"""Identificación de tarjetas por su BIN (los 6 primeros dígitos).

Los datos (marca, tipo, banco emisor y país) vienen de la tabla BinTarjeta, que se
llena con migrate desde datos/bines.csv.gz. No usa internet. Si un BIN no está en la
base, la marca se deduce por rangos.
"""
import logging
import re

logger = logging.getLogger(__name__)

SIN_IDENTIFICAR = "Sin identificar"

# (prefijo desde, prefijo hasta, marca). Se evalúan en orden: los más específicos primero.
RANGOS_MARCA = [
    ("34", "34", "Amex"), ("37", "37", "Amex"),
    ("300", "305", "Diners"), ("36", "36", "Diners"), ("38", "39", "Diners"),
    ("3528", "3589", "JCB"),
    ("2221", "2720", "Mastercard"), ("51", "55", "Mastercard"),
    ("6011", "6011", "Discover"), ("644", "649", "Discover"), ("65", "65", "Discover"),
    ("62", "62", "UnionPay"),
    ("50", "50", "Maestro"), ("56", "58", "Maestro"), ("67", "67", "Maestro"),
    ("4", "4", "Visa"),
]


def bin_de(numero):
    """'4567 89** **** 1234' -> '456789'. None si no trae los 6 primeros dígitos."""
    m = re.match(r"\s*((?:\d\s*){6})", numero or "")
    return re.sub(r"\D", "", m.group(1)) if m else None


def marca_local(bin_):
    for desde, hasta, marca in RANGOS_MARCA:
        if desde <= bin_[:len(desde)] <= hasta:
            return marca
    return SIN_IDENTIFICAR


def identificar_local(bines):
    """Solo la marca por rangos, sin base de datos."""
    return {b: {"marca": marca_local(b)} for b in bines if b}


def identificar(bines):
    """{bin: datos} desde la tabla BinTarjeta; los BIN que no estén quedan solo con la marca.

    Si la tabla no está disponible (p. ej. falta correr migrate), no detiene la
    conciliación: se identifica solo la marca.
    """
    from .models import BinTarjeta  # aquí para que logica_clp siga sin depender de Django

    resultado = identificar_local(bines)
    try:
        for b in BinTarjeta.objects.filter(bin__in=list(resultado)).values():
            resultado[b["bin"]] = b
    except Exception:  # noqa: BLE001 - la identificación es accesoria, nunca debe bloquear
        logger.exception("No se pudo leer la tabla de BIN (¿falta python manage.py migrate?); se muestra solo la marca")
    return resultado


def agrupar(ventas, clave, por_revisar):
    """Cantidad, monto y monto por revisar de las ventas agrupadas por `clave`."""
    grupos = {}
    for v in ventas:
        nombre = v.get(clave) or SIN_IDENTIFICAR
        g = grupos.setdefault(nombre, {"nombre": nombre, "ventas": 0, "monto": 0.0, "por_revisar": 0.0})
        g["ventas"] += 1
        g["monto"] += v["monto"]
        g["por_revisar"] += por_revisar(v)
    return sorted(grupos.values(), key=lambda g: (g["nombre"] == SIN_IDENTIFICAR, -g["monto"]))
