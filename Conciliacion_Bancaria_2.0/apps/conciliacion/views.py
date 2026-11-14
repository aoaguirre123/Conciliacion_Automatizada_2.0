import functools
import logging
from datetime import date, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.utils import timezone

from apps.usuarios.perfiles import es_administrador, solo_administradores, solo_conciliadores

from . import bines, excepciones as ex, graficos, logica, logica_clp, registro, reporte_excepciones
from .dolar import dolar_para, fuente_elegida, fuente_otra
from .forms import ConfiguracionForm, ExcepcionForm
from .models import Conciliacion, Configuracion, Excepcion, Reporte


logger = logging.getLogger(__name__)

SOLO_BORRAR = "Solo un administrador puede borrar conciliaciones del historial."
SOLO_EJEMPLOS = "Solo un administrador puede conciliar con los archivos de ejemplo."
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def solo_post(destino):
    """Como require_POST, pero si alguien abre la dirección en el navegador (GET) lo lleva a
    `destino` en vez de mostrar una página en blanco con el error 405."""
    def decorador(vista):
        @functools.wraps(vista)
        def envoltura(request, *args, **kwargs):
            if request.method != "POST":
                return redirect(destino)
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador

# Archivos predescargados para los botones «Conciliar con archivos de ejemplo».
EJEMPLOS = settings.BASE_DIR / "ejemplos"
SIN_EJEMPLOS = "No hay archivos de ejemplo en el servidor: súbelos a la carpeta {carpeta} del proyecto."


def _identificar(request, clasificar, describir=None):
    """Campo del formulario al que va cada archivo soltado en el recuadro único (lo usa soltar.js).

    `describir(archivo, tipo)` agrega un resumen del contenido, por ejemplo las fechas que trae.
    """
    respuesta = []
    for archivo in request.FILES.getlist("archivos"):
        tipo, motivo = clasificar(archivo)
        detalle = describir(archivo, tipo) if describir and tipo else ""
        respuesta.append({"nombre": archivo.name, "tipo": tipo, "motivo": motivo, "detalle": detalle})
    return JsonResponse({"archivos": respuesta})


def _archivos_ejemplo(carpeta, clasificar):
    """{campo: [archivos]} con los archivos de ejemplo, identificados igual que los que se sueltan en el recuadro.

    Devuelve None si la carpeta no existe o está vacía (no se sube a git: son datos reales del hotel).
    """
    ruta_carpeta = EJEMPLOS / carpeta
    if not ruta_carpeta.is_dir() or not any(ruta_carpeta.iterdir()):
        return None
    por_campo = {}
    for ruta in sorted(ruta_carpeta.iterdir()):
        if ruta.is_file():
            archivo = SimpleUploadedFile(ruta.name, ruta.read_bytes())
            campo, _ = clasificar(archivo)
            if campo:
                por_campo.setdefault(campo, []).append(archivo)
    return por_campo


class NoSeGuardo(Exception):
    """El análisis terminó, pero la base de datos no permitió guardarlo."""


def _guardar_y_mostrar(request, moneda, archivos, nombres, resultado, reportes, cuadrado, por_revisar):
    try:
        conciliacion = registro.guardar(moneda, request.user, archivos, nombres, resultado, reportes, cuadrado, por_revisar)
    except DatabaseError as exc:
        logger.exception("No se pudo guardar la conciliación en el historial")
        raise NoSeGuardo(
            "Los archivos se analizaron, pero no se pudo guardar la conciliación en el historial "
            "(la base de datos no respondió). Intenta de nuevo en unos minutos; si se repite, avisa al administrador."
        ) from exc
    messages.success(request, f"Conciliación N° {conciliacion.pk} guardada en el historial.")
    if request.headers.get("X-Progreso") == "1":
        # Envío desde la pantalla de progreso (progreso.js): el navegador abre el detalle él mismo,
        # así no se pide dos veces ni se pierde el mensaje de arriba.
        return JsonResponse({"url": conciliacion.get_absolute_url()})
    return redirect(conciliacion)


# ---------------------------------------------------------------------------
# Conciliación en dólares
# ---------------------------------------------------------------------------
@login_required
def dolar(request):
    """Recuadro del dólar, que las páginas piden aparte para no esperar a la API al cargar."""
    plantilla = "core/_dolar_tarjeta.html" if request.GET.get("vista") == "tarjeta" else "conciliacion/_dolar_caja.html"
    return render(request, plantilla, dolar_para(request))


def _conciliar_dolares(request, archivos):
    """Procesa y guarda la conciliación: devuelve la redirección al detalle, o la página con los errores."""
    errores = logica.validar_archivos(archivos)
    if not errores:
        try:
            resultado, reportes = logica.procesar(archivos, identificar=bines.identificar,
                                                  parametros=Configuracion.actual().parametros())
        except logica.ArchivoNoValido as exc:
            errores = [str(exc)]
        except Exception as exc:  # se muestra en pantalla y queda en el log
            logger.exception("Error en la conciliación en dólares")
            errores = [f"No se pudieron leer los archivos: {exc}"]
        else:
            resumen = resultado["resumen"]
            try:
                return _guardar_y_mostrar(request, Conciliacion.DOLARES, archivos, logica.NOMBRES_ARCHIVO,
                                          resultado, reportes, resumen["cuadrado"], resumen["por_revisar"])
            except NoSeGuardo as exc:
                errores = [str(exc)]
    return _pagina_dolares(request, errores)


def _pagina_dolares(request, errores=None):
    return render(request, "conciliacion/dolares.html", {
        "fuente_otra": fuente_otra(fuente_elegida(request)),
        "errores": errores,
        "configuracion": Configuracion.actual(),
    })


@login_required
@solo_conciliadores
def dolares(request):
    if request.method == "POST":
        archivos = {f"archivo{n}": request.FILES.get(f"archivo{n}") for n in range(1, 8)}
        # El ERP acepta uno o varios archivos: el BORDERO completo o uno por tarjeta.
        archivos["archivo1"] = request.FILES.getlist("archivo1")
        return _conciliar_dolares(request, archivos)
    return _pagina_dolares(request)


@login_required
@solo_conciliadores
@solo_administradores(mensaje=SOLO_EJEMPLOS, destino="conciliacion:dolares")
@solo_post("conciliacion:dolares")
def ejemplo_dolares(request):
    """Concilia con los archivos predescargados de ejemplos/dolares."""
    por_campo = _archivos_ejemplo("dolares", logica.clasificar)
    if por_campo is None:
        return _pagina_dolares(request, [SIN_EJEMPLOS.format(carpeta="ejemplos/dolares")])
    archivos = {campo: por_campo.get(campo, [None])[0] for campo in logica.NOMBRES_ARCHIVO}
    archivos["archivo1"] = por_campo.get("archivo1", [])
    return _conciliar_dolares(request, archivos)


@login_required
@solo_conciliadores
@solo_post("conciliacion:dolares")
def identificar_dolares(request):
    """Tipo de cada archivo soltado en el recuadro único de la página en dólares."""
    return _identificar(request, logica.clasificar)


# ---------------------------------------------------------------------------
# Conciliación en pesos
# ---------------------------------------------------------------------------
def _validar_clp(archivos):
    errores = []
    if not archivos["bordero"]:
        errores.append("Carga el BORDERO: es la base de la conciliación en pesos.")
    if not archivos["transbank"] and not any(archivos.get(c) for c in logica_clp.ARCHIVOS_TBK):
        errores.append("Carga al menos un archivo «Abonos por día» de Transbank.")
    return errores


def _conciliar_pesos(request, archivos):
    """Procesa y guarda la conciliación: devuelve la redirección al detalle, o la página con los errores."""
    errores = _validar_clp(archivos)
    if not errores:
        try:
            resultado, reportes = logica_clp.procesar(archivos, identificar=bines.identificar,
                                                      parametros=Configuracion.actual().parametros())
        except logica_clp.ArchivoInvalido as exc:
            errores = [str(exc)]
        except Exception as exc:  # se muestra en pantalla y queda en el log
            logger.exception("Error en la conciliación en pesos")
            errores = [f"No se pudieron leer los archivos: {exc}"]
        else:
            resumen = resultado["resumen"]
            try:
                return _guardar_y_mostrar(request, Conciliacion.PESOS, archivos, logica_clp.NOMBRES_ARCHIVO,
                                          resultado, reportes, resumen["cuadrado"], resumen["por_revisar"])
            except NoSeGuardo as exc:
                errores = [str(exc)]
    return _pagina_pesos(request, errores)


def _pagina_pesos(request, errores=None):
    return render(request, "conciliacion/pesos.html", {"errores": errores, "configuracion": Configuracion.actual()})


@login_required
@solo_conciliadores
def pesos(request):
    if request.method == "POST":
        archivos = {campo: request.FILES.get(campo) for campo in logica_clp.NOMBRES_ARCHIVO}
        # BORDERO y Transbank aceptan uno o varios archivos: por tarjeta o medio de pago, o todos juntos.
        archivos["bordero"] = request.FILES.getlist("bordero")
        archivos["transbank"] = request.FILES.getlist("transbank")
        return _conciliar_pesos(request, archivos)
    return _pagina_pesos(request)


@login_required
@solo_conciliadores
@solo_administradores(mensaje=SOLO_EJEMPLOS, destino="conciliacion:pesos")
@solo_post("conciliacion:pesos")
def ejemplo_pesos(request):
    """Concilia con los archivos predescargados de ejemplos/pesos."""
    por_campo = _archivos_ejemplo("pesos", logica_clp.clasificar)
    if por_campo is None:
        return _pagina_pesos(request, [SIN_EJEMPLOS.format(carpeta="ejemplos/pesos")])
    archivos = {campo: por_campo.get(campo, [None])[0] for campo in logica_clp.NOMBRES_ARCHIVO}
    archivos["bordero"] = por_campo.get("bordero", [])
    archivos["transbank"] = por_campo.get("transbank", [])
    return _conciliar_pesos(request, archivos)


@login_required
@solo_conciliadores
@solo_post("conciliacion:pesos")
def identificar_pesos(request):
    """Tipo de cada archivo soltado en el recuadro único de la página en pesos."""
    return _identificar(request, logica_clp.clasificar, logica_clp.describir)


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------
@login_required
def historial(request):
    filtro = _filtro_historial(request.GET)
    for aviso in filtro["avisos"]:
        messages.warning(request, aviso)
    registros = Conciliacion.objects.select_related("usuario").prefetch_related("reportes").defer("resultado")
    registros = _aplicar_filtro(registros, filtro)
    pagina = Paginator(registros, 20).get_page(request.GET.get("pagina"))

    # Totales de lo filtrado: cuántas, cuántas cuadradas y el monto por revisar de cada moneda.
    totales = {fila["moneda"]: fila for fila in registros.order_by().values("moneda").annotate(
        cantidad=Count("pk"), cuadradas=Count("pk", filter=Q(cuadrado=True)), por_revisar=Sum("monto_por_revisar"),
    )}
    return render(request, "conciliacion/historial.html", {
        "pagina": pagina,
        "moneda": filtro["moneda"],
        "filtro": filtro,
        "con_fechas": bool(filtro["desde"] or filtro["hasta"]),
        "total_filtro": pagina.paginator.count,
        "totales_pesos": totales.get(Conciliacion.PESOS),
        "totales_dolares": totales.get(Conciliacion.DOLARES),
        "consulta": _consulta(filtro),
        "consulta_sin_moneda": _consulta(filtro, moneda=""),
        "atajos": _atajos_fechas(filtro),
    })


# ---------------------------------------------------------------------------
# Filtro del historial por moneda y por fechas
# ---------------------------------------------------------------------------
FILTRO_POR = {"periodo": "Período conciliado", "creada": "Fecha en que se hizo"}


def _fecha_param(texto):
    """'2026-09-04' (lo que envía <input type="date">) -> date. None si viene vacío o no es fecha."""
    texto = (texto or "").strip()
    if not texto:
        return None, False
    try:
        return date.fromisoformat(texto), False
    except ValueError:
        return None, True


def _filtro_historial(datos):
    """Lee moneda, «por» (período conciliado o fecha en que se hizo), desde y hasta de GET o POST."""
    moneda = datos.get("moneda", "")
    moneda = moneda if moneda in (Conciliacion.DOLARES, Conciliacion.PESOS) else ""
    por = datos.get("por") if datos.get("por") in FILTRO_POR else "periodo"
    desde, malo_desde = _fecha_param(datos.get("desde"))
    hasta, malo_hasta = _fecha_param(datos.get("hasta"))
    avisos = []
    if malo_desde or malo_hasta:
        avisos.append("Una de las fechas del filtro no es válida y no se usó. Elígela en el calendario.")
    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde
        avisos.append("La fecha «desde» era posterior a «hasta»: se invirtieron.")
    return {"moneda": moneda, "por": por, "por_texto": FILTRO_POR[por], "desde": desde, "hasta": hasta, "avisos": avisos}


def _aplicar_filtro(registros, filtro):
    registros = _filtrar_moneda(registros, filtro["moneda"])
    desde, hasta = filtro["desde"], filtro["hasta"]
    if filtro["por"] == "creada":
        if desde:
            registros = registros.filter(creada__date__gte=desde)
        if hasta:
            registros = registros.filter(creada__date__lte=hasta)
    elif desde or hasta:
        # Período conciliado: las que tienen al menos un día dentro del rango elegido.
        registros = registros.annotate(inicio=Coalesce("desde", "hasta")).filter(hasta__isnull=False)
        if desde:
            registros = registros.filter(hasta__gte=desde)
        if hasta:
            registros = registros.filter(inicio__lte=hasta)
    return registros


def _consulta(filtro, **cambios):
    """Parámetros del filtro para los enlaces (paginación, monedas, volver después de borrar)."""
    valores = {**filtro, **cambios}
    partes = {}
    if valores.get("moneda"):
        partes["moneda"] = valores["moneda"]
    if valores.get("desde") or valores.get("hasta"):
        partes["por"] = valores["por"]
    if valores.get("desde"):
        partes["desde"] = valores["desde"].isoformat()
    if valores.get("hasta"):
        partes["hasta"] = valores["hasta"].isoformat()
    return urlencode(partes)


def _atajos_fechas(filtro):
    hoy = timezone.localdate()
    inicio_mes = hoy.replace(day=1)
    fin_mes_anterior = inicio_mes - timedelta(days=1)
    rangos = [
        ("Este mes", inicio_mes, hoy),
        ("Mes anterior", fin_mes_anterior.replace(day=1), fin_mes_anterior),
        ("Últimos 30 días", hoy - timedelta(days=29), hoy),
        ("Últimos 3 meses", (inicio_mes - timedelta(days=62)).replace(day=1), hoy),
    ]
    return [
        {"texto": texto, "consulta": _consulta(filtro, desde=desde, hasta=hasta),
         "activo": filtro["desde"] == desde and filtro["hasta"] == hasta}
        for texto, desde, hasta in rangos
    ]


def _ids(texto):
    """'4, 7,9' -> [4, 7, 9] (sin repetidos, ignorando lo que no sea número)."""
    ids = []
    for parte in str(texto or "").replace(" ", "").split(","):
        if parte.isdigit() and int(parte) not in ids:
            ids.append(int(parte))
    return ids


def _filtrar_moneda(registros, moneda):
    if moneda in (Conciliacion.DOLARES, Conciliacion.PESOS):
        return registros.filter(moneda=moneda)
    return registros


def _volver_al_historial(datos):
    """Vuelve al historial con el mismo filtro (moneda y fechas) que se estaba viendo."""
    url = reverse("conciliacion:historial")
    consulta = _consulta(_filtro_historial(datos))
    return redirect(f"{url}?{consulta}" if consulta else url)


def _lista_numeros(ids):
    numeros = [f"N° {i}" for i in sorted(ids)]
    if len(numeros) > 10:
        return ", ".join(numeros[:10]) + f" y {len(numeros) - 10} más"
    return ", ".join(numeros)


@login_required
@solo_administradores(mensaje=SOLO_BORRAR, destino="conciliacion:historial")
@solo_post("conciliacion:historial")
def borrar_historial(request):
    """Primer paso: muestra lo que se va a borrar (las seleccionadas o todas) y pide confirmarlo."""
    filtro = _filtro_historial(request.POST)
    moneda = filtro["moneda"]
    if request.POST.get("todas"):
        registros = _aplicar_filtro(Conciliacion.objects.all(), filtro)
    else:
        registros = Conciliacion.objects.filter(pk__in=_ids(",".join(request.POST.getlist("ids"))))
    registros = registros.select_related("usuario").defer("resultado").order_by("-creada", "-pk")
    if not registros:
        messages.warning(request, "Selecciona al menos una conciliación para borrar.")
        return _volver_al_historial(request.POST)
    return render(request, "conciliacion/borrar_confirmar.html", {
        "registros": registros,
        "ids": ",".join(str(c.pk) for c in registros),
        "moneda": moneda,
        "filtro": filtro,
        "con_fechas": bool(filtro["desde"] or filtro["hasta"]),
        "consulta": _consulta(filtro),
        "todas": bool(request.POST.get("todas")),
    })


@login_required
@solo_administradores(mensaje=SOLO_BORRAR, destino="conciliacion:historial")
@solo_post("conciliacion:historial")
def borrar_confirmado(request):
    """Segundo paso: borra solo las conciliaciones confirmadas y comprueba que ya no estén."""
    ids = _ids(request.POST.get("ids"))
    if not ids:
        messages.warning(request, "No había conciliaciones seleccionadas. No se borró nada.")
        return _volver_al_historial(request.POST)
    if not request.POST.get("entiendo"):
        messages.error(request, "No se borró nada: marca la casilla de confirmación para borrar.")
        return _volver_al_historial(request.POST)

    existentes = set(Conciliacion.objects.filter(pk__in=ids).values_list("pk", flat=True))
    Conciliacion.objects.filter(pk__in=existentes).delete()  # sus Excel se borran en cascada

    # Doble verificación: se vuelve a consultar que no quede ninguna.
    quedan = set(Conciliacion.objects.filter(pk__in=existentes).values_list("pk", flat=True))
    borradas = existentes - quedan
    if quedan:
        logger.error("No se borraron las conciliaciones %s", sorted(quedan))
        messages.error(request, f"No se pudieron borrar: {_lista_numeros(quedan)}. Intenta de nuevo.")
    if borradas:
        n = len(borradas)
        if n == 1:
            texto = f"Se borró 1 conciliación del historial ({_lista_numeros(borradas)}). Se verificó que ya no está."
        else:
            texto = f"Se borraron {n} conciliaciones del historial ({_lista_numeros(borradas)}). Se verificó que ya no están."
        messages.success(request, texto)
    ya_no_estaban = set(ids) - existentes
    if ya_no_estaban:
        messages.info(request, f"Ya no estaban en el historial: {_lista_numeros(ya_no_estaban)}.")
    return _volver_al_historial(request.POST)


@login_required
def detalle(request, pk):
    conciliacion = Conciliacion.objects.select_related("usuario").filter(pk=pk).first()
    if conciliacion is None:
        messages.warning(request, f"La conciliación N° {pk} no existe o fue borrada del historial.")
        return redirect("conciliacion:historial")
    contexto = {"conciliacion": conciliacion, "reportes": conciliacion.reportes.defer("contenido")}
    contexto.update(conciliacion.resultado)
    contexto["grafico"] = graficos.preparar(conciliacion.resultado, conciliacion.moneda)
    lista = list(conciliacion.excepciones.select_related("actualizada_por"))
    for e in lista:
        e.conciliacion = conciliacion  # evita una consulta por excepción
    contexto["lista_excepciones"] = lista
    contexto["excepciones_por_estado"] = _contar_por_estado([e for e in lista if e.vigente])
    contexto["excepciones_reemplazadas"] = sum(1 for e in lista if not e.vigente)
    contexto["excepciones_antiguas"] = not lista and "graficos" not in conciliacion.resultado
    contexto["estados_excepcion"] = ex.ESTADOS
    contexto["categorias_excepcion"] = ex.CATEGORIAS
    contexto["consulta_exportar_conciliacion"] = urlencode({"conciliacion": conciliacion.pk, "estado": "todas"})
    if conciliacion.moneda == Conciliacion.PESOS and "observaciones" in conciliacion.resultado:
        # Las conciliaciones guardadas antes de la v3.6.3 traen las diferencias aceptadas mezcladas.
        filas = conciliacion.resultado["observaciones"]
        contexto["observaciones"] = [f for f in filas if not logica_clp.diferencia_aceptada(f)]
        contexto["aceptadas"] = conciliacion.resultado.get("aceptadas", []) + [
            f for f in filas if logica_clp.diferencia_aceptada(f)
        ]
    return render(request, "conciliacion/detalle.html", contexto)


@login_required
def descargar(request, pk, clave):
    reporte = Reporte.objects.filter(conciliacion_id=pk, clave=clave).first()
    if reporte is None:
        if Conciliacion.objects.filter(pk=pk).exists():
            messages.warning(request, "Ese reporte no existe para esta conciliación. Descarga uno de la lista.")
            return redirect("conciliacion:detalle", pk=pk)
        messages.warning(request, f"La conciliación N° {pk} no existe o fue borrada del historial.")
        return redirect("conciliacion:historial")
    respuesta = HttpResponse(bytes(reporte.contenido), content_type=XLSX)
    nombre = reporte.nombre_archivo.replace(".xlsx", f"_{pk}.xlsx")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


# Módulo que falta -> paquete que se instala con pip.
PAQUETES_PDF = {"reportlab": "reportlab", "PIL": "pillow", "charset_normalizer": "charset-normalizer", "chardet": "chardet"}


def _sin_pdf(exc, que="los documentos"):
    """Aviso cuando falta una librería para el PDF, con el nombre exacto de la que falta."""
    modulo = (getattr(exc, "name", None) or "reportlab").split(".")[0]
    paquete = PAQUETES_PDF.get(modulo, modulo)
    return (f"No se pudo generar el PDF: falta instalar la librería «{paquete}» en el servidor. "
            f"Instálala con «pip install {paquete}» (o «pip install -r requirements.txt», que instala todo lo "
            f"necesario) y recarga la aplicación. Mientras tanto, descarga {que} en Excel.")


def _respuesta_pdf(contenido, nombre):
    respuesta = HttpResponse(contenido, content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


def _documentos_en_pdf(request, conciliacion, reportes, nombre):
    try:
        from . import pdf_documentos
        usuario = request.user.get_full_name() or request.user.get_username()
        contenido = pdf_documentos.generar(conciliacion, reportes, usuario)
    except ImportError as exc:
        logger.exception("Falta una librería para generar PDF")
        messages.error(request, _sin_pdf(exc))
        return redirect(conciliacion)
    except Exception:  # se informa en pantalla y queda en el log
        logger.exception("No se pudo generar el PDF de la conciliación %s", conciliacion.pk)
        messages.error(request, "No se pudo generar el PDF. Intenta de nuevo o descarga el Excel; si se repite, avisa al administrador.")
        return redirect(conciliacion)
    return _respuesta_pdf(contenido, nombre)


@login_required
def descargar_pdf(request, pk, clave):
    """Un documento de la conciliación en PDF (el mismo contenido que su Excel)."""
    reporte = Reporte.objects.select_related("conciliacion").filter(conciliacion_id=pk, clave=clave).first()
    if reporte is None:
        if Conciliacion.objects.filter(pk=pk).exists():
            messages.warning(request, "Ese documento no existe para esta conciliación. Descarga uno de la lista.")
            return redirect("conciliacion:detalle", pk=pk)
        messages.warning(request, f"La conciliación N° {pk} no existe o fue borrada del historial.")
        return redirect("conciliacion:historial")
    nombre = reporte.nombre_archivo.replace(".xlsx", f"_{pk}.pdf")
    return _documentos_en_pdf(request, reporte.conciliacion, [reporte], nombre)


@login_required
def descargar_todo_pdf(request, pk):
    """Todos los documentos de la conciliación en un solo PDF, con una portada con su resumen."""
    conciliacion = Conciliacion.objects.select_related("usuario").filter(pk=pk).first()
    if conciliacion is None:
        messages.warning(request, f"La conciliación N° {pk} no existe o fue borrada del historial.")
        return redirect("conciliacion:historial")
    reportes = list(conciliacion.reportes.all())
    if not reportes:
        messages.warning(request, "Esta conciliación no tiene documentos guardados.")
        return redirect(conciliacion)
    nombre = f"conciliacion_{'pesos' if conciliacion.moneda == Conciliacion.PESOS else 'dolares'}_{pk}.pdf"
    return _documentos_en_pdf(request, conciliacion, reportes, nombre)


# ---------------------------------------------------------------------------
# Configuración (solo administradores)
# ---------------------------------------------------------------------------
SOLO_ADMINISTRADORES = "La configuración solo la pueden ver y cambiar los administradores."


def _es_administrador(request):
    if es_administrador(request.user):
        return True
    messages.error(request, SOLO_ADMINISTRADORES)
    return False


@login_required
def configuracion(request):
    """Tolerancias, ventana de días y palabras clave de la cartola. Solo para administradores."""
    if not _es_administrador(request):
        return redirect("core:inicio")
    actual = Configuracion.actual()
    if request.method == "POST":
        formulario = ConfiguracionForm(request.POST, instance=actual)
        if formulario.is_valid():
            config = formulario.save(commit=False)
            config.actualizada_por = request.user
            config.save()
            messages.success(request, "Configuración guardada. Se aplicará en las próximas conciliaciones.")
            return redirect("conciliacion:configuracion")
        # Con errores no se guarda nada: siguen vigentes los valores anteriores.
    else:
        formulario = ConfiguracionForm(instance=actual)
    return render(request, "conciliacion/configuracion.html", {
        "formulario": formulario,
        "actual": actual,
        "guardada": actual._state.adding is False,
        "por_defecto": actual.es_por_defecto(),
    })


@login_required
@solo_post("conciliacion:configuracion")
def restablecer_configuracion(request):
    """Vuelve todos los parámetros a sus valores por defecto."""
    if not _es_administrador(request):
        return redirect("core:inicio")
    config = Configuracion.actual()
    config.restablecer()
    config.actualizada_por = request.user
    config.save()
    messages.success(request, "Se restablecieron los valores por defecto.")
    return redirect("conciliacion:configuracion")


# ---------------------------------------------------------------------------
# Excepciones (CU-04): lista general y gestión de cada una
# ---------------------------------------------------------------------------
ABIERTAS = (Excepcion.PENDIENTE, Excepcion.EN_REVISION)
FILTRO_ESTADO = {
    "abiertas": "Por gestionar",
    Excepcion.PENDIENTE: "Pendientes",
    Excepcion.EN_REVISION: "En revisión",
    Excepcion.RESUELTA: "Resueltas",
    "todas": "Todas",
}


def _contar_por_estado(excepciones):
    cuenta = {clave: 0 for clave, _ in ex.ESTADOS}
    for e in excepciones:
        cuenta[e.estado] += 1
    return cuenta


def _filtro_excepciones(datos):
    """Filtros del módulo de excepciones y de su exportación (GET)."""
    desde, malo_desde = _fecha_param(datos.get("desde"))
    hasta, malo_hasta = _fecha_param(datos.get("hasta"))
    avisos = []
    if malo_desde or malo_hasta:
        avisos.append("Una de las fechas del filtro no es válida y no se usó. Elígela en el calendario.")
    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde
        avisos.append("La fecha «desde» era posterior a «hasta»: se invirtieron.")
    conciliacion = datos.get("conciliacion", "")
    return {
        "estado": datos.get("estado") if datos.get("estado") in FILTRO_ESTADO else "abiertas",
        "categoria": datos.get("categoria") if datos.get("categoria") in ex.NOMBRE_CATEGORIA else "",
        "moneda": datos.get("moneda") if datos.get("moneda") in (Conciliacion.DOLARES, Conciliacion.PESOS) else "",
        "desde": desde,
        "hasta": hasta,
        "conciliacion": int(conciliacion) if str(conciliacion).isdigit() else None,
        "avisos": avisos,
    }


def _consulta_excepciones(filtro, **cambios):
    valores = {**filtro, **cambios}
    partes = {}
    for clave in ("estado", "categoria", "moneda", "conciliacion"):
        if valores.get(clave) and not (clave == "estado" and valores[clave] == "abiertas"):
            partes[clave] = valores[clave]
    for clave in ("desde", "hasta"):
        if valores.get(clave):
            partes[clave] = valores[clave].isoformat()
    return urlencode(partes)


def _excepciones_filtradas(filtro):
    """(base sin filtro de estado ni tipo, filtradas por todo). Una conciliación puntual trae todas las
    suyas; la lista general, solo las vigentes (la última vez que se concilió cada venta)."""
    base = Excepcion.objects.select_related("conciliacion", "actualizada_por").defer("conciliacion__resultado")
    if filtro["conciliacion"]:
        base = base.filter(conciliacion_id=filtro["conciliacion"])
    else:
        base = base.filter(vigente=True)
    if filtro["moneda"]:
        base = base.filter(conciliacion__moneda=filtro["moneda"])
    if filtro["desde"]:
        base = base.filter(fecha__gte=filtro["desde"])
    if filtro["hasta"]:
        base = base.filter(fecha__lte=filtro["hasta"])
    registros = base
    if filtro["estado"] == "abiertas":
        registros = registros.filter(estado__in=ABIERTAS)
    elif filtro["estado"] != "todas":
        registros = registros.filter(estado=filtro["estado"])
    sin_tipo = registros
    if filtro["categoria"]:
        registros = registros.filter(categoria=filtro["categoria"])
    return base, sin_tipo, registros.order_by("-conciliacion__creada", "conciliacion_id", "orden")


@login_required
def excepciones(request):
    """Todas las excepciones de las conciliaciones, para ir gestionándolas (por defecto, las abiertas)."""
    filtro = _filtro_excepciones(request.GET)
    filtro["conciliacion"] = None  # la lista general es de todas las conciliaciones
    for aviso in filtro["avisos"]:
        messages.warning(request, aviso)
    base, sin_tipo, registros = _excepciones_filtradas(filtro)
    por_estado = {fila["estado"]: fila["n"] for fila in base.order_by().values("estado").annotate(n=Count("pk"))}
    por_categoria = {fila["categoria"]: fila["n"] for fila in sin_tipo.order_by().values("categoria").annotate(n=Count("pk"))}
    pagina = Paginator(registros, 25).get_page(request.GET.get("pagina"))
    consulta = lambda **cambios: _consulta_excepciones(filtro, **cambios)  # noqa: E731

    return render(request, "conciliacion/excepciones.html", {
        "pagina": pagina,
        "filtro": filtro,
        "estado": filtro["estado"],
        "categoria": filtro["categoria"],
        "moneda": filtro["moneda"],
        "con_fechas": bool(filtro["desde"] or filtro["hasta"]),
        "filtros_estado": [
            {"clave": clave, "texto": texto, "consulta": consulta(estado=clave, categoria=""), "activo": clave == filtro["estado"],
             "n": sum(por_estado.get(e, 0) for e in ABIERTAS) if clave == "abiertas"
             else sum(por_estado.values()) if clave == "todas" else por_estado.get(clave, 0)}
            for clave, texto in FILTRO_ESTADO.items()
        ],
        "filtros_categoria": [
            {"clave": clave, "texto": texto, "n": por_categoria[clave], "activo": clave == filtro["categoria"],
             "consulta": consulta(categoria="" if clave == filtro["categoria"] else clave)}
            for clave, texto in ex.CATEGORIAS if por_categoria.get(clave)
        ],
        "consulta_moneda": {m: consulta(moneda=m) for m in (Conciliacion.DOLARES, Conciliacion.PESOS)},
        "consulta_sin_moneda": consulta(moneda=""),
        "consulta_sin_fechas": consulta(desde=None, hasta=None),
        "consulta_sin_tipo": consulta(categoria=""),
        "texto_categoria": ex.NOMBRE_CATEGORIA.get(filtro["categoria"], ""),
        "filtrado": bool(filtro["categoria"] or filtro["moneda"] or filtro["desde"] or filtro["hasta"]
                         or filtro["estado"] != "abiertas"),
        "estados_excepcion": ex.ESTADOS,
        "categorias_excepcion": ex.CATEGORIAS,
        "consulta": consulta(),
        "texto_estado": FILTRO_ESTADO[filtro["estado"]],
    })


@login_required
def exportar_excepciones(request):
    """CU-05: reporte de excepciones en PDF ejecutivo o Excel, con los mismos filtros de la lista."""
    filtro = _filtro_excepciones(request.GET)
    formato = "pdf" if request.GET.get("formato") == "pdf" else "xlsx"
    conciliacion = None
    if filtro["conciliacion"]:
        conciliacion = Conciliacion.objects.defer("resultado").filter(pk=filtro["conciliacion"]).first()
        if conciliacion is None:
            messages.warning(request, f"La conciliación N° {filtro['conciliacion']} no existe o fue borrada del historial.")
            return redirect("conciliacion:historial")
    _, _, registros = _excepciones_filtradas(filtro)
    datos = reporte_excepciones.Datos(
        excepciones=list(registros),
        filtro=filtro,
        texto_estado=FILTRO_ESTADO[filtro["estado"]],
        conciliacion=conciliacion,
        usuario=request.user.get_full_name() or request.user.get_username(),
        generado=timezone.localtime(),
    )
    try:
        contenido = reporte_excepciones.pdf(datos) if formato == "pdf" else reporte_excepciones.excel(datos)
    except ImportError as exc:
        logger.exception("Falta una librería para generar PDF")
        messages.error(request, _sin_pdf(exc, "el reporte"))
        return redirect(conciliacion.get_absolute_url() if conciliacion else "conciliacion:excepciones")
    except Exception:  # se informa en pantalla y queda en el log
        logger.exception("No se pudo generar el reporte de excepciones")
        messages.error(request, "No se pudo generar el reporte. Intenta de nuevo; si se repite, avisa al administrador.")
        return redirect(conciliacion.get_absolute_url() if conciliacion else "conciliacion:excepciones")
    nombre = f"excepciones_conciliacion_{conciliacion.pk}" if conciliacion else f"excepciones_{datos.generado:%Y-%m-%d}"
    tipo = "application/pdf" if formato == "pdf" else XLSX
    respuesta = HttpResponse(contenido, content_type=tipo)
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}.{formato}"'
    return respuesta


def _volver(request, excepcion):
    destino = request.POST.get("next") or ""
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(f"{destino.split('#')[0]}#excepcion-{excepcion.pk}")
    return redirect(excepcion.get_absolute_url())


@login_required
@solo_conciliadores(destino="conciliacion:excepciones")
@solo_post("conciliacion:excepciones")
def gestionar_excepcion(request, pk):
    excepcion = Excepcion.objects.select_related("conciliacion").filter(pk=pk).first()
    if excepcion is None:
        messages.warning(request, "Esa excepción ya no existe: la conciliación fue borrada del historial.")
        return redirect("conciliacion:excepciones")
    if not excepcion.vigente and excepcion.reemplazada_por_id:
        messages.info(request, f"Esa venta se volvió a conciliar: gestiónala en la conciliación N° {excepcion.reemplazada_por_id}.")
        return redirect(excepcion.reemplazada_por)
    categoria_antes = excepcion.categoria
    formulario = ExcepcionForm(request.POST, instance=excepcion)
    if not formulario.is_valid():
        errores = [e for lista in formulario.errors.values() for e in lista]
        messages.error(request, f"No se guardó la excepción {excepcion.codigo or ''}: " + " ".join(errores))
        return _volver(request, excepcion)
    excepcion = formulario.save(commit=False)
    if excepcion.categoria != categoria_antes:
        excepcion.sugerencia = ex.sugerencia_de(excepcion.categoria, excepcion.caso())
    excepcion.actualizada = timezone.now()
    excepcion.actualizada_por = request.user
    excepcion.save()
    texto = f"Excepción {excepcion.codigo or ''} guardada: {excepcion.get_estado_display().lower()}"
    if excepcion.categoria != categoria_antes:
        texto += f", ahora como «{excepcion.get_categoria_display()}»"
    messages.success(request, texto + ".")
    return _volver(request, excepcion)


@login_required
@solo_conciliadores(destino="conciliacion:excepciones")
@solo_post("conciliacion:excepciones")
def gestionar_varias(request):
    """Cambia el estado de varias excepciones a la vez y agrega la misma observación a todas."""
    destino = request.POST.get("next") or ""
    volver = (redirect(destino) if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()) else redirect("conciliacion:excepciones"))
    ids = [int(i) for i in request.POST.getlist("ids") if str(i).isdigit()]
    estado = request.POST.get("estado")
    if estado not in ex.NOMBRE_ESTADO:
        messages.error(request, "Elige el nuevo estado para las excepciones seleccionadas.")
        return volver
    if not ids:
        messages.warning(request, "Selecciona al menos una excepción.")
        return volver
    comentario = (request.POST.get("comentario") or "").strip()[:1000]
    ahora = timezone.now()
    excepciones_sel = list(Excepcion.objects.filter(pk__in=ids, vigente=True))
    for e in excepciones_sel:
        e.estado = estado
        if comentario and comentario not in (e.comentario or ""):
            e.comentario = f"{e.comentario}\n{comentario}".strip() if e.comentario else comentario
        e.actualizada, e.actualizada_por = ahora, request.user
    Excepcion.objects.bulk_update(excepciones_sel, ["estado", "comentario", "actualizada", "actualizada_por"])
    n = len(excepciones_sel)
    if not n:
        messages.warning(request, "Las excepciones seleccionadas ya no están vigentes: se volvieron a conciliar.")
        return volver
    omitidas = len(set(ids)) - n
    texto = f"Se {'actualizó' if n == 1 else 'actualizaron'} {n} excepci{'ón' if n == 1 else 'ones'}: {ex.NOMBRE_ESTADO[estado].lower()}"
    if comentario:
        texto += ", con la observación"
    texto += "."
    if omitidas > 0:
        texto += f" {omitidas} no se cambiaron porque se volvieron a conciliar."
    messages.success(request, texto)
    return volver
