"""Identificación de tarjetas por su BIN (los 6 primeros dígitos).

La marca se deduce aquí mismo por rangos, sin internet. El banco emisor, el país y el
tipo (crédito, débito, prepago) se consultan a HandyAPI y se guardan en la tabla
BinTarjeta, así cada BIN se consulta una sola vez.

Al servicio solo se envían los 6 dígitos del BIN, nunca el número de la tarjeta.
La API key es opcional (HANDYAPI_KEY): sin ella HandyAPI responde con un cupo
público más bajo.
"""
import logging
import re
import time

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

URL_HANDYAPI = "https://data.handyapi.com/bin/{}"
# Tiempo máximo que una conciliación espera a la API; lo que no alcance queda solo con la marca.
TIEMPO_MAXIMO_CONSULTAS = 15

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

TIPOS = {"CREDIT": "Crédito", "DEBIT": "Débito", "PREPAID": "Prepago", "CHARGE": "Crédito"}
MARCAS_API = {"VISA": "Visa", "MASTERCARD": "Mastercard", "AMEX": "Amex", "AMERICAN EXPRESS": "Amex",
              "DINERS CLUB": "Diners", "DINERS": "Diners", "DISCOVER": "Discover", "JCB": "JCB",
              "UNIONPAY": "UnionPay", "CHINA UNION PAY": "UnionPay", "MAESTRO": "Maestro"}


def bin_de(numero):
    """'4567 89** **** 1234' -> '456789'. None si no trae los 6 primeros dígitos."""
    m = re.match(r"\s*((?:\d\s*){6})", numero or "")
    return re.sub(r"\D", "", m.group(1)) if m else None


def marca_local(bin_):
    for desde, hasta, marca in RANGOS_MARCA:
        prefijo = bin_[:len(desde)]
        if desde <= prefijo <= hasta:
            return marca
    return SIN_IDENTIFICAR


def _info(bin_, marca=None, tipo="", banco="", pais="", pais_codigo="", nivel="", fuente="local"):
    return {"bin": bin_, "marca": marca or marca_local(bin_), "tipo": tipo, "banco": banco,
            "pais": pais, "pais_codigo": pais_codigo, "nivel": nivel, "fuente": fuente}


def _consultar_handyapi(cliente, bin_):
    """Datos del BIN según HandyAPI, o None si no se pudo consultar."""
    clave = getattr(settings, "HANDYAPI_KEY", "")
    respuesta = cliente.get(URL_HANDYAPI.format(bin_), headers={"x-api-key": clave} if clave else {})
    if respuesta.status_code == 429:
        raise _CupoAgotado()
    respuesta.raise_for_status()
    datos = respuesta.json()
    estado = str(datos.get("Status", "")).upper()
    if estado != "SUCCESS":
        # El cupo agotado llega con HTTP 200 y Status "RATE LIMIT EXCEEDED: ...".
        if "LIMIT" in estado or "QUOTA" in estado:
            raise _CupoAgotado()
        if "NOT FOUND" in estado:
            return _info(bin_, fuente="handyapi")  # BIN desconocido: se guarda para no repetir
        raise ValueError(f"Respuesta inesperada de HandyAPI: {datos.get('Status')}")

    def campo(valor):
        texto = str(valor or "").strip()
        return "" if texto.upper() == "UNKNOWN" else texto

    pais = datos.get("Country") if isinstance(datos.get("Country"), dict) else {}
    return _info(
        bin_,
        marca=MARCAS_API.get(campo(datos.get("Scheme")).upper()) or marca_local(bin_),
        tipo=TIPOS.get(campo(datos.get("Type")).upper(), campo(datos.get("Type")).title()),
        banco=campo(datos.get("Issuer")),
        pais=campo(pais.get("Name")),
        pais_codigo=campo(pais.get("A2")),
        nivel=campo(datos.get("CardTier")).title(),
        fuente="handyapi",
    )


class _CupoAgotado(Exception):
    pass


def identificar(bines, tiempo_maximo=TIEMPO_MAXIMO_CONSULTAS):
    """{bin: datos} para cada BIN. Usa lo guardado y consulta la API solo lo nuevo.

    Si la API falla, se agota el cupo o se acaba el tiempo, los BIN restantes quedan
    solo con la marca (no se guardan, así se reintentan en la próxima conciliación).
    Cualquier otro error (p. ej. falta correr migrate) tampoco detiene la conciliación:
    se identifica solo la marca.
    """
    try:
        return _identificar(bines, tiempo_maximo)
    except Exception:  # noqa: BLE001 - la identificación es accesoria, nunca debe bloquear
        logger.exception("No se pudo identificar los BIN (¿falta python manage.py migrate?); se muestra solo la marca")
        return identificar_local(bines)


def _identificar(bines, tiempo_maximo):
    from .models import BinTarjeta  # aquí para que logica_clp siga sin depender de Django

    bines = {b for b in bines if b}
    guardados = {b.bin: b.como_dict() for b in BinTarjeta.objects.filter(bin__in=bines)}
    faltantes = sorted(bines - guardados.keys())
    resultado = dict(guardados)

    limite = time.monotonic() + tiempo_maximo
    with httpx.Client(timeout=5) as cliente:
        for bin_ in faltantes:
            if time.monotonic() >= limite:
                resultado[bin_] = _info(bin_)
                continue
            try:
                datos = _consultar_handyapi(cliente, bin_)
            except _CupoAgotado:
                logger.warning("HandyAPI: cupo de consultas agotado; los BIN restantes quedan solo con la marca")
                limite = 0
                datos = None
            except (httpx.HTTPError, ValueError):
                logger.warning("No se pudo consultar el BIN %s en HandyAPI", bin_, exc_info=True)
                limite = 0  # si la API no responde, no se insiste con los demás
                datos = None
            if datos is None:
                resultado[bin_] = _info(bin_)
                continue
            BinTarjeta.objects.update_or_create(bin=bin_, defaults={k: v for k, v in datos.items() if k != "bin"})
            resultado[bin_] = datos
    return resultado


def identificar_local(bines):
    """Solo la marca, sin base de datos ni internet."""
    return {b: _info(b) for b in bines if b}


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
