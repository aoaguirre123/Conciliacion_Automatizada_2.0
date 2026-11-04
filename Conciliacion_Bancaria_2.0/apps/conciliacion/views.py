import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import bines, logica, logica_clp, registro
from .dolar import dolar_para, fuente_elegida, fuente_otra
from .models import Conciliacion, Reporte

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Archivos predescargados para los botones «Conciliar con archivos de ejemplo».
EJEMPLOS = settings.BASE_DIR / "ejemplos"
SIN_EJEMPLOS = "No hay archivos de ejemplo en el servidor: súbelos a la carpeta {carpeta} del proyecto."


def _identificar(request, clasificar):
    """Campo del formulario al que va cada archivo soltado en el recuadro único (lo usa soltar.js)."""
    respuesta = []
    for archivo in request.FILES.getlist("archivos"):
        tipo, motivo = clasificar(archivo)
        respuesta.append({"nombre": archivo.name, "tipo": tipo, "motivo": motivo})
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


def _guardar_y_mostrar(request, moneda, archivos, nombres, resultado, reportes, cuadrado, por_revisar):
    conciliacion = registro.guardar(moneda, request.user, archivos, nombres, resultado, reportes, cuadrado, por_revisar)
    messages.success(request, f"Conciliación N° {conciliacion.pk} guardada en el historial.")
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
            resultado, reportes = logica.procesar(archivos, identificar=bines.identificar)
        except logica.ArchivoNoValido as exc:
            errores = [str(exc)]
        except Exception as exc:  # se muestra en pantalla y queda en el log
            logger.exception("Error en la conciliación en dólares")
            errores = [f"No se pudieron leer los archivos: {exc}"]
        else:
            resumen = resultado["resumen"]
            return _guardar_y_mostrar(request, Conciliacion.DOLARES, archivos, logica.NOMBRES_ARCHIVO,
                                      resultado, reportes, resumen["cuadrado"], abs(resumen["diferencia_total"]))
    return _pagina_dolares(request, errores)


def _pagina_dolares(request, errores=None):
    return render(request, "conciliacion/dolares.html", {
        "fuente_otra": fuente_otra(fuente_elegida(request)),
        "errores": errores,
    })


@login_required
def dolares(request):
    if request.method == "POST":
        archivos = {f"archivo{n}": request.FILES.get(f"archivo{n}") for n in range(1, 8)}
        return _conciliar_dolares(request, archivos)
    return _pagina_dolares(request)


@login_required
@require_POST
def ejemplo_dolares(request):
    """Concilia con los archivos predescargados de ejemplos/dolares."""
    por_campo = _archivos_ejemplo("dolares", logica.clasificar)
    if por_campo is None:
        return _pagina_dolares(request, [SIN_EJEMPLOS.format(carpeta="ejemplos/dolares")])
    archivos = {campo: por_campo.get(campo, [None])[0] for campo in logica.NOMBRES_ARCHIVO}
    return _conciliar_dolares(request, archivos)


@login_required
@require_POST
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
            resultado, reportes = logica_clp.procesar(archivos, identificar=bines.identificar)
        except logica_clp.ArchivoInvalido as exc:
            errores = [str(exc)]
        except Exception as exc:  # se muestra en pantalla y queda en el log
            logger.exception("Error en la conciliación en pesos")
            errores = [f"No se pudieron leer los archivos: {exc}"]
        else:
            resumen = resultado["resumen"]
            return _guardar_y_mostrar(request, Conciliacion.PESOS, archivos, logica_clp.NOMBRES_ARCHIVO,
                                      resultado, reportes, resumen["cuadrado"], resumen["por_revisar"])
    return _pagina_pesos(request, errores)


def _pagina_pesos(request, errores=None):
    return render(request, "conciliacion/pesos.html", {"errores": errores})


@login_required
def pesos(request):
    if request.method == "POST":
        archivos = {campo: request.FILES.get(campo) for campo in logica_clp.NOMBRES_ARCHIVO}
        # Transbank acepta uno o varios archivos: separados por medio de pago o todos juntos.
        archivos["transbank"] = request.FILES.getlist("transbank")
        return _conciliar_pesos(request, archivos)
    return _pagina_pesos(request)


@login_required
@require_POST
def ejemplo_pesos(request):
    """Concilia con los archivos predescargados de ejemplos/pesos."""
    por_campo = _archivos_ejemplo("pesos", logica_clp.clasificar)
    if por_campo is None:
        return _pagina_pesos(request, [SIN_EJEMPLOS.format(carpeta="ejemplos/pesos")])
    archivos = {campo: por_campo.get(campo, [None])[0] for campo in logica_clp.NOMBRES_ARCHIVO}
    archivos["transbank"] = por_campo.get("transbank", [])
    return _conciliar_pesos(request, archivos)


@login_required
@require_POST
def identificar_pesos(request):
    """Tipo de cada archivo soltado en el recuadro único de la página en pesos."""
    return _identificar(request, logica_clp.clasificar)


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------
@login_required
def historial(request):
    moneda = request.GET.get("moneda", "")
    registros = Conciliacion.objects.select_related("usuario").prefetch_related("reportes").defer("resultado")
    if moneda in (Conciliacion.DOLARES, Conciliacion.PESOS):
        registros = registros.filter(moneda=moneda)
    pagina = Paginator(registros, 20).get_page(request.GET.get("pagina"))
    return render(request, "conciliacion/historial.html", {
        "pagina": pagina, "moneda": moneda, "total_historial": Conciliacion.objects.count(),
    })


@login_required
@require_POST
def borrar_historial(request):
    """Borra todas las conciliaciones, en pesos y en dólares (y sus Excel), para dejar el historial limpio."""
    total = Conciliacion.objects.count()
    Conciliacion.objects.all().delete()
    if total == 1:
        texto = "Se borró 1 conciliación del historial."
    elif total:
        texto = f"Se borraron {total} conciliaciones del historial."
    else:
        texto = "No había conciliaciones en el historial."
    messages.success(request, texto)
    return redirect("conciliacion:historial")


@login_required
def detalle(request, pk):
    conciliacion = get_object_or_404(Conciliacion.objects.select_related("usuario"), pk=pk)
    contexto = {"conciliacion": conciliacion, "reportes": conciliacion.reportes.defer("contenido")}
    contexto.update(conciliacion.resultado)
    return render(request, "conciliacion/detalle.html", contexto)


@login_required
def descargar(request, pk, clave):
    reporte = get_object_or_404(Reporte, conciliacion_id=pk, clave=clave)
    respuesta = HttpResponse(bytes(reporte.contenido), content_type=XLSX)
    nombre = reporte.nombre_archivo.replace(".xlsx", f"_{pk}.xlsx")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta
