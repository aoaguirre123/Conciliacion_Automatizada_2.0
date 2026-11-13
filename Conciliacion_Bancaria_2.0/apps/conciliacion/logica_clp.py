"""Conciliación en pesos (CLP).

Cruza las liquidaciones de Transbank ("Abonos por día" de Crédito, Débito y Prepago)
contra los pagos con tarjeta registrados en el BORDERO del FrontOffice, y verifica
que el total abonado por Transbank aparezca en la cartola del banco.

Cómo se cruza cada venta de Transbank con el BORDERO (cada pago del BORDERO se usa
una sola vez, y las pasadas van de la coincidencia más segura a la menos segura):

1. Mismo código de autorización, mismo monto (tolerancia de redondeo) y fecha cercana.
2. Código parecido (ceros a la izquierda, "I" por "1", "O" por "0"), mismo monto y fecha cercana.
3. Otro código, pero mismo monto y misma fecha: se concilia y se marca para revisar.
4. Mismo código y fecha cercana, pero distinto monto: diferencia de monto.
5. Mismo código y monto, pero en otra fecha: se concilia y se marca para revisar.
6. Lo que queda: sin registro en el BORDERO (o fuera del período del BORDERO).

Si varios pagos sirven, se elige el de fecha más cercana a la venta. Fecha cercana es hasta
VENTANA_DIAS días: un BORDERO largo repite códigos cortos, así que el código solo no basta.

Todo el estado es local a cada llamada: no hay variables globales.
"""
import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations
from datetime import date, datetime
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import graficos, lectura
from . import parametros as parametros_mod
from .parametros import Parametros

from .bines import SIN_IDENTIFICAR, agrupar, bin_de, identificar_local

# Valores por defecto; el administrador los cambia en «Configuración» (ver parametros.py).
TOLERANCIA = parametros_mod.TOLERANCIA_CLP  # pesos: diferencia aceptada entre el FrontOffice y Transbank
TOLERANCIA_REDONDEO = 10  # pesos: hasta aquí, la diferencia se informa como redondeo
VENTANA_DIAS = parametros_mod.VENTANA_DIAS  # días entre la venta y el pago para considerarlos del mismo movimiento

# Campo del formulario -> (medio de pago, nombre visible)
# Campos antiguos del formulario (un archivo por medio). Se siguen aceptando; hoy basta con
# el campo "transbank", que recibe uno o varios archivos con cualquier combinación de medios.
ARCHIVOS_TBK = {
    "credito": "Crédito",
    "debito": "Débito",
    "prepago": "Prepago",
}
ORDEN_MEDIOS = ["Crédito", "Débito", "Prepago"]

NOMBRES_ARCHIVO = {
    "bordero": "BORDERO",
    "transbank": "Transbank",
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
    "D$": "Diners",
    "RCO": "Redcompra",
}
# Respaldo para códigos de tarjeta nuevos que no estén en CODIGOS_TARJETA_CLP: la descripción debe
# nombrar una marca. No se usa "débito" suelto porque también aparece en "IVA Débito Fiscal".
PATRON_TARJETA = re.compile(r"\b(visa|master ?card|amex|american express|diners|dinners|red ?compra|prepago|magna)\b", re.I)
CODIGOS_NO_TARJETA = {"IVA", "TAX", "PROP", "E$", "EUS$", "CXCN", "CXCE"}  # impuestos, propinas, efectivo, cuentas por cobrar

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

ESTADOS = {
    "conciliado": "Conciliado",
    "diferencia": "Diferencia de monto",
    "sin_registro": "Sin registro en BORDERO",
    "fuera_periodo": "Fuera del período del BORDERO",
    "cuota": "Otra cuota de la misma venta",
}
NOMBRES_MES = {v: k.capitalize() for k, v in MESES.items() if k != "setiembre"}


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


def _dia_mes(valor, anio):
    """'22 octubre' (sin año) -> date con el año dado. Acepta también fechas completas."""
    completa = _fecha(valor)
    if completa or anio is None:
        return completa
    m = re.match(r"(\d{1,2})\s+(?:de\s+)?([a-z]+)", _sin_tildes(_texto(valor)))
    if m and m.group(2) in MESES:
        try:
            return date(anio, MESES[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def _cuota(texto):
    """'2/3' -> (2, 3); 'S/C', '-' o vacío -> (None, None)."""
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)", texto or "")
    if m and int(m.group(2)) > 1:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _mas_meses(fecha, meses):
    """(año, mes) de `fecha` más `meses` meses."""
    total = fecha.year * 12 + fecha.month - 1 + meses
    return total // 12, total % 12 + 1


def _codigo(valor):
    """Código de autorización normalizado: mayúsculas y sin ceros a la izquierda."""
    return _texto(valor).upper().lstrip("0")


def _codigo_flexible(valor):
    """Versión tolerante a errores de digitación comunes."""
    return _codigo(_texto(valor).upper().replace("I", "1").replace("O", "0"))


def _leer(archivo, condicion=None):
    """Hoja del archivo que contiene la tabla buscada (cualquier formato, ver lectura.py).

    Revisa todas las hojas: BancoEstado, por ejemplo, entrega la cartola con una hoja
    "Resumen" y los movimientos en la segunda hoja. Si ninguna hoja tiene una fila que
    cumpla `condicion`, devuelve la primera y el que llama informa el error.
    """
    try:
        hojas = lectura.leer_hojas(archivo)
    except lectura.FormatoNoSoportado as exc:
        raise ArchivoInvalido(str(exc)) from exc
    if condicion is not None:
        for _, df in hojas:
            if _buscar_fila(df, condicion) is not None:
                return df
    return hojas[0][1]


def _buscar_fila(raw, condicion):
    for i in range(len(raw)):
        if condicion([_texto(v) for v in raw.iloc[i].tolist()]):
            return i
    return None


# ---------------------------------------------------------------------------
# Lectura de archivos
# ---------------------------------------------------------------------------
def periodo_del_encabezado(raw):
    """(desde, hasta) de la fila «Periodo de: 04/09/2026 hasta 07/09/2026» del FrontOffice, o None."""
    fila = _buscar_fila(raw.head(30), lambda f: "Periodo de:" in f)
    if fila is None:
        return None
    fechas = [f for f in map(_fecha, raw.iloc[fila].tolist()) if f]
    return (min(fechas), max(fechas)) if len(fechas) >= 2 else None


def _pagos_de_bordero(archivo):
    """(pagos con tarjeta en pesos, período) de un archivo BORDERO, sin anulaciones compensadas."""
    nombre = getattr(archivo, "name", "archivo")
    raw = _leer(archivo, _es_encabezado_bordero)
    fila = _buscar_fila(raw, _es_encabezado_bordero)
    if fila is None:
        raise ArchivoInvalido(f"El BORDERO {nombre} no tiene la fila de encabezados (Cod. Deb., Valor, Documento).")
    encabezado = [_texto(v) for v in raw.iloc[fila].tolist()]
    col = {nombre: encabezado.index(nombre) for nombre in ("Cod. Deb.", "Descripción", "Valor", "Documento", "Fecha", "Cuenta", "Usuario") if nombre in encabezado}

    periodo = periodo_del_encabezado(raw)

    pagos = []
    for i in range(fila + 1, len(raw)):
        cod = _texto(raw.iat[i, col["Cod. Deb."]]).upper()
        desc = _texto(raw.iat[i, col["Descripción"]]) if "Descripción" in col else ""
        if not cod or cod == "COD. DEB.":
            continue
        es_tarjeta = cod in CODIGOS_TARJETA_CLP or (
            cod not in CODIGOS_NO_TARJETA
            and PATRON_TARJETA.search(desc)
            and "US$" not in desc.upper()
            and not cod.endswith("US$")
        )
        if not es_tarjeta:
            continue
        pagos.append({
            "archivo": nombre,
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


def _clave_pago(p):
    """Identifica un pago para no contarlo dos veces si viene en dos archivos."""
    return (p["cod"], p["documento"], p["monto"], p["fecha"], p["cuenta"])


def leer_borderos(archivos):
    """Junta uno o varios BORDERO, por ejemplo uno por tarjeta.

    Devuelve (pagos, período, nombres de archivos repetidos, pagos repetidos entre archivos).
    El período va desde la fecha más antigua hasta la más nueva de todos los archivos. Un archivo
    subido dos veces se lee una sola vez, y un pago que viene en dos archivos se cuenta una vez;
    los pagos iguales dentro de un mismo archivo se mantienen, porque son movimientos distintos.
    """
    pagos, periodos, repetidos = [], [], []
    huellas, vistos = set(), Counter()
    pagos_repetidos = 0
    for archivo in archivos:
        archivo.seek(0)
        huella = hashlib.sha256(archivo.read()).hexdigest()
        archivo.seek(0)
        if huella in huellas:
            repetidos.append(getattr(archivo, "name", "archivo"))
            continue
        huellas.add(huella)
        propios, periodo = _pagos_de_bordero(archivo)
        if periodo:
            periodos.append(periodo)
        conteo = Counter()
        for p in propios:
            clave = _clave_pago(p)
            conteo[clave] += 1
            if conteo[clave] > vistos[clave]:
                pagos.append(p)
            else:
                pagos_repetidos += 1
        vistos |= conteo
    if not pagos:
        raise ArchivoInvalido("El BORDERO no tiene pagos con tarjeta en pesos (Visa $, Master Card $, Amex $, Red Compra).")
    periodo = (min(d for d, _ in periodos), max(h for _, h in periodos)) if periodos else None
    return pagos, periodo, repetidos, pagos_repetidos


def leer_bordero(archivo):
    """Pagos con tarjeta en pesos de un solo BORDERO: (pagos, período)."""
    pagos, periodo, _, _ = leer_borderos([archivo])
    return pagos, periodo


def _medio(valor):
    """'Crédito', 'Débito' o 'Prepago' a partir del texto de Transbank; '' si no se reconoce."""
    texto = _sin_tildes(_texto(valor))
    for clave, nombre in (("credito", "Crédito"), ("debito", "Débito"), ("prepago", "Prepago")):
        if clave in texto:
            return nombre
    return ""


def _dato_encabezado(raw, hasta, etiqueta):
    """Valor bajo «<etiqueta>:» en el encabezado del reporte (misma columna, fila siguiente)."""
    fila = _buscar_fila(raw.iloc[:hasta], lambda f: any(v.startswith(etiqueta + ":") for v in f))
    if fila is None or fila + 1 >= hasta:
        return ""
    for j, v in enumerate(raw.iloc[fila].tolist()):
        if _texto(v).startswith(etiqueta + ":"):
            return _texto(raw.iat[fila + 1, j])
    return ""


def es_en_dolares(liquidacion):
    texto = _sin_tildes(liquidacion.get("moneda", ""))
    return "dolar" in texto or "usd" in texto or "us$" in texto


def leer_transbank(archivo, medio=None):
    """Reporte 'Abonos por día' de Transbank: resumen del abono y detalle de ventas.

    El medio de pago de cada venta sale de su columna «Medio de pago». Si no existe, se usa el
    del encabezado del reporte («Medio de pago: Crédito») y, por último, `medio`.
    """
    nombre_archivo = getattr(archivo, "name", "") or "Transbank"
    raw = _leer(archivo, _es_encabezado_transbank)
    fila = _buscar_fila(raw, _es_encabezado_transbank)
    if fila is None:
        raise ArchivoInvalido(f"{nombre_archivo} no tiene la tabla de detalle de Transbank ('Fecha de venta').")

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
    c_medio = columna("Medio de pago")
    c_unico = columna("Número único")
    c_tid = columna("ID transacción")
    if c_monto is None or c_codigo is None:
        raise ArchivoInvalido(f"{nombre_archivo} no tiene las columnas de monto y código de autorización de Transbank.")

    # «Medio de pago:» del encabezado del reporte; el valor está en la fila siguiente, misma columna.
    medio_reporte = ""
    fila_medio = _buscar_fila(raw.iloc[:fila], lambda f: any(v.startswith("Medio de pago") for v in f))
    if fila_medio is not None and fila_medio + 1 < fila:
        for j, v in enumerate(raw.iloc[fila_medio].tolist()):
            if _texto(v).startswith("Medio de pago"):
                medio_reporte = _medio(raw.iat[fila_medio + 1, j])
                break
    medio_por_defecto = medio_reporte or medio or "Sin medio"
    moneda = _dato_encabezado(raw, fila, "Moneda")

    resumen = {}
    for i in range(fila):
        etiqueta = _texto(raw.iat[i, 1]) if raw.shape[1] > 1 else ""
        if etiqueta and raw.shape[1] > 3:
            resumen[_sin_tildes(etiqueta)] = raw.iat[i, 3]

    fecha_abono = None
    desde = hasta = None
    fila_periodo = _buscar_fila(raw.iloc[:fila], lambda f: any("Periodo de consulta" in v for v in f))
    if fila_periodo is not None:
        valores = raw.iloc[fila_periodo].tolist()
        anio = None
        for j, v in enumerate(valores):
            if "Periodo de consulta" in _texto(v) and j + 1 < len(valores):
                fecha_abono = _fecha(valores[j + 1])
                anio = re.search(r"(\d{4})", _texto(valores[j + 1]))
                anio = int(anio.group(1)) if anio else None
        for j, v in enumerate(valores):
            if j + 1 < len(valores) and _texto(v).startswith("Día desde"):
                desde = _dia_mes(valores[j + 1], anio)
            if j + 1 < len(valores) and _texto(v).startswith("Día hasta"):
                hasta = _dia_mes(valores[j + 1], anio)
    desde = desde or fecha_abono
    hasta = hasta or fecha_abono
    if desde and hasta and hasta < desde:  # consulta que cruza el año (diciembre a enero)
        hasta = hasta.replace(year=hasta.year + 1)

    ventas = []
    for i in range(fila + 2, len(raw)):
        if not _texto(raw.iat[i, c_fecha]):
            continue
        ventas.append({
            "medio": (_medio(raw.iat[i, c_medio]) if c_medio is not None else "") or medio_por_defecto,
            "archivo": nombre_archivo,
            "unico": _texto(raw.iat[i, c_unico]) if c_unico is not None else "",
            "tid": _texto(raw.iat[i, c_tid]) if c_tid is not None else "",
            "fecha": _fecha(raw.iat[i, c_fecha]),
            "tipo": _texto(raw.iat[i, c_tipo]) if c_tipo is not None else "",
            "local": _texto(raw.iat[i, c_local]).split(",")[0] if c_local is not None else "",
            "monto": _numero(raw.iat[i, c_monto]),
            "valido": _numero(raw.iat[i, c_valido]) if c_valido is not None else 0.0,
            "comision": _numero(raw.iat[i, c_comision]) + (_numero(raw.iat[i, c_iva]) if c_iva is not None else 0.0) if c_comision is not None else 0.0,
            "abono": _numero(raw.iat[i, c_abono]) if c_abono is not None else 0.0,
            "cuota": _texto(raw.iat[i, c_cuota]) if c_cuota is not None else "",
            "cuota_num": _cuota(_texto(raw.iat[i, c_cuota]) if c_cuota is not None else "")[0],
            "cuota_total": _cuota(_texto(raw.iat[i, c_cuota]) if c_cuota is not None else "")[1],
            "tarjeta": _texto(raw.iat[i, c_tarjeta]) if c_tarjeta is not None else "",
            "bin": bin_de(_texto(raw.iat[i, c_tarjeta])) if c_tarjeta is not None else None,
            "autorizacion": _texto(raw.iat[i, c_codigo]),
            "codigo": _codigo(raw.iat[i, c_codigo]),
            "codigo_flex": _codigo_flexible(raw.iat[i, c_codigo]),
        })

    total_ventas = _numero(resumen.get("total ventas (+)")) or sum(v["monto"] for v in ventas)
    comision = _numero(resumen.get("comision transbank (-)")) + _numero(resumen.get("iva de comision transbank (-)"))
    total_abono = _numero(resumen.get("total abono")) or sum(v["abono"] for v in ventas)
    return {
        "archivo": nombre_archivo,
        "medio": medio_reporte or medio or "",
        "moneda": moneda,
        "fecha_abono": fecha_abono,
        "desde": desde,
        "hasta": hasta,
        "total_ventas": total_ventas,
        "comision": comision,
        "total_abono": total_abono,
        "ventas": ventas,
    }


def _encabezado_cartola(fila):
    """Fila de encabezados de una cartola: tiene Fecha, una descripción y una columna de abonos.

    Banco de Chile:  Fecha | Descripción | Canal o Sucursal | Nro. Docto. | Cargos (CLP) | Abonos (CLP) | Saldo
    BancoEstado:     Fecha | Sucursal | N° Cuenta Corriente | ... | Descripción | Cheques / Cargos | Depósitos / Abonos | Saldo
    """
    textos = [lectura.normalizar(v) for v in fila]
    return "fecha" in textos and any(t.startswith(("descripcion", "glosa", "detalle")) for t in textos) and any("abono" in t for t in textos)


def leer_cartola(archivo, parametros=None):
    """Abonos de Transbank en la cartola del banco (Banco de Chile, BancoEstado u otro con el mismo esquema).

    Un movimiento es de Transbank si su glosa contiene alguna de las palabras clave configuradas.
    """
    patron = (parametros or Parametros()).patron_cartola()
    raw = _leer(archivo, _encabezado_cartola)
    fila = _buscar_fila(raw, _encabezado_cartola)
    if fila is None:
        raise ArchivoInvalido(
            "La cartola no tiene la fila de encabezados con Fecha, Descripción y una columna de Abonos "
            "(por ejemplo «Abonos (CLP)» o «Depósitos / Abonos»)."
        )
    encabezado = [lectura.normalizar(v) for v in raw.iloc[fila].tolist()]
    c_fecha = encabezado.index("fecha")
    c_desc = next(i for i, v in enumerate(encabezado) if v.startswith(("descripcion", "glosa", "detalle")))
    c_abono = next(i for i, v in enumerate(encabezado) if "abono" in v)

    abonos = []
    for i in range(fila + 1, len(raw)):
        desc = _texto(raw.iat[i, c_desc])
        if not patron.search(desc):
            continue
        monto = _numero(raw.iat[i, c_abono])
        if monto:
            abonos.append({"fecha": _fecha(raw.iat[i, c_fecha]), "descripcion": desc, "monto": monto})
    return abonos


def _es_encabezado_bordero(fila):
    return "Cod. Deb." in fila and "Documento" in fila and "Valor" in fila


def _es_encabezado_transbank(fila):
    return "Fecha de venta" in fila


# Tipo de archivo -> fila de encabezados que lo delata, en el orden en que se prueban.
TIPOS_ARCHIVO = {
    "bordero": _es_encabezado_bordero,
    "transbank": _es_encabezado_transbank,
    "cartola": _encabezado_cartola,
}


def clasificar(archivo):
    """('bordero' | 'transbank' | 'cartola', '') según el contenido, o (None, motivo) si no se reconoce."""
    try:
        hojas = lectura.leer_hojas(archivo)
    except lectura.FormatoNoSoportado as exc:
        return None, str(exc)
    for tipo, es_encabezado in TIPOS_ARCHIVO.items():
        for _, df in hojas:
            fila = _buscar_fila(df, es_encabezado)
            if fila is None:
                continue
            if tipo == "transbank" and es_en_dolares({"moneda": _dato_encabezado(df, fila, "Moneda")}):
                return None, "Es un reporte de Transbank en dólares: cárgalo en la Conciliación en dólares."
            return tipo, ""
    return None, "No parece un BORDERO, un reporte «Abonos por día» de Transbank ni una cartola bancaria."


# ---------------------------------------------------------------------------
# Cruce
# ---------------------------------------------------------------------------
def _cruzar(ventas, pagos, periodo, tolerancia=TOLERANCIA, ventana=VENTANA_DIAS):
    usados = set()
    por_codigo = defaultdict(list)
    por_flex = defaultdict(list)
    por_fecha = defaultdict(list)
    for idx, p in enumerate(pagos):
        por_codigo[p["codigo"]].append(idx)
        por_flex[p["codigo_flex"]].append(idx)
        por_fecha[p["fecha"]].append(idx)

    def dias(venta, pago):
        if venta["fecha"] is None or pago["fecha"] is None:
            return 0
        return abs((venta["fecha"] - pago["fecha"]).days)

    def libre(venta, indices, condicion):
        """Pago sin usar que cumple la condición, el de fecha más cercana a la venta."""
        opciones = [idx for idx in indices if idx not in usados and condicion(pagos[idx])]
        return min(opciones, key=lambda idx: dias(venta, pagos[idx]), default=None)

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

    # La tolerancia configurada solo vale cuando el código coincide. Los cruces sin código (por monto
    # y fecha) exigen el mismo monto, salvo redondeo: con una tolerancia amplia unirían ventas distintas.
    cerca = lambda v: lambda p: abs(p["monto"] - v["monto"]) <= tolerancia  # noqa: E731
    igual = lambda v: lambda p: abs(p["monto"] - v["monto"]) <= min(tolerancia, TOLERANCIA_REDONDEO)  # noqa: E731
    cerca_y_en_fecha = lambda v: lambda p: cerca(v)(p) and dias(v, p) <= ventana  # noqa: E731
    # Un código repetido con otro monto solo cuenta si la venta cae dentro del período del BORDERO
    # y el pago es de esos días: en un BORDERO largo, el mismo código puede ser de otra venta.
    mismo_codigo_en_fecha = lambda v: lambda p: en_periodo(v) and dias(v, p) <= ventana  # noqa: E731
    con_codigo = lambda v: por_codigo.get(v["codigo"], []) if v["codigo"] else []  # noqa: E731
    con_flex = lambda v: por_flex.get(v["codigo_flex"], []) if v["codigo_flex"] else []  # noqa: E731
    pendientes = list(ventas)

    # De la coincidencia más segura a la menos segura; cada venta toma la primera que le sirva.
    pasadas = [
        (con_codigo, cerca_y_en_fecha, "conciliado", ""),
        (con_flex, cerca_y_en_fecha, "conciliado", "Código digitado distinto en el BORDERO"),
        (lambda v: por_fecha.get(v["fecha"], []), igual, "conciliado", "Cruzado por monto y fecha: revisar código"),
        (con_codigo, mismo_codigo_en_fecha, "diferencia", "Mismo código, distinto monto"),
        (con_flex, igual, "conciliado", "Mismo código y monto en otra fecha: revisar"),
    ]
    for candidatos, condicion, estado, nota in pasadas:
        siguientes = []
        for v in pendientes:
            idx = libre(v, candidatos(v), condicion(v))
            if idx is None:
                siguientes.append(v)
            else:
                asignar(v, idx, estado, nota)
        pendientes = siguientes

    for v in pendientes:
        dentro = en_periodo(v)
        fuera = "La venta es de una fecha que el BORDERO no cubre"
        if v.get("cuota_total"):
            fuera = f"Cuota {v['cuota_num']}/{v['cuota_total']} de una venta de una fecha que el BORDERO no cubre"
        v.update(
            estado="sin_registro" if dentro else "fuera_periodo",
            nota="" if dentro else fuera,
            monto_bordero=None, diferencia=None, documento_bordero="", cod_bordero="", fecha_bordero=None, cuenta_bordero="",
        )

    for v in ventas:
        if v["estado"] == "conciliado" and v["diferencia"]:
            texto = ("Diferencia de redondeo" if abs(v["diferencia"]) <= TOLERANCIA_REDONDEO
                     else "Diferencia dentro de la tolerancia")
            v["nota"] = (v["nota"] + "; " if v["nota"] else "") + texto

    return [p for idx, p in enumerate(pagos) if idx not in usados]


# Notas de una venta conciliada con el mismo código cuya diferencia se acepta (no hay nada que revisar).
NOTAS_DIFERENCIA_ACEPTADA = {"Diferencia de redondeo", "Diferencia dentro de la tolerancia"}


def diferencia_aceptada(v):
    """Conciliada con el mismo código y una diferencia de redondeo o dentro de la tolerancia.

    Sirve para ventas (motor) y para filas guardadas en el historial (mismas claves estado y nota).
    """
    partes = {p.strip() for p in (v.get("nota") or "").split(";") if p.strip()}
    return v.get("estado") == "conciliado" and bool(partes) and partes <= NOTAS_DIFERENCIA_ACEPTADA


def con_observacion(v):
    """Conciliada, pero con algo que mirar: código escrito distinto, cruce por monto y fecha
    o mismo código en otra fecha."""
    return v.get("estado") == "conciliado" and bool(v.get("nota")) and not diferencia_aceptada(v)


def _por_revisar(v):
    if v["estado"] == "diferencia":
        return abs(v["diferencia"] or 0)
    if v["estado"] == "sin_registro":
        return v["monto"]
    return 0


def _identificar_tarjetas(ventas, identificar):
    """Agrega a cada venta la marca, el tipo, el banco y el país de su tarjeta (por BIN)."""
    datos_bin = identificar({v["bin"] for v in ventas if v["bin"]})
    for v in ventas:
        datos = datos_bin.get(v["bin"]) or {}
        banco, pais = datos.get("banco", ""), datos.get("pais", "")
        v.update(
            marca=datos.get("marca") or SIN_IDENTIFICAR,
            tipo_tarjeta=datos.get("tipo", ""),
            banco=banco,
            pais=pais,
            pais_codigo=datos.get("pais_codigo", ""),
            emisor=f"{banco} ({pais})" if banco and pais else banco,
        )


def _resumen_tarjetas(ventas):
    """Ventas agrupadas por marca y por banco emisor, para la pantalla y el Excel."""
    extranjeras = [v for v in ventas if v["pais_codigo"] and v["pais_codigo"] != "CL"]
    return {
        "por_marca": agrupar(ventas, "marca", _por_revisar),
        "por_emisor": agrupar(ventas, "emisor", _por_revisar),
        "con_banco": sum(1 for v in ventas if v["banco"]),
        "total": len(ventas),
        "extranjeras": len(extranjeras),
        "monto_extranjeras": sum(v["monto"] for v in extranjeras),
    }


def _lista(valor):
    if not valor:
        return []
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


def _leer_liquidaciones(archivos):
    """Lee todos los archivos de Transbank (campo «transbank» y campos antiguos por medio).

    Un mismo archivo subido más de una vez se lee solo una vez. Devuelve (liquidaciones,
    nombres de los archivos repetidos que se ignoraron).
    """
    entradas = [(a, None) for a in _lista(archivos.get("transbank"))]
    entradas += [(a, medio) for campo, medio in ARCHIVOS_TBK.items() for a in _lista(archivos.get(campo))]
    vistos, liquidaciones, repetidos = set(), [], []
    for archivo, medio in entradas:
        archivo.seek(0)
        huella = hashlib.sha256(archivo.read()).hexdigest()
        archivo.seek(0)
        if huella in vistos:
            repetidos.append(getattr(archivo, "name", "archivo"))
            continue
        vistos.add(huella)
        liquidacion = leer_transbank(archivo, medio)
        if es_en_dolares(liquidacion):
            raise ArchivoInvalido(
                f"{liquidacion['archivo']} es un reporte de Transbank en dólares. "
                "Cárgalo en la Conciliación en dólares."
            )
        liquidaciones.append(liquidacion)
    return liquidaciones, repetidos


def _clave_venta(v):
    """Identifica una venta para no contarla dos veces si viene en dos archivos."""
    if v["unico"] and v["unico"] not in ("-", "0"):
        return ("unico", v["unico"], v["cuota"])
    return ("datos", v["tid"], v["codigo"], v["monto"], v["valido"], v["fecha"], v["cuota"], v["tarjeta"])


def _sin_ventas_repetidas(ventas):
    vistas, unicas = set(), []
    for v in ventas:
        clave = _clave_venta(v)
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(v)
    return unicas, len(ventas) - len(unicas)


def _resumen_por_medio(ventas, liquidaciones):
    """Totales por medio de pago calculados desde el detalle de ventas.

    Coinciden con el bloque de resumen de Transbank («Total ventas», «Comisión», «Total abono»)
    y funcionan también cuando un archivo trae varios medios mezclados.
    """
    fechas_por_archivo = {liq["archivo"]: liq["fecha_abono"] for liq in liquidaciones}
    grupos = {}
    for v in ventas:
        grupos.setdefault(v["medio"], []).append(v)
    orden = sorted(grupos, key=lambda m: (ORDEN_MEDIOS.index(m) if m in ORDEN_MEDIOS else len(ORDEN_MEDIOS), m))
    medios = []
    for medio in orden:
        propias = grupos[medio]
        fechas = sorted({fechas_por_archivo.get(v["archivo"]) for v in propias} - {None})
        medios.append({
            "medio": medio,
            "fecha_abono": ", ".join(f.strftime("%d-%m-%Y") for f in fechas),
            "archivos": sorted({v["archivo"] for v in propias}),
            "ventas": len(propias),
            "total_ventas": sum(v["valido"] or v["monto"] for v in propias),
            "comision": sum(v["comision"] for v in propias),
            "total_abono": sum(v["abono"] for v in propias),
            "conciliado": sum(v["monto_bordero"] or 0 for v in propias if v["estado"] in ("conciliado", "diferencia")),
            "por_revisar": sum(_por_revisar(v) for v in propias),
            "banco": "no_encontrado",
            "fecha_banco": "",
            "nota_banco": "",
        })
    return medios


def _buscar_abonos(medios, liquidaciones, abonos_banco):
    """Marca en qué medios se encontró el abono en la cartola.

    1. Un abono por medio de pago (lo habitual).
    2. Si no, un abono que sume varios medios (por ejemplo débito + prepago, o el total de un
       archivo que trae los tres medios juntos).
    Cada movimiento del banco se usa una sola vez; se prefiere el de la misma fecha del abono.
    """
    usados = set()

    def buscar(monto, fecha_texto):
        candidatos = [i for i, a in enumerate(abonos_banco) if i not in usados and abs(a["monto"] - monto) < 1]
        candidatos.sort(key=lambda i: (abonos_banco[i]["fecha"].strftime("%d-%m-%Y") if abonos_banco[i]["fecha"] else "") not in fecha_texto)
        if candidatos:
            usados.add(candidatos[0])
            return abonos_banco[candidatos[0]]
        return None

    def marcar(grupo, banco, nota=""):
        for m in grupo:
            m["banco"] = "encontrado"
            m["fecha_banco"] = banco["fecha"].strftime("%d-%m-%Y") if banco["fecha"] else ""
            m["nota_banco"] = nota

    for m in medios:
        banco = buscar(m["total_abono"], m["fecha_abono"])
        if banco:
            marcar([m], banco)

    pendientes = [m for m in medios if m["banco"] != "encontrado" and m["total_abono"]]
    for tamano in range(len(pendientes), 1, -1):
        for grupo in combinations(pendientes, tamano):
            if any(m["banco"] == "encontrado" for m in grupo):
                continue
            banco = buscar(sum(m["total_abono"] for m in grupo), " ".join(m["fecha_abono"] for m in grupo))
            if banco:
                marcar(grupo, banco, "Abono conjunto: " + " + ".join(m["medio"] for m in grupo))


def _archivos_usados(archivos, liquidaciones):
    usados = []
    borderos = _lista(archivos.get("bordero"))
    if borderos:
        usados.append("BORDERO (" + ", ".join(getattr(a, "name", "archivo") for a in borderos) + ")")
    if liquidaciones:
        usados.append("Transbank (" + ", ".join(liq["archivo"] for liq in liquidaciones) + ")")
    if archivos.get("cartola"):
        usados.append("Cartola bancaria")
    return usados


# ---------------------------------------------------------------------------
# Cuotas
# ---------------------------------------------------------------------------
def _clave_cuotas(v):
    """Identifica la venta original de una cuota: el código y la tarjeta se repiten en cada cuota,
    igual que la fecha y el monto original de la venta."""
    return (v["codigo"], v["fecha"], v["monto"], v["tarjeta"], v["cuota_total"])


def _separar_cuotas(ventas):
    """(ventas que se cruzan con el BORDERO, {venta original: [cuotas]}).

    Una venta en cuotas se registra una sola vez en el BORDERO, por el monto total. Si en los
    archivos vienen varias cuotas de la misma venta, solo la primera se cruza; las demás toman su
    resultado (si no, la segunda cuota quedaría «sin registro» porque el pago ya se usó).
    """
    grupos = defaultdict(list)
    for v in ventas:
        if v.get("cuota_total"):
            grupos[_clave_cuotas(v)].append(v)
    adicionales = set()
    for cuotas in grupos.values():
        cuotas.sort(key=lambda c: c["cuota_num"])
        adicionales.update(id(c) for c in cuotas[1:])
    return [v for v in ventas if id(v) not in adicionales], grupos


def _completar_cuotas(grupos):
    """Las cuotas que no se cruzaron toman el resultado de la primera cuota de su venta."""
    for cuotas in grupos.values():
        primera = cuotas[0]
        for c in cuotas[1:]:
            c.update(
                estado="cuota",
                nota=f"Cuota {c['cuota_num']}/{c['cuota_total']}: la venta se revisa con la cuota "
                     f"{primera['cuota_num']}/{primera['cuota_total']} ({ESTADOS[primera['estado']].lower()})",
                monto_bordero=None, diferencia=None, documento_bordero=primera.get("documento_bordero", ""),
                cod_bordero=primera.get("cod_bordero", ""), fecha_bordero=primera.get("fecha_bordero"),
                cuenta_bordero=primera.get("cuenta_bordero", ""),
            )


def _texto_mes(anio, mes):
    return f"{NOMBRES_MES[mes]} {anio}"


def _seguimiento_cuotas(grupos, liquidaciones):
    """Ventas en cuotas: qué cuotas vienen en los archivos y cuáles no se encontraron.

    Transbank abona cada cuota alrededor de un mes después de la anterior, así que la cuota k se
    espera en el mes de la venta más k - 1 meses. Es una estimación: a veces una cuota se atrasa.
    Una cuota que no está en los archivos se informa para que se concilie con un reporte que
    abarque ese mes; no cambia el monto por revisar.
    """
    fechas = [f for liq in liquidaciones for f in (liq.get("desde"), liq.get("hasta")) if f]
    periodo = (min(fechas), max(fechas)) if fechas else None
    meses_periodo = (_mas_meses(periodo[0], 0), _mas_meses(periodo[1], 0)) if periodo else None

    filas = []
    for cuotas in grupos.values():
        primera = cuotas[0]
        total = primera["cuota_total"]
        encontradas = sorted({c["cuota_num"] for c in cuotas})
        faltantes = []
        for k in range(1, total + 1):
            if k in encontradas or primera["fecha"] is None:
                continue
            anio, mes = _mas_meses(primera["fecha"], k - 1)
            en_periodo = bool(meses_periodo) and meses_periodo[0] <= (anio, mes) <= meses_periodo[1]
            faltantes.append({"cuota": f"{k}/{total}", "mes": _texto_mes(anio, mes), "en_periodo": en_periodo})
        if primera["fecha"] is None:
            faltantes = [{"cuota": f"{k}/{total}", "mes": "", "en_periodo": False}
                         for k in range(1, total + 1) if k not in encontradas]
        filas.append({
            "fecha": primera["fecha"].strftime("%d-%m-%Y") if primera["fecha"] else "",
            "fecha_orden": primera["fecha"] or date.min,
            "autorizacion": primera["autorizacion"],
            "tarjeta": primera["tarjeta"],
            "medio": primera["medio"],
            "monto": primera["monto"],
            "cuotas": total,
            "monto_cuota": primera["valido"],
            "encontradas": ", ".join(f"{k}/{total}" for k in encontradas),
            "faltantes": faltantes,
            "faltantes_texto": ", ".join(f"{f['cuota']} ({f['mes']})" if f["mes"] else f["cuota"] for f in faltantes),
            "estado_venta": ESTADOS[primera["estado"]],
        })
    filas.sort(key=lambda f: (not f["faltantes"], f["fecha_orden"], f["autorizacion"]))
    for f in filas:
        del f["fecha_orden"]
    return {
        "ventas": filas,
        "con_faltantes": sum(1 for f in filas if f["faltantes"]),
        "faltantes": sum(len(f["faltantes"]) for f in filas),
        "faltantes_en_periodo": sum(1 for f in filas for x in f["faltantes"] if x["en_periodo"]),
        "periodo": f"{periodo[0]:%d-%m-%Y} al {periodo[1]:%d-%m-%Y}" if periodo else "",
    }


# ---------------------------------------------------------------------------
# Fechas que cubren los reportes de Transbank
# ---------------------------------------------------------------------------
# Transbank no abona crédito y débito al mismo ritmo: el reporte de un día trae, por ejemplo,
# crédito de hace 2 o 3 días y débito de ayer. Por eso las fechas se separan en dos grupos.
GRUPOS = {"credito": "Crédito", "debito": "Débito y prepago"}
_PATRON_DEBITO = re.compile(r"red ?compra|prepago|debito", re.I)


def _grupo_pago(pago):
    """Grupo de un pago del BORDERO: Redcompra va con débito y prepago; Visa, Mastercard, Amex y
    Diners con crédito."""
    if pago["cod"] == "RCO" or _PATRON_DEBITO.search(_sin_tildes(pago.get("tarjeta", ""))):
        return "debito"
    return "credito"


def _grupo_venta(venta):
    return "credito" if venta["medio"] == "Crédito" else "debito"


def _cobertura(ventas):
    """{grupo: fechas de venta que traen los reportes}. Las cuotas 2 en adelante no cuentan: son de
    ventas antiguas, no de los días que abona el reporte."""
    fechas = defaultdict(set)
    for v in ventas:
        if v["fecha"] and not (v.get("cuota_num") or 0) > 1:
            fechas[_grupo_venta(v)].add(v["fecha"])
    return dict(fechas)


def _texto_fechas(fechas):
    """{4, 5, 6, 9 de sept.} -> '04-09 al 06-09, 09-09'."""
    tramos = []
    for f in sorted(fechas):
        if tramos and (f - tramos[-1][1]).days == 1:
            tramos[-1][1] = f
        else:
            tramos.append([f, f])
    return ", ".join(f"{a:%d-%m}" if a == b else f"{a:%d-%m} al {b:%d-%m}" for a, b in tramos)


def texto_cobertura(cobertura):
    return " · ".join(f"{GRUPOS[g]}: {_texto_fechas(cobertura[g])}" for g in GRUPOS if cobertura.get(g))


def describir(archivo, tipo):
    """Resumen corto que se muestra al soltar un archivo, antes de conciliar."""
    try:
        if tipo == "transbank":
            texto = texto_cobertura(_cobertura(leer_transbank(archivo)["ventas"]))
            return f"ventas de {texto}" if texto else ""
        if tipo == "bordero":
            _, periodo = _pagos_de_bordero(archivo)
            return f"del {periodo[0]:%d-%m-%Y} al {periodo[1]:%d-%m-%Y}" if periodo else ""
    except Exception:  # noqa: BLE001 - la prelectura es solo informativa: nunca debe impedir la carga
        return ""
    finally:
        archivo.seek(0)
    return ""


def _separar_bordero_pendiente(pendientes, cobertura):
    """(pagos sin abono de fechas que cubren los reportes, cantidad de pagos de otras fechas)."""
    if not cobertura:
        return pendientes, 0
    cubiertos = [p for p in pendientes if p["fecha"] in cobertura.get(_grupo_pago(p), set())]
    return cubiertos, len(pendientes) - len(cubiertos)


def procesar(archivos, identificar=identificar_local, parametros=None):
    """Ejecuta la conciliación en pesos. Devuelve (resultado para la pantalla, reportes Excel).

    `identificar` recibe un conjunto de BIN y devuelve {bin: datos}; por defecto solo la marca.
    `parametros` (tolerancia, ventana de días y palabras clave de la cartola); por defecto, los de
    parametros.py.
    """
    parametros = parametros or Parametros()
    pagos, periodo, borderos_repetidos, pagos_repetidos = leer_borderos(_lista(archivos["bordero"]))
    liquidaciones, repetidos = _leer_liquidaciones(archivos)
    abonos_banco = leer_cartola(archivos["cartola"], parametros) if archivos.get("cartola") else None

    ventas, ventas_repetidas = _sin_ventas_repetidas([v for liq in liquidaciones for v in liq["ventas"]])
    _identificar_tarjetas(ventas, identificar)
    a_cruzar, grupos_cuotas = _separar_cuotas(ventas)
    pendientes_bordero = _cruzar(a_cruzar, pagos, periodo, parametros.tolerancia_clp, parametros.ventana_dias)
    _completar_cuotas(grupos_cuotas)
    cuotas = _seguimiento_cuotas(grupos_cuotas, liquidaciones)
    # El cruce usa todo el BORDERO; lo pendiente se limita a las fechas que traen los reportes.
    cobertura = _cobertura(ventas)
    pendientes_bordero, bordero_sin_cobertura = _separar_bordero_pendiente(pendientes_bordero, cobertura)

    medios = _resumen_por_medio(ventas, liquidaciones)
    if abonos_banco is not None:
        _buscar_abonos(medios, liquidaciones, abonos_banco)
    for m in medios:
        if abonos_banco is None:
            m["banco"] = "sin_cartola"

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
        "con_nota": sum(1 for v in ventas if con_observacion(v)),
        "diferencias": cuenta("diferencia"),
        "sin_registro": cuenta("sin_registro"),
        "fuera_periodo": cuenta("fuera_periodo"),
        "otras_cuotas": cuenta("cuota"),
        "cuotas_faltantes": cuotas["faltantes_en_periodo"],
        "bordero_pendiente": len(pendientes_bordero),
        "bordero_sin_cobertura": bordero_sin_cobertura,
        "cobertura": texto_cobertura(cobertura),
        "abonos_faltantes": abonos_faltantes,
        "archivos_repetidos": repetidos,
        "ventas_repetidas": ventas_repetidas,
        "borderos_repetidos": borderos_repetidos,
        "pagos_repetidos": pagos_repetidos,
        "banco_cargado": abonos_banco is not None,
        "periodo_bordero": f"{periodo[0]:%d-%m-%Y} al {periodo[1]:%d-%m-%Y}" if periodo else "",
    }

    # Lo que hay que revisar. Las conciliadas con diferencia aceptada van aparte (no en «Por revisar»).
    observaciones = [_fila_venta(v) for v in ventas if v["estado"] in ("diferencia", "sin_registro") or con_observacion(v)]
    aceptadas = sorted((_fila_venta(v) for v in ventas if diferencia_aceptada(v)), key=lambda f: (f["medio"], f["fecha"]))
    orden = {"diferencia": 0, "sin_registro": 1, "conciliado": 2, "fuera_periodo": 3}
    observaciones.sort(key=lambda f: (orden[f["estado"]], not f["observacion"], f["medio"], f["fecha"]))

    resultado = {
        "periodo": periodo,
        "resumen": resumen,
        "medios": medios,
        "total_medios": total,
        "observaciones": observaciones,
        "aceptadas": aceptadas,
        "tarjetas": _resumen_tarjetas(ventas),
        "archivos_usados": _archivos_usados(archivos, liquidaciones),
        "parametros": parametros.como_dict(),
        "cuotas": cuotas,
        "graficos": graficos.datos_clp(ventas, pendientes_bordero, _por_revisar, con_observacion, ORDEN_MEDIOS),
    }
    reportes = [
        ("completa", "Conciliación completa", "Resumen, todas las ventas de Transbank y lo pendiente del BORDERO.",
         "conciliacion_clp_completa.xlsx", _excel_completo(resultado, ventas, pendientes_bordero, resumen)),
        ("por_revisar", "Por revisar", "Diferencias de monto, ventas sin registro y conciliadas con observación.",
         "conciliacion_clp_por_revisar.xlsx", _excel_ventas("Ventas por revisar", observaciones)),
        ("bordero_pendiente", "BORDERO sin abono", "Pagos con tarjeta del BORDERO de las fechas que traen los reportes, sin abono.",
         "bordero_sin_abono.xlsx", _excel_bordero(pendientes_bordero, resumen)),
    ]
    return resultado, reportes


def _fila_venta(v):
    return {
        "medio": v["medio"],
        "fecha": v["fecha"].strftime("%d-%m-%Y") if v["fecha"] else "",
        "local": v["local"],
        "autorizacion": v["autorizacion"],
        "tarjeta": v["tarjeta"],
        "marca": v["marca"],
        "tipo_tarjeta": v["tipo_tarjeta"],
        "banco": v["banco"],
        "pais": v["pais"],
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
        "observacion": con_observacion(v),
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
    ("N° tarjeta", "tarjeta", 20), ("Marca", "marca", 13), ("Tipo tarjeta", "tipo_tarjeta", 12),
    ("Banco emisor", "banco", 30), ("País emisor", "pais", 16), ("Cuota", "cuota", 8), ("Monto Transbank", "monto", 16), ("Monto BORDERO", "monto_bordero", 16),
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


def _subtitulo_bordero(resumen):
    texto = "Solo pagos de las fechas de venta que traen los reportes de Transbank cargados"
    if resumen.get("cobertura"):
        texto += f" ({resumen['cobertura']})"
    texto += "."
    if resumen.get("bordero_sin_cobertura"):
        texto += (f" Se omitieron {resumen['bordero_sin_cobertura']} pagos de otras fechas: para revisarlos, "
                  "carga los abonos de esos días.")
    return texto


def _excel_bordero(pagos, resumen=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "BORDERO sin abono"
    filas = [{**p, "fecha": p["fecha"].strftime("%d-%m-%Y") if p["fecha"] else ""} for p in pagos]
    _hoja_tabla(ws, "Pagos con tarjeta del BORDERO sin abono en estos archivos", [
        ("Fecha", "fecha", 12), ("Cód.", "cod", 8), ("Tarjeta", "tarjeta", 14), ("Documento", "documento", 14),
        ("Monto", "monto", 14), ("Cuenta", "cuenta", 12), ("Usuario", "usuario", 14),
        ("Archivo BORDERO", "archivo", 30), ("Fila en BORDERO", "fila", 14),
    ], filas, _subtitulo_bordero(resumen or {}))
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

    tarjetas = resultado["tarjetas"]
    columnas_grupo = [("N° ventas", "ventas", 11), ("Monto ventas", "monto", 16), ("Por revisar", "por_revisar", 14)]
    _hoja_tabla(wb.create_sheet("Por marca"), "Ventas de Transbank por marca de tarjeta",
                [("Marca", "nombre", 18)] + columnas_grupo, tarjetas["por_marca"],
                "Marca identificada por los 6 primeros dígitos (BIN) de la tarjeta.")
    _hoja_tabla(wb.create_sheet("Por banco emisor"), "Ventas de Transbank por banco emisor",
                [("Banco emisor (país)", "nombre", 48)] + columnas_grupo, tarjetas["por_emisor"],
                f"Banco identificado en {tarjetas['con_banco']} de {tarjetas['total']} ventas. Fuente: bin-list-data (CC-BY-4.0).")

    cuotas = resultado.get("cuotas") or {}
    if cuotas.get("ventas"):
        _hoja_tabla(wb.create_sheet("Cuotas"), "Ventas en cuotas", [
            ("Fecha venta", "fecha", 12), ("Medio", "medio", 10), ("Autorización", "autorizacion", 13),
            ("Tarjeta", "tarjeta", 22), ("Monto venta", "monto", 15), ("N° cuotas", "cuotas", 10),
            ("Monto cuota", "monto_cuota", 14), ("Cuotas en los archivos", "encontradas", 22),
            ("Cuotas no encontradas (mes esperado)", "faltantes_texto", 42), ("Venta en el BORDERO", "estado_venta", 26),
        ], cuotas["ventas"], "Las cuotas no encontradas no están en los reportes de Transbank cargados: concilia con un "
                             "reporte que abarque el mes esperado para ubicarlas.")

    ws3 = wb.create_sheet("BORDERO sin abono")
    filas_b = [{**p, "fecha": p["fecha"].strftime("%d-%m-%Y") if p["fecha"] else ""} for p in pendientes]
    _hoja_tabla(ws3, "Pagos con tarjeta del BORDERO sin abono en estos archivos", [
        ("Fecha", "fecha", 12), ("Cód.", "cod", 8), ("Tarjeta", "tarjeta", 14), ("Documento", "documento", 14),
        ("Monto", "monto", 14), ("Cuenta", "cuenta", 12), ("Usuario", "usuario", 14),
        ("Archivo BORDERO", "archivo", 30), ("Fila en BORDERO", "fila", 14),
    ], filas_b, _subtitulo_bordero(resumen))
    return _guardar(wb)
