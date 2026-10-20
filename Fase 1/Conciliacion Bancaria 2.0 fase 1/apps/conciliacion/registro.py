"""Guarda cada conciliación en la base de datos para poder volver a verla."""
import json
import math
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction

from .models import Conciliacion, Reporte


def _a_json(valor):
    """Convierte tipos de numpy/pandas/fechas a tipos que JSONField acepta."""
    if isinstance(valor, dict):
        return {str(k): _a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_a_json(v) for v in valor]
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    if hasattr(valor, "item"):  # numpy
        valor = valor.item()
    if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
        return None
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return str(valor)


def _descripcion_archivos(archivos, nombres):
    return [
        {"campo": campo, "etiqueta": nombres.get(campo, campo), "nombre": archivo.name, "tamano": archivo.size}
        for campo, archivo in archivos.items() if archivo
    ]


@transaction.atomic
def guardar(moneda, usuario, archivos, nombres, resultado, reportes, cuadrado, por_revisar):
    registro = Conciliacion.objects.create(
        moneda=moneda,
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        archivos=_descripcion_archivos(archivos, nombres),
        cuadrado=bool(cuadrado),
        monto_por_revisar=Decimal(str(round(float(por_revisar or 0), 2))),
        resultado=json.loads(json.dumps(_a_json(resultado))),
    )
    Reporte.objects.bulk_create([
        Reporte(conciliacion=registro, clave=clave, titulo=titulo, descripcion=descripcion,
                nombre_archivo=nombre, contenido=contenido, orden=i)
        for i, (clave, titulo, descripcion, nombre, contenido) in enumerate(reportes)
    ])
    return registro
