"""Resumen gráfico de cada conciliación: dónde está lo que hay que revisar.

Se calcula en dos pasos:

1. `datos_clp` / `datos_usd` (al conciliar): totales por estado, por medio de pago o marca,
   por día de venta y las ventas con más monto por revisar. Se guardan en
   resultado["graficos"], así una conciliación del historial se ve igual que el día que se hizo.
2. `preparar` (al mostrar): convierte esos totales en anchos, alturas y frases. Las
   conciliaciones anteriores a esta versión no tienen resultado["graficos"]; para ellas se
   arma lo que se puede desde los datos que sí guardaron.
"""
from datetime import date, datetime

MAYORES = 8

# Estados en el orden de la barra. Los grises (nada que hacer) van al final para que no
# queden al lado del ámbar. tono -> color en app.css (.grafico-tono--*).
ESTADOS_CLP = [
    ("conciliado", "Conciliadas", "ok"),
    ("con_nota", "Conciliadas con observación", "aviso"),
    ("diferencia", "Diferencia de monto", "error"),
    ("sin_registro", "Sin registro en el BORDERO", "error-rayado"),
    ("cuota", "Otras cuotas de la misma venta", "neutro"),
    ("fuera_periodo", "Fuera del período del BORDERO", "neutro-rayado"),
]
ESTADOS_USD = [
    ("conciliada", "Conciliadas", "ok"),
    ("redondeo", "Diferencia de redondeo", "aviso"),
    ("diferencia", "Diferencia de monto", "error"),
    ("sin_registro", "Sin registro en el ERP", "error-rayado"),
    ("fuera_periodo", "Fuera del período del ERP", "neutro-rayado"),
]
POR_REVISAR = {"diferencia", "sin_registro"}
# No van en el gráfico por día: son ventas de otros meses (cuotas) o de fechas que el registro no cubre.
FUERA_DEL_DIA_A_DIA = {"cuota", "fuera_periodo"}


# ---------------------------------------------------------------------------
# 1. Totales que se guardan con la conciliación
# ---------------------------------------------------------------------------
def _texto_fecha(valor):
    if isinstance(valor, datetime):
        valor = valor.date()
    return valor.isoformat() if isinstance(valor, date) else ""


def _acumular(grupos, clave, monto, por_revisar):
    g = grupos.setdefault(clave, {"ventas": 0, "monto": 0.0, "revisar_n": 0, "revisar_monto": 0.0})
    g["ventas"] += 1
    g["monto"] += monto
    if por_revisar:
        g["revisar_n"] += 1
        g["revisar_monto"] += por_revisar


def _armar(ventas, orden_medios=()):
    """ventas: dicts con estado, medio, fecha (date o None), monto, por_revisar, codigo, fecha_texto."""
    estados, medios, dias = {}, {}, {}
    for v in ventas:
        e = estados.setdefault(v["estado"], [0, 0.0])
        e[0] += 1
        e[1] += v["monto"]
        _acumular(medios, v["medio"] or "Sin identificar", v["monto"], v["por_revisar"])
        if v["fecha"] and v["estado"] not in FUERA_DEL_DIA_A_DIA:
            _acumular(dias, _texto_fecha(v["fecha"]), v["monto"], v["por_revisar"])
    orden = list(orden_medios)
    lista_medios = sorted(
        ({"nombre": nombre, **datos} for nombre, datos in medios.items()),
        key=lambda m: (orden.index(m["nombre"]) if m["nombre"] in orden else len(orden), m["nombre"]),
    )
    mayores = sorted((v for v in ventas if v["por_revisar"]), key=lambda v: -v["por_revisar"])[:MAYORES]
    return {
        "version": 1,
        "estados": {clave: [n, round(monto, 2)] for clave, (n, monto) in estados.items()},
        "medios": lista_medios,
        "dias": [{"fecha": f, **datos} for f, datos in sorted(dias.items())],
        "mayores": [
            {
                "fecha": v["fecha_texto"],
                "medio": v["medio"],
                "codigo": v["codigo"],
                "monto": round(v["monto"], 2),
                "por_revisar": round(v["por_revisar"], 2),
                "estado": v["estado"],
            }
            for v in mayores
        ],
    }


def datos_clp(ventas, pendientes_bordero, por_revisar, con_observacion, orden_medios=()):
    """Ventas de Transbank ya cruzadas (logica_clp) y pagos del BORDERO sin abono.

    `con_observacion(venta)`: conciliada con un código escrito distinto o solo por monto y fecha.
    Las conciliadas con diferencia de redondeo o dentro de la tolerancia cuentan como conciliadas.
    """
    filas = []
    for v in ventas:
        estado = "con_nota" if con_observacion(v) else v["estado"]
        filas.append({
            "estado": estado,
            "medio": v["medio"],
            "fecha": v["fecha"],
            "fecha_texto": v["fecha"].strftime("%d-%m-%Y") if v["fecha"] else "",
            "monto": v["monto"] or 0,
            "por_revisar": por_revisar(v),
            "codigo": v["autorizacion"],
        })
    datos = _armar(filas, orden_medios)
    datos["bordero_sin_abono"] = [len(pendientes_bordero), round(sum(p.get("monto") or 0 for p in pendientes_bordero), 2)]
    return datos


def datos_usd(filas_proceso, nombre_marca, numero, leer_fecha):
    """Filas de logica.informacion_proceso (una por venta de Transbank)."""
    filas = []
    for r in filas_proceso:
        estado = r.get("estado") or ("sin_registro" if r.get("extra") == "NO" else "conciliada")
        monto = abs(numero(r.get("monto_original")))
        if estado == "diferencia":
            pendiente = abs(numero(r.get("diferencia")))
        elif estado == "sin_registro":
            pendiente = monto
        else:
            pendiente = 0.0
        fecha = leer_fecha(r.get("fecha_venta"))
        filas.append({
            "estado": estado,
            "medio": nombre_marca(r.get("tipo_tarjeta")) or "Sin identificar",
            "fecha": fecha,
            "fecha_texto": fecha.strftime("%d-%m-%Y") if fecha else "",
            "monto": monto,
            "por_revisar": pendiente,
            "codigo": str(r.get("codigo_autorizacion") or ""),
        })
    return _armar(filas, ("Visa", "Mastercard", "American Express", "Diners"))


# ---------------------------------------------------------------------------
# 2. Lo que se muestra
# ---------------------------------------------------------------------------
def _pesos(valor, moneda):
    if moneda == "USD":
        texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"US$ {texto}"
    return "$ " + f"{round(valor):,.0f}".replace(",", ".")


def _pct(parte, total):
    return round(100 * parte / total, 1) if total else 0


def _pct_texto(valor):
    if 0 < valor < 1:
        return "menos de 1%"
    return f"{round(valor):.0f}%"


def _corta(fecha_iso):
    """2026-09-04 -> 04-09"""
    try:
        d = date.fromisoformat(fecha_iso)
    except (TypeError, ValueError):
        return fecha_iso
    return f"{d:%d-%m}"


def _larga(fecha_iso):
    try:
        return f"{date.fromisoformat(fecha_iso):%d-%m-%Y}"
    except (TypeError, ValueError):
        return fecha_iso


def _desde_resultado_antiguo(resultado, moneda):
    """Conciliaciones guardadas antes de los gráficos: se arma lo posible."""
    resumen = resultado.get("resumen") or {}
    if moneda == "CLP":
        estados = {
            "conciliado": [max((resumen.get("conciliadas") or 0) - (resumen.get("con_nota") or 0), 0), None],
            "con_nota": [resumen.get("con_nota") or 0, None],
            "diferencia": [resumen.get("diferencias") or 0, None],
            "sin_registro": [resumen.get("sin_registro") or 0, None],
            "cuota": [resumen.get("otras_cuotas") or 0, None],
            "fuera_periodo": [resumen.get("fuera_periodo") or 0, None],
        }
        filas = [
            {
                "estado": o["estado"], "medio": o.get("medio"), "fecha_texto": o.get("fecha", ""),
                "fecha": _fecha_ddmmaaaa(o.get("fecha")), "monto": o.get("monto") or 0,
                "por_revisar": abs(o.get("diferencia") or 0) if o["estado"] == "diferencia"
                else (o.get("monto") or 0) if o["estado"] == "sin_registro" else 0,
                "codigo": o.get("autorizacion", ""),
            }
            for o in resultado.get("observaciones") or []
        ]
        parcial = _armar(filas)
        medios = [
            {"nombre": m["medio"], "ventas": m["ventas"], "monto": m["total_ventas"],
             "revisar_n": next((x["revisar_n"] for x in parcial["medios"] if x["nombre"] == m["medio"]), 0),
             "revisar_monto": m["por_revisar"]}
            for m in resultado.get("medios") or []
        ]
        return {"version": 0, "estados": estados, "medios": medios, "dias": parcial["dias"],
                "mayores": parcial["mayores"], "dias_parciales": True}
    estados = {
        "conciliada": [resumen.get("conciliadas") or 0, None],
        "redondeo": [resumen.get("redondeo") or 0, None],
        "diferencia": [resumen.get("diferencias") or 0, None],
        "sin_registro": [max((resumen.get("no_ubicadas") or 0) - (resumen.get("fuera_periodo") or 0), 0), None],
        "fuera_periodo": [resumen.get("fuera_periodo") or 0, None],
    }
    return {"version": 0, "estados": estados, "medios": [], "dias": [], "mayores": []}


def _fecha_ddmmaaaa(texto):
    try:
        return datetime.strptime(texto, "%d-%m-%Y").date()
    except (TypeError, ValueError):
        return None


def preparar(resultado, moneda):
    """Datos listos para la plantilla conciliacion/_graficos.html, o None si no hay ventas."""
    datos = resultado.get("graficos") or _desde_resultado_antiguo(resultado, moneda)
    definiciones = ESTADOS_CLP if moneda == "CLP" else ESTADOS_USD
    total_ventas = sum(n for n, _ in datos["estados"].values())
    if not total_ventas:
        return None
    fmt = lambda valor: _pesos(valor, moneda)  # noqa: E731

    estados = []
    for clave, nombre, tono in definiciones:
        n, monto = datos["estados"].get(clave, [0, None])
        if not n:
            continue
        pct = _pct(n, total_ventas)
        estados.append({
            "clave": clave, "nombre": nombre, "tono": tono, "cantidad": n, "pct": pct,
            "pct_texto": _pct_texto(pct), "monto_texto": fmt(monto) if monto is not None else "",
            "por_revisar": clave in POR_REVISAR,
        })

    medios = [m for m in datos["medios"] if m["ventas"]]
    total_revisar = sum(m["revisar_monto"] for m in medios)
    max_medio = max((m["revisar_monto"] for m in medios), default=0)
    filas_medio = []
    for m in sorted(medios, key=lambda m: -m["revisar_monto"]):
        filas_medio.append({
            "nombre": m["nombre"],
            "ventas": m["ventas"],
            "revisar_n": m["revisar_n"],
            "revisar_texto": fmt(m["revisar_monto"]),
            "ancho": _pct(m["revisar_monto"], max_medio),
            "parte": _pct_texto(_pct(m["revisar_monto"], total_revisar)) if total_revisar else "",
            "del_medio": _pct_texto(_pct(m["revisar_monto"], m["monto"])) if m["monto"] else "",
            "limpio": not m["revisar_monto"],
        })

    dias = datos["dias"]
    max_dia = max((d["revisar_monto"] for d in dias), default=0)
    pico = max(dias, key=lambda d: d["revisar_monto"]) if max_dia else None
    columnas = [{
        "fecha": _corta(d["fecha"]),
        "fecha_larga": _larga(d["fecha"]),
        "alto": _pct(d["revisar_monto"], max_dia),
        "limpio": not d["revisar_monto"],
        "pico": d is pico,
        "revisar_texto": fmt(d["revisar_monto"]),
        "revisar_n": d["revisar_n"],
        "ventas": d["ventas"],
        "monto_texto": fmt(d["monto"]),
    } for d in dias]

    nombres_estado = {clave: nombre for clave, nombre, _ in definiciones}
    mayores = [{**v, "estado_texto": nombres_estado.get(v["estado"], v["estado"]),
                "monto_texto": fmt(v["monto"]), "revisar_texto": fmt(v["por_revisar"])}
               for v in datos["mayores"]]

    return {
        "moneda": moneda,
        "total_ventas": total_ventas,
        "estados": estados,
        "medios": filas_medio if total_revisar else [],
        "nombre_medio": "medio de pago" if moneda == "CLP" else "marca",
        "dias": columnas if len(columnas) > 1 and max_dia else [],
        "dias_parciales": datos.get("dias_parciales", False),
        "pico": columnas[dias.index(pico)] if pico and len(columnas) > 1 else None,
        "mayores": mayores,
        "hallazgos": _hallazgos(datos, estados, medios, total_revisar, pico, mayores, total_ventas, moneda, fmt),
        "sin_detalle": datos.get("version") == 0,
        "bordero_sin_abono": datos.get("bordero_sin_abono"),
    }


def _hallazgos(datos, estados, medios, total_revisar, pico, mayores, total_ventas, moneda, fmt):
    """Hasta tres frases cortas que dicen por dónde empezar."""
    frases = []
    registro = "BORDERO" if moneda == "CLP" else "ERP"
    minuscula = lambda texto: texto[:1].lower() + texto[1:]  # noqa: E731
    fuera = next((e for e in estados if e["clave"] == "fuera_periodo"), None)
    aviso_fuera = None
    if fuera and fuera["pct"] >= 10:
        aviso_fuera = (
            f"{fuera['cantidad']} ventas ({fuera['pct_texto']}) son de fechas que el {registro} cargado no cubre: "
            f"para cruzarlas, concilia de nuevo con un {registro} que incluya esas fechas."
        )
    if not total_revisar and not any(e["por_revisar"] for e in estados):
        frases.append(f"No hay montos por revisar: las ventas del período están en el {registro}.")
        if aviso_fuera:
            frases.append(aviso_fuera)
        return frases

    por_clave = {e["clave"]: e for e in estados}
    diferencia, sin_registro = por_clave.get("diferencia"), por_clave.get("sin_registro")
    if diferencia and sin_registro:
        mayor, menor = (sin_registro, diferencia) if sin_registro["cantidad"] >= diferencia["cantidad"] else (diferencia, sin_registro)
        frases.append(
            f"La mayoría de los casos son «{minuscula(mayor['nombre'])}» ({mayor['cantidad']}); "
            f"además hay {menor['cantidad']} con «{minuscula(menor['nombre'])}»."
        )
    elif sin_registro:
        frases.append(f"Todos los casos por revisar son ventas sin registro en el {registro} ({sin_registro['cantidad']}).")
    elif diferencia:
        frases.append(f"Todos los casos por revisar son diferencias de monto ({diferencia['cantidad']}).")

    con_revision = [m for m in medios if m["revisar_monto"]]
    if total_revisar and len(medios) > 1 and con_revision:
        top = max(con_revision, key=lambda m: m["revisar_monto"])
        parte = _pct(top["revisar_monto"], total_revisar)
        nombre = "medio" if moneda == "CLP" else "marca"
        if len(con_revision) == 1:
            frases.append(f"Todo el monto por revisar es de {top['nombre']}; {'los otros medios' if moneda == 'CLP' else 'las otras marcas'} cuadran.")
        elif parte >= 50:
            frases.append(f"{top['nombre']} concentra el {_pct_texto(parte)} del monto por revisar ({fmt(top['revisar_monto'])}).")
        else:
            frases.append(f"El monto por revisar se reparte entre {len(con_revision)} {nombre}s; el mayor es {top['nombre']} con {fmt(top['revisar_monto'])}.")

    if pico and len(datos["dias"]) > 1:
        frases.append(
            f"El día {_larga(pico['fecha'])} tiene el mayor monto por revisar: {fmt(pico['revisar_monto'])} "
            f"en {pico['revisar_n']} venta{'s' if pico['revisar_n'] != 1 else ''}."
        )
    elif mayores:
        v = mayores[0]
        frases.append(f"El caso más grande es la venta {v['codigo']} del {v['fecha']}: {v['revisar_texto']}.")
    frases = frases[:3]
    if aviso_fuera:
        frases.append(aviso_fuera)
    return frases
