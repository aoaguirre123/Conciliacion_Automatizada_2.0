"""Excepciones de una conciliación (CU-04): qué tipo de problema es cada caso y qué hacer.

Al guardar una conciliación, cada venta por revisar se convierte en una excepción con:
- una categoría automática (error de digitación, diferencia de monto, venta sin registro,
  anulación, cuota diferida, etc.),
- una acción sugerida armada con los datos del caso (código, montos y fechas),
- un estado que el analista va cambiando (pendiente, en revisión, resuelta), un comentario y,
  si tiene antecedentes, otra categoría (reclasificación manual).

Las funciones de este módulo trabajan con diccionarios simples para servir igual a las
conciliaciones nuevas y a las guardadas antes de existir las excepciones (migración 0006).
"""
from datetime import date, datetime

CATEGORIAS = [
    ("digitacion", "Error de digitación del código"),
    ("codigo_distinto", "Código no coincide"),
    ("fecha_distinta", "Registrada en otra fecha"),
    ("tarjeta_distinta", "Registrada en otra tarjeta"),
    ("monto_distinto", "Diferencia de monto"),
    ("sin_registro", "Venta sin registro contable"),
    ("anulacion", "Anulación o nota de crédito"),
    ("cuota_diferida", "Cuota diferida no encontrada"),
    ("otra", "Otra causa"),
]
NOMBRE_CATEGORIA = dict(CATEGORIAS)

ESTADOS = [
    ("pendiente", "Pendiente"),
    ("en_revision", "En revisión"),
    ("resuelta", "Resuelta"),
]
NOMBRE_ESTADO = dict(ESTADOS)


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------
def _monto(valor, moneda):
    if valor is None or valor == "":
        return "—"
    valor = float(valor)
    if moneda == "USD":
        texto = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{'-' if valor < 0 else ''}US$ {texto}"
    return f"{'-' if valor < 0 else ''}$ " + f"{round(abs(valor)):,.0f}".replace(",", ".")


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _fecha(valor):
    """date | datetime | '04-09-2026' | '2026-09-04' -> date o None."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()[:10]
    for formato in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _texto_fecha(valor):
    f = _fecha(valor)
    return f.strftime("%d-%m-%Y") if f else ""


# ---------------------------------------------------------------------------
# Clasificación
# ---------------------------------------------------------------------------
def categoria_de(caso):
    """Categoría automática de un caso normalizado (ver _caso_clp / _caso_usd)."""
    nota = (caso.get("nota") or "").lower()
    monto = _numero(caso.get("monto")) or 0
    if monto < 0 or "anul" in (caso.get("tipo") or "").lower():
        return "anulacion"
    if "código digitado distinto" in nota:
        return "digitacion"
    if "cruzado por monto y fecha" in nota:
        return "codigo_distinto"
    if "otra fecha" in nota:
        return "fecha_distinta"
    if "otra tarjeta" in nota:
        return "tarjeta_distinta"
    if caso.get("estado") == "diferencia":
        return "monto_distinto"
    return "sin_registro"


def sugerencia_de(categoria, caso):
    """Acción sugerida: una instrucción corta (el código y los montos ya se ven en la excepción)."""
    moneda = caso.get("moneda", "CLP")
    registro = "BORDERO" if moneda == "CLP" else "ERP"
    codigo = caso.get("codigo") or ""
    documento = caso.get("documento") or ""
    if categoria == "digitacion":
        if documento and codigo:
            return f"Corregir el código en el {registro}: dice {documento}, debe ser {codigo}."
        return f"Corregir el código en el {registro}" + (f" (debe ser {codigo})." if codigo else ".")
    if categoria == "codigo_distinto":
        return f"Confirmar con el voucher y corregir el código en el {registro}."
    if categoria == "fecha_distinta":
        fecha = caso.get("fecha") or ""
        return f"Corregir la fecha en el {registro}" + (f" (debe ser {fecha})." if fecha else ".")
    if categoria == "tarjeta_distinta":
        return "Corregir la tarjeta del pago en el ERP."
    if categoria == "monto_distinto":
        if "sin monto en la cartola" in (caso.get("nota") or "").lower():
            return f"Revisar la cartola de {caso.get('medio') or 'la tarjeta'}: el pago no aparece."
        diferencia = abs(_numero(caso.get("diferencia")) or 0)
        if diferencia and diferencia <= (1 if moneda == "USD" else 100):
            return "Probable redondeo: evaluar subir la tolerancia."
        return f"Corregir el monto en el {registro} o registrar el ajuste."
    if categoria == "anulacion":
        return f"Verificar que la venta y su anulación estén en el {registro}."
    if categoria == "cuota_diferida":
        mes = (caso.get("mes") or "").lower()
        if caso.get("en_periodo"):
            return f"Consultar con Transbank: la cuota de {mes or 'ese mes'} no llegó."
        return f"Conciliar de nuevo incluyendo {mes or 'el mes de la cuota'}."
    if categoria == "otra":
        return "Ver comentario."
    return f"Registrar la venta en el {registro}."


# ---------------------------------------------------------------------------
# Casos desde los resultados de cada motor
# ---------------------------------------------------------------------------
def _caso_clp(fila):
    """Fila de «Ventas por revisar» (logica_clp._fila_venta, guardada o recién calculada)."""
    return {
        "moneda": "CLP",
        "estado": fila.get("estado"),
        "nota": fila.get("nota") or "",
        "tipo": fila.get("tipo") or "",
        "fecha": _texto_fecha(fila.get("fecha")),
        "medio": fila.get("medio") or "",
        "marca": fila.get("marca") or "",
        "codigo": fila.get("autorizacion") or "",
        "documento": fila.get("documento_bordero") or "",
        "monto": _numero(fila.get("monto")),
        "monto_registro": _numero(fila.get("monto_bordero")),
        "diferencia": _numero(fila.get("diferencia")),
    }


def _completar(caso):
    categoria = categoria_de(caso)
    return {
        "categoria": categoria,
        "fecha": _fecha(caso.get("fecha")),
        "medio": caso.get("medio") or "",
        "codigo": str(caso.get("codigo") or "")[:40],
        "monto": caso.get("monto"),
        "monto_registro": caso.get("monto_registro"),
        "diferencia": caso.get("diferencia"),
        "detalle": caso.get("nota") or "",
        "sugerencia": sugerencia_de(categoria, caso),
    }


def desde_clp(observaciones, cuotas=None):
    """Excepciones de una conciliación en pesos.

    observaciones: filas de «Ventas por revisar» (diferencias, sin registro y conciliadas con
    observación; las de diferencia aceptada no son excepciones). cuotas: resultado["cuotas"].
    """
    from .logica_clp import diferencia_aceptada  # evita la importación circular

    casos = [_completar(_caso_clp(f)) for f in observaciones or [] if not diferencia_aceptada(f)]
    for venta in (cuotas or {}).get("ventas", []):
        for faltante in venta.get("faltantes", []):
            caso = {
                "moneda": "CLP", "estado": "cuota", "fecha": venta.get("fecha"), "medio": venta.get("medio"),
                "codigo": venta.get("autorizacion"), "monto": _numero(venta.get("monto_cuota")),
                "cuota": faltante.get("cuota"), "mes": faltante.get("mes"), "en_periodo": faltante.get("en_periodo"),
            }
            casos.append({
                "categoria": "cuota_diferida",
                "fecha": _fecha(caso["fecha"]),
                "medio": caso["medio"] or "",
                "codigo": str(caso["codigo"] or "")[:40],
                "monto": caso["monto"],
                "monto_registro": None,
                "diferencia": None,
                "detalle": f"Cuota {faltante.get('cuota')} no encontrada" + (f" (esperada en {faltante['mes']})" if faltante.get("mes") else ""),
                "sugerencia": sugerencia_de("cuota_diferida", caso),
            })
    return casos


def es_excepcion_usd(r):
    """¿La venta en dólares (fila de logica.informacion_proceso) hay que revisarla?"""
    estado = r.get("estado") or ""
    nota = r.get("nota") or ""
    observacion = any(t in nota for t in ("Código digitado distinto", "Cruzado por monto y fecha", "otra fecha"))
    return estado in ("diferencia", "sin_registro") or (estado in ("conciliada", "redondeo") and observacion)


def caso_usd(r, nombre_marca, numero, leer_fecha):
    fecha = leer_fecha(r.get("fecha_venta"))
    return {
        "moneda": "USD",
        "estado": r.get("estado") or "",
        "nota": r.get("nota") or "",
        "fecha": fecha.strftime("%d-%m-%Y") if fecha else "",
        "medio": nombre_marca(r.get("tipo_tarjeta")) or "",
        "codigo": str(r.get("codigo_autorizacion") or ""),
        "documento": str(r.get("documento") or ""),
        "monto": numero(r.get("monto_original")),
        "monto_registro": numero(r.get("monto_cartola")) if r.get("monto_cartola") not in ("", None) else None,
        "diferencia": numero(r.get("diferencia")) if r.get("diferencia") not in ("", None) else None,
    }


def desde_usd(filas_proceso, nombre_marca, numero, leer_fecha):
    """Excepciones de una conciliación en dólares (filas de logica.informacion_proceso)."""
    return [_completar(caso_usd(r, nombre_marca, numero, leer_fecha)) for r in filas_proceso if es_excepcion_usd(r)]


def anotar_filas_clp(observaciones):
    """Agrega a cada fila de «Ventas por revisar» su tipo de excepción y acción sugerida (para el Excel)."""
    for fila in observaciones:
        caso = _caso_clp(fila)
        categoria = categoria_de(caso)
        fila["excepcion"] = NOMBRE_CATEGORIA[categoria]
        fila["accion_sugerida"] = sugerencia_de(categoria, caso)
    return observaciones


# ---------------------------------------------------------------------------
# Guardado (lo usan Excepcion.crear_para y la migración 0006)
# ---------------------------------------------------------------------------
def _decimal(valor):
    from decimal import Decimal
    return None if valor is None else Decimal(str(round(float(valor), 2)))


def campos_excepcion(conciliacion, orden, caso):
    return {
        "conciliacion": conciliacion, "orden": orden,
        "categoria_auto": caso["categoria"], "categoria": caso["categoria"],
        "fecha": caso.get("fecha"), "medio": (caso.get("medio") or "")[:40], "codigo": (caso.get("codigo") or "")[:40],
        "monto": _decimal(caso.get("monto")), "monto_registro": _decimal(caso.get("monto_registro")),
        "diferencia": _decimal(caso.get("diferencia")), "detalle": (caso.get("detalle") or "")[:300],
        "sugerencia": caso.get("sugerencia") or "",
    }


def _clave(e):
    return (e.categoria_auto, e.codigo, e.fecha, e.monto, e.detalle)


def heredar_gestion(Excepcion, conciliacion):
    """La misma venta ya estaba como excepción en una conciliación anterior de la misma moneda:
    la nueva hereda su estado, tipo y comentario, y la anterior deja de estar vigente."""
    nuevas = list(Excepcion.objects.filter(conciliacion=conciliacion))
    if not nuevas:
        return
    claves = {_clave(e): e for e in nuevas}
    anteriores = (Excepcion.objects.filter(vigente=True, conciliacion__moneda=conciliacion.moneda,
                                           codigo__in={e.codigo for e in nuevas})
                  .exclude(conciliacion=conciliacion).order_by("conciliacion_id", "orden"))
    heredadas, reemplazadas = {}, []
    for vieja in anteriores:
        nueva = claves.get(_clave(vieja))
        if nueva is None:
            continue
        heredadas[nueva.pk] = vieja  # la más reciente gana (orden por conciliación)
        vieja.vigente = False
        vieja.reemplazada_por = conciliacion
        reemplazadas.append(vieja)
    for nueva in nuevas:
        vieja = heredadas.get(nueva.pk)
        if vieja is None:
            continue
        nueva.estado, nueva.comentario = vieja.estado, vieja.comentario
        nueva.actualizada, nueva.actualizada_por_id = vieja.actualizada, vieja.actualizada_por_id
        if vieja.categoria != vieja.categoria_auto:
            nueva.categoria, nueva.sugerencia = vieja.categoria, vieja.sugerencia
    if reemplazadas:
        Excepcion.objects.bulk_update(reemplazadas, ["vigente", "reemplazada_por"])
        Excepcion.objects.bulk_update(
            [n for n in nuevas if n.pk in heredadas],
            ["estado", "comentario", "actualizada", "actualizada_por", "categoria", "sugerencia"],
        )
