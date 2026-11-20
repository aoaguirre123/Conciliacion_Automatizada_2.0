"""Valor del dólar observado desde mindicador.cl, findic.cl o la API de la CMF, con respaldo automático y caché de una hora.

Las fuentes se consultan a la vez. Si la elegida no responde en 3 segundos, se usa otra.
La API de la CMF solo se usa si está configurada la variable de entorno CMF_API_KEY.
La consulta sigue en segundo plano hasta 30 segundos: si responde tarde (por ejemplo, a través del proxy
de PythonAnywhere), el valor queda en caché y aparece en la siguiente carga de la página.
Además se guarda el último valor obtenido (30 días): si ninguna fuente responde, se muestra ese valor con su fecha.
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime

import httpx
from django.core.cache import cache

logger = logging.getLogger(__name__)

# clave: (nombre visible, URL).
# mindicador y findic entregan {"serie": [{"fecha", "valor"}, ...]}.
# La CMF entrega {"Dolares": [{"Valor": "1.008,79", "Fecha": "2026-11-20"}]} y pide una API key gratuita.
FUENTES = {
    "mindicador": ("mindicador.cl", "https://mindicador.cl/api/dolar"),
    "findic": ("findic.cl", "https://findic.cl/api/dolar"),
    "cmf": ("CMF", "https://api.cmfchile.cl/api-sbifv3/recursos_api/dolar"),
}
SESION_FUENTE = "fuente_dolar"
ESPERA_MAXIMA = 3  # segundos que la página espera a las fuentes antes de mostrarse sin el dólar
TIEMPO_CONSULTA = 30  # segundos que cada consulta puede seguir en segundo plano antes de darse por caída
DURACION_ULTIMO = 30 * 24 * 60 * 60  # se conserva el último valor obtenido para cuando las fuentes no respondan

def clave_cmf():
    return os.environ.get("CMF_API_KEY", "").strip()


def fuentes_activas():
    """Fuentes que se pueden consultar: la CMF solo si hay API key."""
    return [clave for clave in FUENTES if clave != "cmf" or clave_cmf()]


def _leer_serie(fuente, datos):
    """Convierte la respuesta de cada API a [{"fecha": "dd-mm-YYYY", "valor": float}, ...]."""
    if fuente == "cmf":
        return [
            {
                "fecha": datetime.strptime(item["Fecha"], "%Y-%m-%d").strftime("%d-%m-%Y"),
                "valor": float(item["Valor"].replace(".", "").replace(",", ".")),
            }
            for item in sorted(datos["Dolares"], key=lambda item: item["Fecha"], reverse=True)
        ]
    return [
        {
            "fecha": datetime.fromisoformat(item["fecha"].replace("Z", "+00:00")).strftime("%d-%m-%Y"),
            "valor": item["valor"],
        }
        for item in datos["serie"]
    ]


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
    parametros = {"apikey": clave_cmf(), "formato": "json"} if fuente == "cmf" else None
    try:
        respuesta = httpx.get(url, params=parametros, timeout=TIEMPO_CONSULTA)
        respuesta.raise_for_status()
        serie = _leer_serie(fuente, respuesta.json())
    except (httpx.HTTPError, KeyError, ValueError, AttributeError, TypeError) as error:
        if fuente == "cmf":
            # Sin el detalle: el mensaje de error incluye la URL con la API key.
            logger.warning("No se pudo obtener el valor del dólar desde %s (%s)", nombre, type(error).__name__)
        else:
            logger.warning("No se pudo obtener el valor del dólar desde %s", nombre, exc_info=True)
        serie = []

    cache.set(cache_clave, serie, 60 * 60 if serie else 60)
    if serie:
        cache.set(f"dolar_ultimo_{fuente}", serie[:1], DURACION_ULTIMO)
    return serie


def obtener_dolar(preferida="mindicador"):
    """Último dólar: {"fecha", "valor", "fuente", "nombre"}, o None si ninguna fuente responde.

    Consulta todas las fuentes a la vez y espera como máximo ESPERA_MAXIMA segundos en total.
    Usa la preferida si respondió a tiempo y, si no, la siguiente que haya respondido.
    Si ninguna respondió, devuelve el último valor guardado, marcado con "guardado": True.
    """
    activas = fuentes_activas()
    if preferida not in activas:
        preferida = activas[0]
    orden = [preferida] + [clave for clave in activas if clave != preferida]
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
    for clave in orden:
        guardado = cache.get(f"dolar_ultimo_{clave}")
        if guardado:
            return {**guardado[0], "fuente": clave, "nombre": FUENTES[clave][0], "guardado": True}
    return None


def fuente_elegida(request):
    """Fuente que eligió el usuario. La elección llega por ?fuente=<clave> y se recuerda en la sesión."""
    activas = fuentes_activas()
    if request.GET.get("fuente") in activas:
        request.session[SESION_FUENTE] = request.GET["fuente"]
    elegida = request.session.get(SESION_FUENTE, "mindicador")
    return elegida if elegida in activas else activas[0]


def fuente_otra(preferida):
    """La fuente a la que lleva el botón de cambiar: la siguiente de las activas, en orden circular."""
    activas = fuentes_activas()
    posicion = activas.index(preferida) if preferida in activas else -1
    otra = activas[(posicion + 1) % len(activas)]
    return {"clave": otra, "nombre": FUENTES[otra][0]}


def dolar_para(request):
    """Contexto del dólar para las plantillas, respetando la fuente que eligió el usuario."""
    preferida = fuente_elegida(request)
    dolar = obtener_dolar(preferida)
    if dolar and not dolar.get("guardado") and dolar["fuente"] != preferida:
        dolar["respaldo_de"] = FUENTES[preferida][0]  # la elegida no respondió
    return {"dolar_hoy": dolar, "fuente_otra": fuente_otra(preferida)}
