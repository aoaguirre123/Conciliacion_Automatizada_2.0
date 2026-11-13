import functools
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.usuarios.perfiles import es_administrador, solo_administradores, solo_conciliadores

from . import bines, graficos, logica, logica_clp, registro
from .dolar import dolar_para, fuente_elegida, fuente_otra
from .forms import ConfiguracionForm
from .models import Conciliacion, Configuracion, Reporte


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
    moneda = request.GET.get("moneda", "")
    registros = Conciliacion.objects.select_related("usuario").prefetch_related("reportes").defer("resultado")
    registros = _filtrar_moneda(registros, moneda)
    pagina = Paginator(registros, 20).get_page(request.GET.get("pagina"))
    return render(request, "conciliacion/historial.html", {
        "pagina": pagina, "moneda": moneda, "total_filtro": pagina.paginator.count,
    })


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


def _volver_al_historial(moneda):
    url = reverse("conciliacion:historial")
    return redirect(f"{url}?moneda={moneda}" if moneda in (Conciliacion.DOLARES, Conciliacion.PESOS) else url)


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
    moneda = request.POST.get("moneda", "")
    if request.POST.get("todas"):
        registros = _filtrar_moneda(Conciliacion.objects.all(), moneda)
    else:
        registros = Conciliacion.objects.filter(pk__in=_ids(",".join(request.POST.getlist("ids"))))
    registros = registros.select_related("usuario").defer("resultado").order_by("-creada", "-pk")
    if not registros:
        messages.warning(request, "Selecciona al menos una conciliación para borrar.")
        return _volver_al_historial(moneda)
    return render(request, "conciliacion/borrar_confirmar.html", {
        "registros": registros,
        "ids": ",".join(str(c.pk) for c in registros),
        "moneda": moneda,
        "todas": bool(request.POST.get("todas")),
    })


@login_required
@solo_administradores(mensaje=SOLO_BORRAR, destino="conciliacion:historial")
@solo_post("conciliacion:historial")
def borrar_confirmado(request):
    """Segundo paso: borra solo las conciliaciones confirmadas y comprueba que ya no estén."""
    moneda = request.POST.get("moneda", "")
    ids = _ids(request.POST.get("ids"))
    if not ids:
        messages.warning(request, "No había conciliaciones seleccionadas. No se borró nada.")
        return _volver_al_historial(moneda)
    if not request.POST.get("entiendo"):
        messages.error(request, "No se borró nada: marca la casilla de confirmación para borrar.")
        return _volver_al_historial(moneda)

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
    return _volver_al_historial(moneda)


@login_required
def detalle(request, pk):
    conciliacion = Conciliacion.objects.select_related("usuario").filter(pk=pk).first()
    if conciliacion is None:
        messages.warning(request, f"La conciliación N° {pk} no existe o fue borrada del historial.")
        return redirect("conciliacion:historial")
    contexto = {"conciliacion": conciliacion, "reportes": conciliacion.reportes.defer("contenido")}
    contexto.update(conciliacion.resultado)
    contexto["grafico"] = graficos.preparar(conciliacion.resultado, conciliacion.moneda)
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
