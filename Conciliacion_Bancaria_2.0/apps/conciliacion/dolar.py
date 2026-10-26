"""Valor del dólar observado desde mindicador.cl, con caché de una hora."""
import logging
from datetime import datetime

import httpx
from django.core.cache import cache

logger = logging.getLogger(__name__)

URL_DOLAR = "https://mindicador.cl/api/dolar"
CACHE_DOLAR = "serie_dolar"


def obtener_serie_dolar():
    """Serie del dólar [{"fecha": "dd-mm-YYYY", "valor": float}, ...], la más reciente primero.

    Se guarda 1 hora en caché para no llamar a la API en cada request.
    Si la API falla, devuelve [] y la página sigue funcionando.
    """
    serie = cache.get(CACHE_DOLAR)
    if serie is not None:
        return serie

    try:
        respuesta = httpx.get(URL_DOLAR, timeout=10)
        respuesta.raise_for_status()
        serie = [
            {
                "fecha": datetime.fromisoformat(item["fecha"].replace("Z", "+00:00")).strftime("%d-%m-%Y"),
                "valor": item["valor"],
            }
            for item in respuesta.json()["serie"]
        ]
    except (httpx.HTTPError, KeyError, ValueError):
        logger.warning("No se pudo obtener el valor del dólar desde mindicador.cl", exc_info=True)
        return []

    cache.set(CACHE_DOLAR, serie, 60 * 60)
    return serie
