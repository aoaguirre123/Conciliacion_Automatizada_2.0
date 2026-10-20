"""Conciliación en pesos (CLP).

Cruza las liquidaciones de Transbank ("Abonos por día" de Crédito, Débito y Prepago)
contra los pagos con tarjeta registrados en el BORDERO del FrontOffice, y verifica
que el total abonado por Transbank aparezca en la cartola del banco.

Cómo se cruza cada venta de Transbank con el BORDERO (cada pago del BORDERO se usa
una sola vez, y las pasadas van de la coincidencia más segura a la menos segura):

1. Mismo código de autorización y mismo monto (tolerancia de redondeo).
2. Código parecido (ceros a la izquierda, "I" por "1", "O" por "0") y mismo monto.
3. Mismo código de autorización pero distinto monto: diferencia de monto.
4. Sin código, pero mismo monto y misma fecha: se concilia y se marca para revisar.
5. Lo que queda: sin registro en el BORDERO (o fuera del período del BORDERO).

Todo el estado es local a cada llamada: no hay variables globales.
"""
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

TOLERANCIA = 10  # pesos: diferencias de redondeo entre el FrontOffice y Transbank

# Campo del formulario -> (medio de pago, nombre visible)
ARCHIVOS_TBK = {
    "credito": "Crédito",
    "debito": "Débito",
    "prepago": "Prepago",
}

NOMBRES_ARCHIVO = {
    "bordero": "BORDERO",
    "credito": "Transbank Crédito",
    "debito": "Transbank Débito",
    "prepago": "Transbank Prepago",
    "cartola": "Cartola bancaria",
}

# Códigos de pago con tarjeta en pesos del FrontOffice.
CODIGOS_TARJETA_CLP = {
    "V$": "Visa",
    "MC$": "Mastercard",
    "AME$": "Amex",
    "DIN$": "Diners",
    "DI$": "Diners",
    "RCO": "Redcompra",
}
PATRON_TARJETA = re.compile(r"visa|master|amex|diners|dinners|red ?compra|prepago|d[eé]bito|magna", re.I)

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

ESTADOS = {
    "conciliado": "Conciliado",
    "diferencia": "Diferencia de monto",
    "sin_registro": "Sin registro en BORDERO",
    "fuera_periodo": "Fuera del período del BORDERO",
}


class ArchivoInvalido(ValueError):
    """El archivo no tiene el formato esperado."""


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _texto(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def _numero(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("$", "").replace(" ", "")
    if not texto:
        return 0.0
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _fecha(valor):
    """Acepta fechas de Excel, '04/09/2026' y '04 septiembre 2026'."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = _sin_tildes(_texto(valor))
    if not texto:
        return None
    m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", texto)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{1,2})\s+(?:de\s+)?([a-z]+)\s+(?:de\s+)?(\d{4})", texto)
    if m and m.group(2) in MESES:
        return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
    return None


def _codigo(valor):
    """Código de autorización normalizado: mayúsculas y sin ceros a la izquierda."""
    return _texto(valor).upper().lstrip("0")


def _codigo_flexible(valor):
    """Versión tolerante a errores de digitación comunes."""
    return _codigo(_texto(valor).upper().replace("I", "1").replace("O", "0"))


def _leer(archivo):
    archivo.seek(0)
    try:
        return pd.read_excel(archivo, header=None, dtype=object)
    except Exception as exc:  # noqa: BLE001
        raise ArchivoInvalido(f"No se pudo abrir {getattr(archivo, 'name', 'el archivo')}: {exc}") from exc


def _buscar_fila(raw, condicion):
    for i in range(len(raw)):
        if condicion([_texto(v) for v in raw.iloc[i].tolist()]):
            return i
    return None


# ---------------------------------------------------------------------------
# Lectura de archivos
# ---------------------------------------------------------------------------
def leer_bordero(archivo):
    """Pagos con tarjeta en pesos del BORDERO, sin anulaciones compensadas."""
    raw = _leer(archivo)
    fila = _buscar_fila(raw, lambda f: "Cod. Deb." in f and "Documento" in f and "Valor" in f)
    if fila is None:
        raise ArchivoInvalido("El BORDERO no tiene la fila de encabezados (Cod. Deb., Valor, Documento).")
    encabezado = [_texto(v) for v in raw.iloc[fila].tolist()]
    col = {nombre: encabezado.index(nombre) for nombre in ("Cod. Deb.", "Descripción", "Valor", "Documento", "Fecha", "Cuenta", "Usuario") if nombre in encabezado}

    periodo = None
    fila_periodo = _buscar_fila(raw, lambda f: "Periodo de:" in f)
    if fila_periodo is not None:
        fechas = [_fecha(v) for v in raw.iloc[fila_periodo].tolist()]
        fechas = [f for f in fechas if f]
        if len(fechas) >= 2:
            periodo = (min(fechas), max(fechas))

    pagos = []
    for i in range(fila + 1, len(raw)):
        cod = _texto(raw.iat[i, col["Cod. Deb."]]).upper()
        desc = _texto(raw.iat[i, col["Descripción"]]) if "Descripción" in col else ""
        if not cod or cod == "COD. DEB.":
            continue
        es_tarjeta = cod in CODIGOS_TARJETA_CLP or (PATRON_TARJETA.search(desc) and "US$" not in desc.upper() and not cod.endswith("US$"))
        if not es_tarjeta:
            continue
        pagos.append({
            "fila": i + 1,
            "cod": cod,
            "tarjeta": CODIGOS_TARJETA_CLP.get(cod, desc),
            "monto": -_numero(raw.iat[i, col["Valor"]]),  # los pagos vienen en negativo
            "documento": _texto(raw.iat[i, col["Documento"]]),
            "codigo": _codigo(raw.iat[i, col["Documento"]]),
            "codigo_flex": _codigo_flexible(raw.iat[i, col["Documento"]]),
            "fecha": _fecha(raw.iat[i, col["Fecha"]]) if "Fecha" in col else None,
            "cuenta": _texto(raw.iat[i, col["Cuenta"]]) if "Cuenta" in col else "",
            "usuario": _texto(raw.iat[i, col["Usuario"]]) if "Usuario" in col else "",
        })

    if not pagos:
        raise ArchivoInvalido("El BORDERO no tiene pagos con tarjeta en pesos (Visa $, Master Card $, Amex $, Red Compra).")

    # Una anulación (monto negativo) cancela un pago igual con el mismo código.
    anulados = set()
    for a in (p for p in pagos if p["monto"] < 0):
        for p in pagos:
            if p is not a and id(p) not in anulados and p["codigo"] == a["codigo"] and p["monto"] == -a["monto"]:
                anulados.update({id(p), id(a)})
                break
    pagos = [p for p in pagos if id(p) not in anulados and p["monto"] > 0]

    if periodo is None:
        fechas = [p["fecha"] for p in pagos if p["fecha"]]
        periodo = (min(fechas), max(fechas)) if fechas else None
    return pagos, periodo


def leer_transbank(archivo, medio):
    """Reporte 'Abonos por día' de Transbank: resumen del abono y detalle de ventas."""
    raw = _leer(archivo)
    fila = _buscar_fila(raw, lambda f: "Fecha de venta" in f)
    if fila is None:
        raise ArchivoInvalido(f"El archivo de Transbank {medio} no tiene la tabla de detalle ('Fecha de venta').")

    nombres = {}
    for c in raw.columns:
        arriba, abajo = _texto(raw.iat[fila, c]), _texto(raw.iat[fila + 1, c]) if fila + 1 < len(raw) else ""
        nombre = abajo or arriba
        if nombre:
            nombres[c] = nombre

    def columna(*opciones):
        for c, n in nombres.items():
            if any(_sin_tildes(o) in _sin_tildes(n) for o in opciones):
                return c
        return None

    c_fecha = columna("Fecha de venta")
    c_tipo = columna("Tipo de movimiento")
    c_local = columna("Nombre local")
    c_monto = columna("Monto original de venta")
    c_valido = columna("Monto venta válido para abono")
    c_comision = columna("Comisión Transbank (-)")
    c_iva = columna("IVA Comisión Transbank")
    c_abono = columna("Total abono (=)")
    c_cuota = columna("N° de cuota")
    c_codigo = columna("Código de autorización de venta")
    c_tarjeta = columna("N° de tarjeta")
    if c_monto is None or c_codigo is None:
        raise ArchivoInvalido(f"El archivo de Transbank {medio} no tiene las columnas de monto y código de autorización.")

    resumen = {}
    for i in range(fila):
        etiqueta = _texto(raw.iat[i, 1]) if raw.shape[1] > 1 else ""
        if etiqueta and raw.shape[1] > 3:
            resumen[_sin_tildes(etiqueta)] = raw.iat[i, 3]

    fecha_abono = None
    fila_periodo = _buscar_fila(raw.iloc[:fila], lambda f: any("Periodo de consulta" in v for v in f))
    if fila_periodo is not None:
        valores = raw.iloc[fila_periodo].tolist()
        for j, v in enumerate(valores):
            if "Periodo de consulta" in _texto(v) and j + 1 < len(valores):
                fecha_abono = _fecha(valores[j + 1])

    ventas = []
    for i in range(fila + 2, len(raw)):
        if not _texto(raw.iat[i, c_fecha]):
            continue
        ventas.append({
            "medio": medio,
            "fecha": _fecha(raw.iat[i, c_fecha]),
            "tipo": _texto(raw.iat[i, c_tipo]) if c_tipo is not None else "",
            "local": _texto(raw.iat[i, c_local]).split(",")[0] if c_local is not None else "",
            "monto": _numero(raw.iat[i, c_monto]),
            "valido": _numero(raw.iat[i, c_valido]) if c_valido is not None else 0.0,
            "comision": _numero(raw.iat[i, c_comision]) + (_numero(raw.iat[i, c_iva]) if c_iva is not None else 0.0) if c_comision is not None else 0.0,
            "abono": _numero(raw.iat[i, c_abono]) if c_abono is not None else 0.0,
            "cuota": _texto(raw.iat[i, c_cuota]) if c_cuota is not None else "",
            "tarjeta": _texto(raw.iat[i, c_tarjeta]) if c_tarjeta is not None else "",
            "autorizacion": _texto(raw.iat[i, c_codigo]),
            "codigo": _codigo(raw.iat[i, c_codigo]),
            "codigo_flex": _codigo_flexible(raw.iat[i, c_codigo]),
        })

    total_ventas = _numero(resumen.get("total ventas (+)")) or sum(v["monto"] for v in ventas)
    comision = _numero(resumen.get("comision transbank (-)")) + _numero(resumen.get("iva de comision transbank (-)"))
    total_abono = _numero(resumen.get("total abono")) or sum(v["abono"] for v in ventas)
    return {
        "medio": medio,
        "fecha_abono": fecha_abono,
        "total_ventas": total_ventas,
        "comision": comision,
        "total_abono": total_abono,
        "ventas": ventas,
    }


def leer_cartola(archivo):
    """Abonos de Transbank en la cartola del banco."""
    raw = _leer(archivo)
    fila = _buscar_fila(raw, lambda f: "Descripción" in f and any(v.startswith("Abonos") for v in f))
    if fila is None:
        raise ArchivoInvalido("La cartola no tiene la fila de encabezados (Fecha, Descripción, Abonos).")
    encabezado = [_texto(v) for v in raw.iloc[fila].tolist()]
    c_fecha = encabezado.index("Fecha")
    c_desc = encabezado.index("Descripción")
    c_abono = next(i for i, v in enumerate(encabezado) if v.startswith("Abonos"))

    abonos = []
    for i in range(fila + 1, len(raw)):
        desc = _texto(raw.iat[i, c_desc])
        if not re.search(r"transbank|tbk", desc, re.I):
            continue
        monto = _numero(raw.iat[i, c_abono])
        if monto:
            abonos.append({"fecha": _fecha(raw.iat[i, c_fecha]), "descripcion": desc, "monto": monto})
    return abonos


# ---------------------------------------------------------------------------
# Cruce
# ---------------------------------------------------------------------------
def _cruzar(ventas, pagos, periodo):
    usados = set()
    por_codigo = defaultdict(list)
    por_flex = defaultdict(list)
    por_fecha = defaultdict(list)
    for idx, p in enumerate(pagos):
        por_codigo[p["codigo"]].append(idx)
        por_flex[p["codigo_flex"]].append(idx)
        por_fecha[p["fecha"]].append(idx)

    def libre(indices, condicion):
        for idx in indices:
            if idx not in usados and condicion(pagos[idx]):
                return idx
        return None

    def asignar(venta, idx, estado, nota):
        usados.add(idx)
        p = pagos[idx]
        venta.update(
            estado=estado,
            nota=nota,
            monto_bordero=p["monto"],
            diferencia=round(venta["monto"] - p["monto"]),
            documento_bordero=p["documento"],
            cod_bordero=p["cod"],
            fecha_bordero=p["fecha"],
            cuenta_bordero=p["cuenta"],
        )

    def en_periodo(v):
        return periodo is None or (v["fecha"] is not None and periodo[0] <= v["fecha"] <= periodo[1])

    cerca = lambda v: lambda p: abs(p["monto"] - v["monto"]) <= TOLERANCIA  # noqa: E731
    # Un código repetido con otro monto solo cuenta si la venta cae dentro del período del BORDERO.
    mismo_codigo_en_periodo = lambda v: lambda p: en_periodo(v)  # noqa: E731
    pendientes = list(ventas)

    pasadas = [
        (lambda v: por_codigo.get(v["codigo"], []) if v["codigo"] else [], cerca, "conciliado", ""),
        (lambda v: por_flex.get(v["codigo_flex"], []) if v["codigo_flex"] else [], cerca, "conciliado", "Código digitado distinto en el BORDERO"),
        (lambda v: por_codigo.get(v["codigo"], []) if v["codigo"] else [], mismo_codigo_en_periodo, "diferencia", "Mismo código, distinto monto"),
        (lambda v: por_fecha.get(v["fecha"], []), cerca, "conciliado", "Cruzado por monto y fecha: revisar código"),
    ]
    for candidatos, condicion, estado, nota in pasadas:
        siguientes = []
        for v in pendientes:
            idx = libre(candidatos(v), condicion(v))
            if idx is None:
                siguientes.append(v)
            else:
                asignar(v, idx, estado, nota)
        pendientes = siguientes

    for v in pendientes:
        dentro = en_periodo(v)
        v.update(
            estado="sin_registro" if dentro else "fuera_periodo",
            nota="" if dentro else "La venta es de una fecha que el BORDERO no cubre",
            monto_bordero=None, diferencia=None, documento_bordero="", cod_bordero="", fecha_bordero=None, cuenta_bordero="",
        )

    for v in ventas:
        if v["estado"] == "conciliado" and v["diferencia"]:
            v["nota"] = (v["nota"] + "; " if v["nota"] else "") + "Diferencia de redondeo"

    return [p for idx, p in enumerate(pagos) if idx not in usados]


def _por_revisar(v):
    if v["estado"] == "diferencia":
        return abs(v["diferencia"] or 0)
    if v["estado"] == "sin_registro":
        return v["monto"]
    return 0


def procesar(archivos):
    """Ejecuta la conciliación en pesos. Devuelve (resultado para la pantalla, reportes Excel)."""
    pagos, periodo = leer_bordero(archivos["bordero"])
    liquidaciones = [leer_transbank(archivos[campo], medio) for campo, medio in ARCHIVOS_TBK.items() if archivos.get(campo)]
    abonos_banco = leer_cartola(archivos["cartola"]) if archivos.get("cartola") else None

    ventas = [v for liq in liquidaciones for v in liq["ventas"]]
    pendientes_bordero = _cruzar(ventas, pagos, periodo)

    # Abono de cada liquidación en el banco (mismo monto; se prefiere la misma fecha).
    usados_banco = set()
    medios = []
    for liq in liquidaciones:
        propias = [v for v in liq["ventas"]]
        banco = None
        if abonos_banco is not None:
            candidatos = [i for i, a in enumerate(abonos_banco) if i not in usados_banco and abs(a["monto"] - liq["total_abono"]) < 1]
            candidatos.sort(key=lambda i: abonos_banco[i]["fecha"] != liq["fecha_abono"])
            if candidatos:
                usados_banco.add(candidatos[0])
                banco = abonos_banco[candidatos[0]]
        medios.append({
            "medio": liq["medio"],
            "fecha_abono": liq["fecha_abono"].strftime("%d-%m-%Y") if liq["fecha_abono"] else "",
            "ventas": len(propias),
            "total_ventas": liq["total_ventas"],
            "comision": liq["comision"],
            "total_abono": liq["total_abono"],
            "conciliado": sum(v["monto_bordero"] or 0 for v in propias if v["estado"] in ("conciliado", "diferencia")),
            "por_revisar": sum(_por_revisar(v) for v in propias),
            "banco": "sin_cartola" if abonos_banco is None else ("encontrado" if banco else "no_encontrado"),
            "fecha_banco": banco["fecha"].strftime("%d-%m-%Y") if banco and banco["fecha"] else "",
        })

    total = {
        "medio": "Total",
        "ventas": sum(m["ventas"] for m in medios),
        "total_ventas": sum(m["total_ventas"] for m in medios),
        "comision": sum(m["comision"] for m in medios),
        "total_abono": sum(m["total_abono"] for m in medios),
        "conciliado": sum(m["conciliado"] for m in medios),
        "por_revisar": sum(m["por_revisar"] for m in medios),
    }

    cuenta = lambda estado: sum(1 for v in ventas if v["estado"] == estado)  # noqa: E731
    abonos_faltantes = [m["medio"] for m in medios if m["banco"] == "no_encontrado"]
    resumen = {
        "por_revisar": total["por_revisar"],
        "cuadrado": total["por_revisar"] == 0 and not abonos_faltantes,
        "conciliadas": cuenta("conciliado"),
        "con_nota": sum(1 for v in ventas if v["estado"] == "conciliado" and v["nota"]),
        "diferencias": cuenta("diferencia"),
        "sin_registro": cuenta("sin_registro"),
        "fuera_periodo": cuenta("fuera_periodo"),
        "bordero_pendiente": len(pendientes_bordero),
        "abonos_faltantes": abonos_faltantes,
        "banco_cargado": abonos_banco is not None,
        "periodo_bordero": f"{periodo[0]:%d-%m-%Y} al {periodo[1]:%d-%m-%Y}" if periodo else "",
    }

    observaciones = [
        _fila_venta(v) for v in ventas
        if v["estado"] in ("diferencia", "sin_registro") or (v["estado"] == "conciliado" and v["nota"])
    ]
    orden = {"diferencia": 0, "sin_registro": 1, "conciliado": 2, "fuera_periodo": 3}
    observaciones.sort(key=lambda f: (orden[f["estado"]], f["medio"], f["fecha"]))

    resultado = {
        "resumen": resumen,
        "medios": medios,
        "total_medios": total,
        "observaciones": observaciones,
        "archivos_usados": [NOMBRES_ARCHIVO[c] for c in NOMBRES_ARCHIVO if archivos.get(c)],
    }
    reportes = [
        ("completa", "Conciliación completa", "Resumen, todas las ventas de Transbank y lo pendiente del BORDERO.",
         "conciliacion_clp_completa.xlsx", _excel_completo(resultado, ventas, pendientes_bordero, resumen)),
        ("por_revisar", "Por revisar", "Diferencias de monto, ventas sin registro y cruces a revisar.",
         "conciliacion_clp_por_revisar.xlsx", _excel_ventas("Ventas por revisar", observaciones)),
        ("bordero_pendiente", "BORDERO sin abono", "Pagos con tarjeta del BORDERO que no vienen en estos abonos.",
         "bordero_sin_abono.xlsx", _excel_bordero(pendientes_bordero)),
    ]
    return resultado, reportes


def _fila_venta(v):
    return {
        "medio": v["medio"],
        "fecha": v["fecha"].strftime("%d-%m-%Y") if v["fecha"] else "",
        "local": v["local"],
        "autorizacion": v["autorizacion"],
        "tarjeta": v["tarjeta"],
        "cuota": v["cuota"],
        "monto": v["monto"],
        "monto_bordero": v["monto_bordero"],
        "diferencia": v["diferencia"],
        "documento_bordero": v["documento_bordero"],
        "documento_distinto": bool(v["documento_bordero"]) and _codigo(v["documento_bordero"]) != v["codigo"],
        "cod_bordero": v["cod_bordero"],
        "estado": v["estado"],
        "estado_texto": ESTADOS[v["estado"]],
        "nota": v["nota"],
    }


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
FUENTE = Font(name="Arial", size=10)
FUENTE_NEGRITA = Font(name="Arial", size=10, bold=True)
FUENTE_TITULO = Font(name="Arial", size=13, bold=True, color="0A2C4A")
FONDO_ENCABEZADO = PatternFill("solid", fgColor="E6EEF6")
MONEDA = '"$"#,##0;-"$"#,##0;"-"'

COLUMNAS_VENTAS = [
    ("Medio", "medio", 12), ("Fecha venta", "fecha", 12), ("Local", "local", 28), ("Cód. autorización", "autorizacion", 16),
    ("N° tarjeta", "tarjeta", 20), ("Cuota", "cuota", 8), ("Monto Transbank", "monto", 16), ("Monto BORDERO", "monto_bordero", 16),
    ("Diferencia", "diferencia", 13), ("Documento BORDERO", "documento_bordero", 18), ("Cód. BORDERO", "cod_bordero", 12),
    ("Estado", "estado_texto", 28), ("Observación", "nota", 40),
]


def _hoja_tabla(ws, titulo, columnas, filas, subtitulo=None):
    ws["A1"] = titulo
    ws["A1"].font = FUENTE_TITULO
    inicio = 3
    if subtitulo:
        ws["A2"] = subtitulo
        ws["A2"].font = Font(name="Arial", size=10, italic=True)
        inicio = 4
    for j, (encabezado, _, ancho) in enumerate(columnas, start=1):
        celda = ws.cell(row=inicio, column=j, value=encabezado)
        celda.font = FUENTE_NEGRITA
        celda.fill = FONDO_ENCABEZADO
        celda.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = ancho
    for i, fila in enumerate(filas, start=inicio + 1):
        for j, (encabezado, clave, _) in enumerate(columnas, start=1):
            celda = ws.cell(row=i, column=j, value=fila.get(clave))
            celda.font = FUENTE
            if encabezado.startswith(("Monto", "Diferencia", "Total", "Comisión", "Conciliado", "Por revisar")):
                celda.number_format = MONEDA
    ws.freeze_panes = ws.cell(row=inicio + 1, column=1)
    if filas:
        ws.auto_filter.ref = f"A{inicio}:{get_column_letter(len(columnas))}{inicio + len(filas)}"
    return inicio


def _guardar(wb):
    wb.calculation.fullCalcOnLoad = True  # Excel recalcula las fórmulas de totales al abrir
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _excel_ventas(titulo, filas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Ventas"
    _hoja_tabla(ws, titulo, COLUMNAS_VENTAS, filas)
    return _guardar(wb)


def _excel_bordero(pagos):
    wb = Workbook()
    ws = wb.active
    ws.title = "BORDERO sin abono"
    filas = [{**p, "fecha": p["fecha"].strftime("%d-%m-%Y") if p["fecha"] else ""} for p in pagos]
    _hoja_tabla(ws, "Pagos con tarjeta del BORDERO sin abono en estos archivos", [
        ("Fecha", "fecha", 12), ("Cód.", "cod", 8), ("Tarjeta", "tarjeta", 14), ("Documento", "documento", 14),
        ("Monto", "monto", 14), ("Cuenta", "cuenta", 12), ("Usuario", "usuario", 14), ("Fila en BORDERO", "fila", 14),
    ], filas, "Pueden abonarse en otro día: revisa los abonos de los días siguientes.")
    return _guardar(wb)


def _excel_completo(resultado, ventas, pendientes, resumen):
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    columnas = [
        ("Medio de pago", "medio", 16), ("Fecha abono", "fecha_abono", 13), ("N° ventas", "ventas", 10),
        ("Total ventas", "total_ventas", 16), ("Comisión + IVA", "comision", 15), ("Total abono", "total_abono", 16),
        ("Conciliado en BORDERO", "conciliado", 18), ("Por revisar", "por_revisar", 14), ("Abono en banco", "banco_texto", 16),
    ]
    textos_banco = {"encontrado": "Encontrado", "no_encontrado": "No encontrado", "sin_cartola": "Sin cartola"}
    filas = [{**m, "banco_texto": textos_banco[m["banco"]] + (f" ({m['fecha_banco']})" if m["fecha_banco"] else "")} for m in resultado["medios"]]
    inicio = _hoja_tabla(ws, "Conciliación en pesos: Transbank vs. BORDERO", columnas, filas,
                         f"Período del BORDERO: {resumen['periodo_bordero']}")
    fila_total = inicio + len(filas) + 1
    ws.cell(row=fila_total, column=1, value="Total").font = FUENTE_NEGRITA
    for j in range(3, 9):
        letra = get_column_letter(j)
        celda = ws.cell(row=fila_total, column=j, value=f"=SUM({letra}{inicio + 1}:{letra}{fila_total - 1})")
        celda.font = FUENTE_NEGRITA
        if j > 3:
            celda.number_format = MONEDA

    ws2 = wb.create_sheet("Transbank vs BORDERO")
    _hoja_tabla(ws2, "Todas las ventas de Transbank", COLUMNAS_VENTAS, [_fila_venta(v) for v in ventas])

    ws3 = wb.create_sheet("BORDERO sin abono")
    filas_b = [{**p, "fecha": p["fecha"].strftime("%d-%m-%Y") if p["fecha"] else ""} for p in pendientes]
    _hoja_tabla(ws3, "Pagos con tarjeta del BORDERO sin abono en estos archivos", [
        ("Fecha", "fecha", 12), ("Cód.", "cod", 8), ("Tarjeta", "tarjeta", 14), ("Documento", "documento", 14),
        ("Monto", "monto", 14), ("Cuenta", "cuenta", 12), ("Usuario", "usuario", 14), ("Fila en BORDERO", "fila", 14),
    ], filas_b)
    return _guardar(wb)
