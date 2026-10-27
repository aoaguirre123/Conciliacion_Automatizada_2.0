"""Valor del dólar observado desde mindicador.cl o findic.cl, con respaldo automático y caché de una hora.

Las dos fuentes se consultan a la vez. Si la elegida no responde en 3 segundos, se usa la otra.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime

import httpx
from django.core.cache import cache

logger = logging.getLogger(__name__)

# clave: (nombre visible, URL). Las dos APIs entregan {"serie": [{"fecha", "valor"}, ...]}.
FUENTES = {
    "mindicador": ("mindicador.cl", "https://mindicador.cl/api/dolar"),
    "findic": ("findic.cl", "https://findic.cl/api/dolar"),
}
SESION_FUENTE = "fuente_dolar"
ESPERA_MAXIMA = 3  # segundos que se espera a la fuente elegida antes de usar la otra

# Hilos para consultar las APIs sin bloquear: una API colgada no frena la respuesta.
_hilos = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dolar")


def obtener_serie_dolar(fuente="mindicador"):
    """Serie del dólar [{"fecha": "dd-mm-YYYY", "valor": float}, ...], la más reciente primero.

    Se guarda 1 hora en caché para no llamar a la API en cada request.
    Si la API falla, devuelve [] y se recuerda la caída por 1 minuto para no volver a esperarla.
    """
    cache_clave = f"serie_dolar_{fuente}"
    serie = cache.get(cache_clave)
    if serie is not None:
        return serie

    nombre, url = FUENTES[fuente]
    try:
        respuesta = httpx.get(url, timeout=ESPERA_MAXIMA)
        respuesta.raise_for_status()
        serie = [
            {
                "fecha": datetime.fromisoformat(item["fecha"].replace("Z", "+00:00")).strftime("%d-%m-%Y"),
                "valor": item["valor"],
            }
            for item in respuesta.json()["serie"]
        ]
    except (httpx.HTTPError, KeyError, ValueError):
        logger.warning("No se pudo obtener el valor del dólar desde %s", nombre, exc_info=True)
        serie = []

    cache.set(cache_clave, serie, 60 * 60 if serie else 60)
    return serie


def obtener_dolar(preferida="mindicador"):
    """Último dólar: {"fecha", "valor", "fuente", "nombre"}, o None si ninguna fuente responde.

    Consulta todas las fuentes a la vez y espera como máximo ESPERA_MAXIMA segundos en total.
    Usa la preferida si respondió a tiempo y, si no, la siguiente que haya respondido.
    """
    orden = [preferida] + [clave for clave in FUENTES if clave != preferida]
    pedidos = {clave: _hilos.submit(obtener_serie_dolar, clave) for clave in orden}
    limite = time.monotonic() + ESPERA_MAXIMA
    for clave in orden:
        try:
            serie = pedidos[clave].result(timeout=max(0, limite - time.monotonic()))
        except TimeoutError:
            # Se marca como caída por 1 minuto para que las próximas cargas no la esperen.
            logger.warning("%s no respondió en %s segundos", FUENTES[clave][0], ESPERA_MAXIMA)
            cache.add(f"serie_dolar_{clave}", [], 60)
            continue
        if serie:
            return {**serie[0], "fuente": clave, "nombre": FUENTES[clave][0]}
    return None


def fuente_elegida(request):
    """Fuente que eligió el usuario. La elección llega por ?fuente=<clave> y se recuerda en la sesión."""
    if request.GET.get("fuente") in FUENTES:
        request.session[SESION_FUENTE] = request.GET["fuente"]
    return request.session.get(SESION_FUENTE, "mindicador")


def fuente_otra(preferida):
    """La fuente a la que lleva el botón de cambiar."""
    otra = next(clave for clave in FUENTES if clave != preferida)
    return {"clave": otra, "nombre": FUENTES[otra][0]}


def dolar_para(request):
    """Contexto del dólar para las plantillas, respetando la fuente que eligió el usuario."""
    preferida = fuente_elegida(request)
    dolar = obtener_dolar(preferida)
    if dolar and dolar["fuente"] != preferida:
        dolar["respaldo_de"] = FUENTES[preferida][0]  # la elegida no respondió
    return {"dolar_hoy": dolar, "fuente_otra": fuente_otra(preferida)}
