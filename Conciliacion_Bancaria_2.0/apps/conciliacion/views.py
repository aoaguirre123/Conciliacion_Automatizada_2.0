import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from . import bines, logica, logica_clp, registro
from .dolar import obtener_serie_dolar
from .models import Conciliacion, Reporte

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _dolar():
    serie = obtener_serie_dolar()
    return serie[0] if serie else None


def _guardar_y_mostrar(request, moneda, archivos, nombres, resultado, reportes, cuadrado, por_revisar):
    conciliacion = registro.guardar(moneda, request.user, archivos, nombres, resultado, reportes, cuadrado, por_revisar)
    messages.success(request, f"Conciliación N° {conciliacion.pk} guardada en el historial.")
    return redirect(conciliacion)


# ---------------------------------------------------------------------------
# Conciliación en dólares
# ---------------------------------------------------------------------------
@login_required
def dolares(request):
    contexto = {"dolar_hoy": _dolar()}
    if request.method == "POST":
        archivos = {f"archivo{n}": request.FILES.get(f"archivo{n}") for n in range(1, 8)}
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
        contexto["errores"] = errores
    return render(request, "conciliacion/dolares.html", contexto)


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


@login_required
def pesos(request):
    contexto = {}
    if request.method == "POST":
        archivos = {campo: request.FILES.get(campo) for campo in logica_clp.NOMBRES_ARCHIVO}
        # Transbank acepta uno o varios archivos: separados por medio de pago o todos juntos.
        archivos["transbank"] = request.FILES.getlist("transbank")
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
        contexto["errores"] = errores
    return render(request, "conciliacion/pesos.html", contexto)


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
    return render(request, "conciliacion/historial.html", {"pagina": pagina, "moneda": moneda})


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
