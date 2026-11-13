"""Lógica de la conciliación en dólares (ERP, Transbank, cartolas de tarjetas y banco).

No depende de las vistas: recibe los archivos subidos y devuelve los datos para la
pantalla y los Excel de descarga. Las listas de trabajo son de módulo (herencia del
código original), por eso cada análisis se ejecuta con un candado.

Cómo se cruza cada venta de Transbank con el ERP. Cada pago del ERP se usa una sola vez, debe ser
de la misma tarjeta y las pasadas van de la coincidencia más segura a la menos segura. El monto en
dólares del pago sale de la cartola de la tarjeta (el ERP lo tiene en pesos):

1. Mismo código, mismo monto (tolerancia de redondeo) y fecha cercana.
2. Mismo código y fecha cercana, en varios documentos que juntos suman el monto.
3. Código parecido (ceros a la izquierda, "I" por "1", "O" por "0"), mismo monto y fecha cercana.
4. Mismo código y fecha cercana, con otro monto: diferencia de monto.
5. Código parecido y fecha cercana, con otro monto: diferencia de monto.
6. Otro código, pero mismo monto y misma fecha: se vincula y se marca para revisar.
7. Código parecido y mismo monto en otra fecha: se vincula y se marca para revisar.
8. Lo que queda: sin registro en el ERP.

Si varios pagos sirven, se elige el de fecha más cercana y luego el de monto más cercano. Las
pasadas 4 y 5 van antes que la 6 porque Transbank suele redondear a dólares enteros: un código con
su fecha pesa más que un monto parecido de otro código.
"""
import hashlib
import re
import threading
from collections import Counter, defaultdict
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font

from . import graficos, lectura, logica_clp
from .bines import identificar_local
from .parametros import Parametros

ArchivoNoValido = logica_clp.ArchivoInvalido

# ---------------------------------------------------------------------------
# Resultados del último análisis (los usan las descargas de Excel).
# Se limpian al comenzar cada análisis.
# ---------------------------------------------------------------------------
informacion_proceso = []
tc_inf = []
documento_inf = []
monto_buscar_inf = []
fecha_inf = []

COLS_ERP = list(range(1, 11))
COLS_TBK = list(range(1, 11))
COLS_BANCO = list(range(1, 9))
COLS_TARJETA = list(range(1, 15))
TOLERANCIA_USD = 0.005  # para comparar montos con decimales leídos de formatos distintos
TOLERANCIA_REDONDEO_USD = Parametros().tolerancia_usd  # por defecto; se cambia en «Configuración»
COLS_MONTOS = ("Unnamed: 12", "Unnamed: 13", "Unnamed: 14")  # otra moneda, saldo, saldo corregido

NOMBRES_TARJETA = ["Amex US$", "Dinners US$", "Master Card US$", "Visa US$"]
CODIGO_A_NOMBRE = {"AX": "Amex US$", "DI": "Dinners US$", "MC": "Master Card US$", "VI": "Visa US$"}
MARCA_GRAFICO = {"VI": "Visa", "MC": "Mastercard", "AX": "American Express", "DI": "Diners"}

# campo del formulario -> nombre visible
NOMBRES_ARCHIVO = {
    "archivo1": "ERP",
    "archivo2": "Amex",
    "archivo3": "Dinners",
    "archivo4": "Visa",
    "archivo5": "Mastercard",
    "archivo6": "Banco",
    "archivo7": "Transbank",
}

# código Transbank -> (campo del formulario, nombre para mensajes)
TARJETAS_TBK = {
    "AX": ("archivo2", "AMERICAN EXPRESS"),
    "DI": ("archivo3", "DINNERS"),
    "VI": ("archivo4", "VISA"),
    "MC": ("archivo5", "MASTER CARD"),
}


# marca de la tarjeta (por BIN) -> código de Transbank del formato antiguo
MARCA_A_CODIGO = [("american", "AX"), ("amex", "AX"), ("diner", "DI"), ("dinner", "DI"),
                  ("master", "MC"), ("maestro", "MC"), ("visa", "VI")]


class LectorExcel:
    """Lee cada archivo subido una sola vez y entrega las columnas por posición.

    Acepta .xls, .xlsx, .xlsm, .ods, CSV y HTML exportado como Excel (ver lectura.py).
    Las columnas se llaman 'Unnamed: <posición>' igual que en el código original, pero
    sin depender del texto de la primera fila ni del motor de Excel, y sin límite de filas.
    Se devuelve una copia para que las modificaciones de una sección no afecten a otra.
    """

    def __init__(self):
        self._hojas = {}
        self._tablas = {}

    def hojas(self, archivo):
        if id(archivo) not in self._hojas:
            self._hojas[id(archivo)] = lectura.leer_hojas(archivo)
        return self._hojas[id(archivo)]

    def es_abonos_por_dia(self, archivo):
        """True si el archivo es el reporte «Abonos por día» del portal de Transbank."""
        for _, df in self.hojas(archivo):
            for i in range(min(len(df), 80)):
                textos = [lectura.normalizar(v) for v in df.iloc[i].tolist()]
                if "fecha de venta" in textos and "medio de pago" in textos:
                    return True
        return False

    def leer(self, archivo, columnas):
        clave = (id(archivo), tuple(columnas))
        if clave not in self._tablas:
            tabla = lectura.tabla_posicional(self.hojas(archivo)[0][1], columnas)
            if "Unnamed: 2" in tabla:
                # documento como número, para comparar 5001, 5001.0 y "5001" de una vez
                tabla["_doc"] = tabla["Unnamed: 2"].map(lectura.numero)
            self._tablas[clave] = tabla
        return self._tablas[clave].copy()


def _clave_fila(valores):
    """Fila del ERP como texto, para reconocerla si viene repetida en otro archivo.
    Un mismo número puede leerse como 107093 o 107093.0 según el resto de la columna."""
    return tuple("" if pd.isna(v) else _texto_codigo(v) for v in valores)


def _juntar_erp(archivos, lector):
    """Junta uno o varios ERP en una sola tabla, por ejemplo un BORDERO por tarjeta.

    Devuelve (tabla, nombres de archivos repetidos, filas repetidas entre archivos). Un archivo
    subido dos veces se lee una sola vez, y una fila que viene en dos archivos se cuenta una vez
    (por ejemplo, si se carga el BORDERO completo junto con los de cada tarjeta). Las filas iguales
    dentro de un mismo archivo se mantienen, porque son movimientos distintos. Solo se comparan los
    movimientos: los encabezados de página y los totales se repiten en todos los archivos.
    """
    tablas, repetidos, huellas = [], [], set()
    vistas, filas_repetidas = Counter(), 0
    columnas = [f"Unnamed: {c}" for c in COLS_ERP]
    for archivo in archivos:
        huella = hashlib.sha256(lectura._bytes(archivo)).hexdigest()
        if huella in huellas:
            repetidos.append(getattr(archivo, "name", "archivo"))
            continue
        huellas.add(huella)
        tabla = lector.leer(archivo, COLS_ERP)
        conteo, conservar = Counter(), []
        for valores in tabla[columnas].itertuples(index=False):
            if lectura.numero(valores[7]) is None:  # columna 8, Valor: sin monto no es un movimiento
                conservar.append(True)
                continue
            clave = _clave_fila(valores)
            conteo[clave] += 1
            nueva = conteo[clave] > vistas[clave]
            conservar.append(nueva)
            filas_repetidas += not nueva
        vistas |= conteo
        tablas.append(tabla[conservar])
    return pd.concat(tablas, ignore_index=True), repetidos, filas_repetidas


def _erp(archivos, lector):
    """Tabla del ERP (uno o varios archivos, ver _juntar_erp). Se arma una sola vez por análisis."""
    if "erp" not in lector._tablas:
        lector._tablas["erp"] = _juntar_erp(logica_clp._lista(archivos["archivo1"]), lector)
    return lector._tablas["erp"][0].copy()


def _pagos_us(erp):
    """Solo las filas de pagos con tarjeta en dólares. El BORDERO completo trae todos los movimientos
    del hotel, y el código de una venta puede aparecer en otras filas (por ejemplo «Venta:303742» en
    un consumo del bar), que no son el pago de esa venta."""
    es_pago = erp["Unnamed: 5"].map(lambda d: any(pago in lectura.normalizar(d) for pago in PAGOS_US))
    return erp[es_pago.astype(bool)]


def _num(valor, por_defecto=0.0):
    """Monto como float aunque venga como texto ('1.234,56', '$ 1.234'); por_defecto si está vacío."""
    resultado = lectura.numero(valor)
    return por_defecto if resultado is None else resultado


def _entero(valor):
    """Valor absoluto entero (montos y documentos del ERP). 0 si está vacío."""
    return abs(int(_num(valor)))


def _codigo_marca(marca):
    texto = lectura.normalizar(marca)
    return next((codigo for clave, codigo in MARCA_A_CODIGO if clave in texto), "")


def leer_transbank(archivo, lector, identificar=identificar_local):
    """Tabla de Transbank con las columnas del formato antiguo y la lista de abonos calculados.

    Acepta los dos formatos:
    - el antiguo, por posición (2 fecha, 3 código de tarjeta AX/DI/MC/VI, 6 monto, 7 autorización)
      con la fila «Abono Calculado (=):»;
    - el reporte «Abonos por día» del portal (todos los medios de pago en un archivo). La marca
      de cada venta sale del BIN de la tarjeta, y el abono es el «Total abono» del reporte.
    """
    clave = (id(archivo), "transbank")
    if clave in lector._tablas:
        tabla, abonos = lector._tablas[clave]
        return tabla.copy(), list(abonos)

    if not lector.es_abonos_por_dia(archivo):
        tabla, abonos = lector.leer(archivo, COLS_TBK), _abonos_calculados(lector.hojas(archivo))
    else:
        liquidacion = logica_clp.leer_transbank(archivo)
        moneda = lectura.normalizar(liquidacion["moneda"])
        if moneda and "dolar" not in moneda and "usd" not in moneda:
            raise ArchivoNoValido(
                f"{liquidacion['archivo']} es un reporte de Transbank en {liquidacion['moneda'].lower()}. "
                "Cárgalo en la Conciliación en pesos."
            )
        ventas = liquidacion["ventas"]
        datos_bin = identificar({v["bin"] for v in ventas if v["bin"]})
        filas = []
        for v in ventas:
            marca = (datos_bin.get(v["bin"]) or {}).get("marca", "")
            filas.append({
                "Unnamed: 1": v["medio"],
                "Unnamed: 2": v["fecha"].strftime("%d-%m-%Y") if v["fecha"] else "",
                "Unnamed: 3": _codigo_marca(marca) or (marca or "Sin identificar"),
                "Unnamed: 6": v["monto"],
                "Unnamed: 7": v["autorizacion"],
            })
        columnas = [f"Unnamed: {c}" for c in COLS_TBK]
        tabla = pd.DataFrame(filas).reindex(columns=columnas)
        abonos = [liquidacion["total_abono"]] if liquidacion["total_abono"] else []
    lector._tablas[clave] = (tabla, abonos)
    return tabla.copy(), list(abonos)


def _codigo_normalizado(texto):
    return str(texto).strip().upper().lstrip("0")


def _partes_codigo(documento):
    """Códigos que trae el Documento del ERP, sin ceros a la izquierda (Transbank entrega «088459» y
    el ERP «88459»). Se compara cada código completo: «00 DUAL 00819067» trae 819067, pero 135870 no trae 3587."""
    if pd.isna(documento):
        return set()
    partes = map(_codigo_normalizado, re.split(r"[^0-9A-Za-z]+", _texto_codigo(documento)))
    return {parte for parte in partes if parte}


def _limpiar_resultados():
    for lista in (informacion_proceso, tc_inf, documento_inf, monto_buscar_inf, fecha_inf):
        lista.clear()


def _registrar_no_ubicado(tarjeta, documento, monto, fecha):
    tc_inf.append(tarjeta)
    documento_inf.append(documento)
    monto_buscar_inf.append(monto)
    fecha_inf.append(fecha)


# ---------------------------------------------------------------------------
# 1) Banco vs Transbank: ¿el "Abono Calculado" aparece en la cartola?
# ---------------------------------------------------------------------------
def _abonos_calculados(hojas_tbk):
    """Montos de las filas 'Abono Calculado (=):' del archivo de Transbank, en cualquier columna."""
    montos = []
    for _, df in hojas_tbk:
        for fila in df.itertuples(index=False):
            celdas = list(fila)
            for j, celda in enumerate(celdas):
                if lectura.normalizar(celda).startswith("abono calculado"):
                    siguiente = next((lectura.numero(v) for v in celdas[j + 1:] if lectura.numero(v) is not None), None)
                    if siguiente is not None:
                        montos.append(siguiente)
                    break
    return montos


def _abonos_del_banco(hojas_banco):
    """Montos abonados en la cartola. Busca la columna cuyo encabezado contiene 'abono'
    (Banco de Chile: 'Abonos (USD)'; BancoEstado: 'Depósitos / Abonos') en cualquier hoja.
    Si no encuentra encabezado, usa la columna 8 como el código original."""
    for _, df in hojas_banco:
        for i in range(len(df)):
            textos = [lectura.normalizar(v) for v in df.iloc[i].tolist()]
            if "fecha" in textos and any("abono" in t for t in textos):
                columna = next(j for j, t in enumerate(textos) if "abono" in t)
                return [m for m in (lectura.numero(v) for v in df.iloc[i + 1:, columna]) if m]
    df = hojas_banco[0][1]
    return [m for m in (lectura.numero(v) for v in df.iloc[1:, 8]) if m] if df.shape[1] > 8 else []


def _buscar_abono_en_banco(archivo_banco, archivo_tbk, lector, identificar=identificar_local):
    resultado = {"abonado": 0, "ws": 0}
    abonos_banco = _abonos_del_banco(lector.hojas(archivo_banco))

    for monto in leer_transbank(archivo_tbk, lector, identificar)[1]:
        resultado["msg"] = f"encontro abono por {monto}"
        resultado["abono_calculado"] = monto
        if any(abs(abono - monto) < TOLERANCIA_USD for abono in abonos_banco):
            resultado["abonado"] = monto
            resultado["ws"] = 1
            break
    return resultado


# ---------------------------------------------------------------------------
# 2) Transbank -> ERP -> archivo de la tarjeta (llena informacion_proceso)
# ---------------------------------------------------------------------------
def _iguales(a, b):
    """Compara montos aunque uno venga como texto o con distinta precisión."""
    a, b = lectura.numero(a), lectura.numero(b)
    return a is not None and b is not None and abs(a - b) < TOLERANCIA_USD


def _mismo_documento(tabla, documento):
    """Filas de `tabla` cuyo documento (columna 2) es `documento`; 5001, 5001.0 y '5001' son iguales."""
    if documento is None or (isinstance(documento, float) and pd.isna(documento)) or str(documento).strip() == "":
        return pd.Series(False, index=tabla.index)
    buscado = lectura.numero(documento)
    if buscado is None:
        return tabla["Unnamed: 2"].astype(str).str.strip() == str(documento).strip()
    return tabla["_doc"] == buscado


def _montos_tarjeta(fila):
    """Otra moneda, saldo y saldo corregido de una fila de la posición por cliente.
    En los montos chicos el archivo los trae una columna a la derecha: Otra Moneda vacía,
    los dólares en Saldo y los pesos en Saldo Corregido."""
    otra_moneda, saldo, saldo_corregido = (fila[columna] for columna in COLS_MONTOS)
    if lectura.numero(otra_moneda) is None and lectura.numero(saldo) is not None and lectura.numero(saldo_corregido) is not None:
        return saldo, saldo_corregido, None
    return otra_moneda, saldo, saldo_corregido


def _comparar_con_tarjeta(df_tarjeta, codigo_erp, valor_erp, monto_original, nombre):
    """Misma lógica que los 4 bloques DI / VI / MC / AX del código antiguo."""
    datos = {}
    coincidencias = df_tarjeta[_mismo_documento(df_tarjeta, codigo_erp)]
    if coincidencias.empty:
        return datos

    encontro = False
    for idx in coincidencias.index:
        otra_moneda, saldo, saldo_corregido = _montos_tarjeta(coincidencias.loc[idx])

        if _iguales(monto_original, otra_moneda):
            datos["status"] = f"El monto original {monto_original} coincide con OTRA MONEDA {otra_moneda}"
            datos["monto_cartola"] = otra_moneda

        if _iguales(saldo, valor_erp):
            datos["observacion"] = f"El valor ERP {valor_erp} coincide con SALDO {saldo}"
            encontro = True
        elif _iguales(valor_erp, saldo_corregido):
            datos["observacion"] = f"El valor ERP {valor_erp} coincide con SALDO CORREGIDO {saldo_corregido}"
            encontro = True

        if encontro:
            datos["monto_cartola"] = otra_moneda
            break

    if not encontro:
        datos["status"] = f"NO ENCONTRO EL MONTO ORIGINAL {monto_original} EN NINGUNA COLUMNA DE {nombre}"
    return datos


def _texto_codigo(codigo):
    """Código de autorización como texto: 123456.0 -> '123456'."""
    if isinstance(codigo, float) and codigo.is_integer():
        return str(int(codigo))
    return str(codigo).strip()


def _pagos_erp(archivos, lector):
    """Pagos con tarjeta en dólares del ERP, sin las reversas: un movimiento positivo es el reverso
    de un pago igual con el mismo código, y ninguno de los dos cuenta."""
    pagos = []
    for _, fila in _pagos_us(_erp(archivos, lector)).iterrows():
        valor = lectura.numero(fila["Unnamed: 8"])
        if valor:
            pagos.append({
                "partes": _partes_codigo(fila["Unnamed: 9"]),
                "tarjeta": _codigo_marca(fila["Unnamed: 5"]),
                "cuenta": fila["Unnamed: 3"],
                "valor": valor,
                "fecha": logica_clp._fecha(fila["Unnamed: 10"]),
            })
    anulados = set()
    for i, reverso in enumerate(pagos):
        if reverso["valor"] > 0:
            anulados.add(i)
            pago = next((j for j, p in enumerate(pagos) if j not in anulados and p["valor"] == -reverso["valor"]
                         and p["partes"] == reverso["partes"]), None)
            if pago is not None:
                anulados.add(pago)
    return [p for i, p in enumerate(pagos) if i not in anulados]


def _ventas_transbank(archivos, lector, identificar):
    """Ventas de Transbank por conciliar. Una venta sin marca reconocida también se concilia:
    se busca en los pagos de todas las tarjetas y toma la marca del pago que le corresponda."""
    tbk = leer_transbank(archivos["archivo7"], lector, identificar)[0]
    ventas = []
    for fila in tbk.index:
        tipo_tarjeta = tbk.at[fila, "Unnamed: 3"]
        monto_original = tbk.at[fila, "Unnamed: 6"]
        codigo_autorizacion = tbk.at[fila, "Unnamed: 7"]
        fecha_venta = tbk.at[fila, "Unnamed: 2"]

        # Las filas sin código o sin monto son encabezados y totales del reporte.
        if pd.isna(codigo_autorizacion) or lectura.numero(monto_original) is None:
            continue

        codigo = _texto_codigo(codigo_autorizacion)
        ventas.append({
            "codigo": _codigo_normalizado(codigo),
            "flex": logica_clp._codigo_flexible(codigo),
            "fecha": logica_clp._fecha(fecha_venta),
            "monto": _num(monto_original),
            "sin_marca": tipo_tarjeta not in TARJETAS_TBK,
            "reg": {
                "codigo_autorizacion": codigo_autorizacion,
                "documento": "",
                "monto_original": monto_original,
                "monto_cartola": "",
                "diferencia": "",
                "fecha_venta": fecha_venta,
                "tipo_tarjeta": tipo_tarjeta,
                "status": "",
                "observacion": "",
                "nota": "",
                "extra": "OK",
                "estado": "",
                "valor_erp": 0,
                "sin_marca": tipo_tarjeta not in TARJETAS_TBK,
            },
        })
    return ventas


def _cruzar_con_erp(ventas, pagos, en_cartola, tolerancia=TOLERANCIA_REDONDEO_USD, ventana=logica_clp.VENTANA_DIAS):
    """Vincula cada venta con su pago del ERP y llena su registro (ver las pasadas al inicio del módulo).

    `en_cartola(pago, monto)` entrega lo que dice la cartola de la tarjeta sobre ese pago.
    """
    usados = set()
    por_codigo, por_flex, por_fecha = defaultdict(list), defaultdict(list), defaultdict(list)
    for idx, p in enumerate(pagos):
        for parte in p["partes"]:
            por_codigo[parte].append(idx)
            por_flex[logica_clp._codigo_flexible(parte)].append(idx)
        por_fecha[p["fecha"]].append(idx)

    def dolares(v, idx):
        datos = en_cartola(pagos[idx], v["monto"])
        return _num(datos["monto_cartola"]) if "monto_cartola" in datos else None

    def dias(v, idx):
        if v["fecha"] is None or pagos[idx]["fecha"] is None:
            return 0
        return abs((v["fecha"] - pagos[idx]["fecha"]).days)

    def cerca(v, idx):
        monto = dolares(v, idx)
        return monto is not None and _es_redondeo(v["monto"] - monto, tolerancia)

    def igual(v, idx):
        """Para los cruces sin el código en fecha: la tolerancia configurada no se amplía más allá del redondeo."""
        monto = dolares(v, idx)
        return monto is not None and _es_redondeo(v["monto"] - monto, min(tolerancia, TOLERANCIA_REDONDEO_USD))

    def en_fecha(v, idx):
        return dias(v, idx) <= ventana

    def libres(v, indices):
        """Pagos sin usar de la tarjeta de la venta (de cualquiera, si la venta no tiene marca)."""
        return [i for i in dict.fromkeys(indices) if i not in usados and (v["sin_marca"] or pagos[i]["tarjeta"] == v["reg"]["tipo_tarjeta"])]

    def elegir(v, indices, condicion):
        opciones = [i for i in libres(v, indices) if condicion(v, i)]
        if not opciones:
            return None
        return [min(opciones, key=lambda i: (dias(v, i), abs(v["monto"] - (dolares(v, i) or 0))))]

    def dividido(v):
        """Varios documentos con el mismo código y fecha cercana que juntos suman el monto de la venta."""
        opciones = [i for i in libres(v, por_codigo.get(v["codigo"], [])) if en_fecha(v, i)]
        montos = [dolares(v, i) for i in opciones]
        if len(opciones) > 1 and None not in montos and _es_redondeo(v["monto"] - sum(montos), tolerancia):
            return opciones
        return None

    con_codigo = lambda v: por_codigo.get(v["codigo"], [])  # noqa: E731
    con_flex = lambda v: por_flex.get(v["flex"], [])  # noqa: E731
    codigo_digitado = "Código digitado distinto en el ERP"
    pasadas = [
        (lambda v: elegir(v, con_codigo(v), lambda v, i: en_fecha(v, i) and cerca(v, i)), ""),
        (dividido, "Pago dividido en varios documentos"),
        (lambda v: elegir(v, con_flex(v), lambda v, i: en_fecha(v, i) and cerca(v, i)), codigo_digitado),
        (lambda v: elegir(v, con_codigo(v), en_fecha), ""),
        (lambda v: elegir(v, con_flex(v), en_fecha), codigo_digitado),
        (lambda v: elegir(v, por_fecha.get(v["fecha"], []) if v["fecha"] else [], igual), "Cruzado por monto y fecha: revisar código"),
        (lambda v: elegir(v, con_flex(v), igual), "Mismo código y monto en otra fecha: revisar"),
    ]

    pendientes = list(ventas)
    for buscar, nota in pasadas:
        siguientes = []
        for v in pendientes:
            indices = buscar(v)
            if indices is None:
                siguientes.append(v)
            else:
                usados.update(indices)
                _llenar_ubicada(v, [pagos[i] for i in indices], [dolares(v, i) for i in indices], en_cartola, nota,
                                tolerancia)
        pendientes = siguientes
    return pendientes, por_codigo


def _es_redondeo(diferencia, tolerancia=TOLERANCIA_REDONDEO_USD):
    return round(abs(diferencia), 2) <= tolerancia


def _llenar_ubicada(venta, pagos, montos, en_cartola, nota, tolerancia=TOLERANCIA_REDONDEO_USD):
    reg = venta["reg"]
    reg.update(en_cartola(pagos[0], venta["monto"]))
    reg["documento"] = pagos[0]["cuenta"] if len(pagos) == 1 else " + ".join(str(p["cuenta"]) for p in pagos)
    reg["valor_erp"] = sum(_entero(p["valor"]) for p in pagos)
    if venta["sin_marca"]:
        reg["tipo_tarjeta"] = pagos[0]["tarjeta"]

    notas = [nota] if nota else []
    if venta["sin_marca"]:
        notas.append("Marca de la tarjeta tomada del ERP")
    if montos[0] is None:
        # El documento no está en la cartola, o no cuadra en pesos: no hay dólares con qué comparar.
        reg["status"] = reg["status"] or f"EL DOCUMENTO {pagos[0]['cuenta']} NO ESTA EN LA CARTOLA DE LA TARJETA"
        reg.update(monto_cartola=0.0, diferencia=round(venta["monto"], 2), estado="diferencia")
        notas.append("Sin monto en la cartola de la tarjeta")
    else:
        monto_cartola = round(sum(m for m in montos if m is not None), 2)
        diferencia = round(venta["monto"] - monto_cartola, 2)
        reg.update(monto_cartola=monto_cartola, diferencia=diferencia)
        if not _es_redondeo(diferencia, tolerancia):
            reg["estado"] = "diferencia"
            notas.append("Diferencia de monto")
        elif diferencia:
            reg["estado"] = "redondeo"
            notas.append("Diferencia de redondeo")
        else:
            reg["estado"] = "conciliada"
    reg["nota"] = "; ".join(notas)


def _llenar_sin_registro(venta, pagos, por_codigo, periodo):
    reg = venta["reg"]
    reg["status"] = f"NO ENCONTRO EL CODIGO : {reg['codigo_autorizacion']} CUYO VALOR ES DE {reg['monto_original']} "
    reg["extra"] = "NO"
    dentro = periodo is None or (venta["fecha"] is not None and periodo[0] <= venta["fecha"] <= periodo[1])
    reg["estado"] = "sin_registro" if dentro else "fuera_periodo"

    mismos = [pagos[i] for i in por_codigo.get(venta["codigo"], [])]
    notas = []
    if venta["sin_marca"]:
        notas.append("Marca de la tarjeta no identificada")
    if not dentro:
        notas.append("La venta es de una fecha que el ERP no cubre")
    if any(p["tarjeta"] != reg["tipo_tarjeta"] for p in mismos) and not venta["sin_marca"]:
        notas.append("El código está en un pago de otra tarjeta")
    elif mismos:
        notas.append("El código está en el ERP, pero en otra fecha o usado por otra venta")
    reg["nota"] = "; ".join(notas)


def _conciliar_transbank_con_erp(archivos, lector, identificar=identificar_local, parametros=None):
    parametros = parametros or Parametros()
    ventas = _ventas_transbank(archivos, lector, identificar)
    pagos = _pagos_erp(archivos, lector)
    cartolas = {
        codigo: lector.leer(archivos[campo], COLS_TARJETA) if archivos[campo] else None
        for codigo, (campo, _) in TARJETAS_TBK.items()
    }

    def en_cartola(pago, monto):
        nombre = TARJETAS_TBK[pago["tarjeta"]][1]
        if cartolas[pago["tarjeta"]] is None:
            return {"status": f"NO SE CARGO EL ARCHIVO DE {nombre}"}
        return _comparar_con_tarjeta(cartolas[pago["tarjeta"]], pago["cuenta"], _entero(pago["valor"]), monto, nombre)

    pendientes, por_codigo = _cruzar_con_erp(ventas, pagos, en_cartola, parametros.tolerancia_usd,
                                             parametros.ventana_dias)
    periodo = _periodo(archivos, lector, identificar)
    for venta in pendientes:
        _llenar_sin_registro(venta, pagos, por_codigo, periodo)
    informacion_proceso.extend(v["reg"] for v in ventas)


# ---------------------------------------------------------------------------
# 3) ERP -> cartola de cada tarjeta: el documento debe estar y con el mismo monto
# ---------------------------------------------------------------------------
def _valor_en_columnas(filas, valor_buscado):
    for idx in filas.index:
        for col in COLS_MONTOS:
            valor = filas.at[idx, col]
            if not pd.isna(valor) and _entero(valor) == valor_buscado:
                return True
    return False


def _procesar_erp(archivos, lector):
    diccionario = {}
    erp = _erp(archivos, lector)
    cartolas = {
        CODIGO_A_NOMBRE[codigo]: lector.leer(archivos[campo], COLS_TARJETA) if archivos[campo] else None
        for codigo, (campo, _) in TARJETAS_TBK.items()
    }

    for i, fila in enumerate(erp.index, start=1):
        codigo_buscar = erp.at[fila, "Unnamed: 3"]
        monto_erp = erp.at[fila, "Unnamed: 8"]
        descripcion = lectura.normalizar(erp.at[fila, "Unnamed: 5"])
        if lectura.numero(monto_erp) is None or not any(pago in descripcion for pago in PAGOS_US):
            continue

        tarjeta = CODIGO_A_NOMBRE[_codigo_marca(descripcion)]
        cartola = cartolas[tarjeta]
        if cartola is None:
            continue

        valor_buscado = _entero(monto_erp)
        fecha_erp = erp.at[fila, "Unnamed: 10"]
        encontrado = _valor_en_columnas(cartola[_mismo_documento(cartola, codigo_buscar)], valor_buscado)

        documento = _entero(codigo_buscar) if lectura.numero(codigo_buscar) is not None else str(codigo_buscar)
        diccionario[str(i)] = {
            "tarjeta": tarjeta,
            "codigo": documento,
            "Valor": valor_buscado,
            "Status": "encontrado" if encontrado else "no encontrado",
        }
        if not encontrado:
            _registrar_no_ubicado(tarjeta, documento, valor_buscado, fecha_erp)

    return diccionario


# ---------------------------------------------------------------------------
# Tablas de resumen
# ---------------------------------------------------------------------------
def _armar_tabla(valores_us, valores_tbk, decimales=None):
    """Filas para las tablas de resultado: una por tarjeta y una fila de total."""
    redondear = (lambda v: round(v, decimales)) if decimales is not None else (lambda v: v)
    filas = []
    for nombre in NOMBRES_TARJETA:
        us = redondear(valores_us.get(nombre, 0))
        tbk = redondear(valores_tbk.get(nombre, 0))
        filas.append({
            "cuenta": nombre,
            "ventas_cm": us,
            "ventas_tbk": tbk,
            "diferencia": redondear(tbk - us),
            "es_total": False,
        })
    filas.append({
        "cuenta": "Total",
        "ventas_cm": redondear(sum(f["ventas_cm"] for f in filas)),
        "ventas_tbk": redondear(sum(f["ventas_tbk"] for f in filas)),
        "diferencia": redondear(sum(f["diferencia"] for f in filas)),
        "es_total": True,
    })
    return filas


def _resumen_proceso(tabla_dolar, tolerancia=TOLERANCIA_REDONDEO_USD):
    """Indicadores que se muestran arriba de los resultados."""
    diferencia = float(tabla_dolar[-1]["diferencia"]) if tabla_dolar else 0.0
    no_ubicadas = {tuple(r.values()) for r in informacion_proceso if r["extra"] == "NO"}
    cuenta = lambda estado: sum(1 for r in informacion_proceso if r["estado"] == estado)  # noqa: E731
    por_revisar = sum(abs(r["diferencia"]) for r in informacion_proceso if r["estado"] == "diferencia")
    por_revisar += sum(abs(_num(r["monto_original"])) for r in informacion_proceso if r["estado"] == "sin_registro")
    return {
        "diferencia_total": diferencia,
        "por_revisar": round(por_revisar, 2),
        "cuadrado": round(por_revisar, 2) == 0,
        "ubicadas": sum(1 for r in informacion_proceso if r["extra"] == "OK"),
        "no_ubicadas": len(no_ubicadas),
        "erp_sin_tarjeta": len(documento_inf),
        "conciliadas": cuenta("conciliada"),
        "redondeo": cuenta("redondeo"),
        "diferencias": cuenta("diferencia"),
        "fuera_periodo": cuenta("fuera_periodo"),
        "sin_marca": sum(1 for r in informacion_proceso if r["sin_marca"]),
        "con_nota": sum(1 for r in informacion_proceso if r["extra"] == "OK" and "revisar" in r["nota"]),
        "tolerancia_redondeo": tolerancia,
    }


def _resumen_general(diccionario):
    us = dict.fromkeys(NOMBRES_TARJETA, 0)
    tbk = dict.fromkeys(NOMBRES_TARJETA, 0)

    for reg in diccionario.values():
        if reg["Status"] == "encontrado" and reg["tarjeta"] in us:
            us[reg["tarjeta"]] += reg["Valor"]

    for item in informacion_proceso:
        nombre = CODIGO_A_NOMBRE.get(item["tipo_tarjeta"])
        if nombre and item["extra"] == "OK":
            tbk[nombre] += item["valor_erp"]

    return _armar_tabla(us, tbk)


def _resumen_dolar():
    """Ventas CM: lo que dice la cartola de cada tarjeta. Ventas TBK: lo que dice Transbank.
    La diferencia es Transbank menos cartola, igual que en el Excel de cada venta."""
    cartola = dict.fromkeys(NOMBRES_TARJETA, 0)
    tbk = dict.fromkeys(NOMBRES_TARJETA, 0)
    for item in informacion_proceso:
        nombre = CODIGO_A_NOMBRE.get(item["tipo_tarjeta"])
        if nombre and item["extra"] == "OK":
            cartola[nombre] += _num(item["monto_cartola"])
            tbk[nombre] += _num(item["monto_original"])

    return _armar_tabla(cartola, tbk, decimales=2)


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
def _periodo(archivos, lector, identificar=identificar_local):
    """(desde, hasta) de la conciliación, o None si no hay fechas.

    Sale de la fila «Periodo de: … hasta …» del ERP; con varios archivos, desde la fecha más antigua
    hasta la más nueva. Si el ERP no la trae, se usa la primera y la última fecha de sus movimientos
    o, sin ERP, las fechas de venta de Transbank.
    """
    fechas = []
    if archivos["archivo1"]:
        encabezados = [logica_clp.periodo_del_encabezado(lector.hojas(a)[0][1]) for a in logica_clp._lista(archivos["archivo1"])]
        encabezados = [p for p in encabezados if p]
        if encabezados:
            return min(d for d, _ in encabezados), max(h for _, h in encabezados)
        fechas = _erp(archivos, lector)["Unnamed: 10"].map(logica_clp._fecha).dropna().tolist()
    if not fechas and archivos["archivo7"]:
        fechas = leer_transbank(archivos["archivo7"], lector, identificar)[0]["Unnamed: 2"].map(logica_clp._fecha).dropna().tolist()
    return (min(fechas), max(fechas)) if fechas else None


# ---------------------------------------------------------------------------
# Reconocimiento de archivos (recuadro único de carga)
# ---------------------------------------------------------------------------
# marca en «Cliente: … TRANSBANK - TARJETA AMEX US$» de la cartola de tarjeta -> campo del formulario
MARCA_A_CAMPO = [("amex", "archivo2"), ("american", "archivo2"), ("diner", "archivo3"), ("dinner", "archivo3"),
                 ("visa", "archivo4"), ("master", "archivo5")]
PAGOS_US = ("amex us$", "dinners us$", "diners us$", "master card us$", "visa us$")


def _valor_tras(filas, etiqueta):
    """Valor de «<etiqueta>:» en el encabezado: a su derecha (liquidación antigua) o, si a la derecha
    hay otra etiqueta, en la fila siguiente (reporte «Abonos por día»)."""
    for i, fila in enumerate(filas):
        for j, celda in enumerate(fila):
            if celda.startswith(etiqueta):
                derecha = next((c for c in fila[j + 1:] if c), "")
                if derecha and not derecha.endswith(":"):
                    return derecha
                return filas[i + 1][j] if i + 1 < len(filas) and j < len(filas[i + 1]) else ""
    return ""


def clasificar(archivo):
    """(campo del formulario 'archivo1'…'archivo7', '') según el contenido, o (None, motivo)."""
    try:
        hojas = lectura.leer_hojas(archivo)
    except lectura.FormatoNoSoportado as exc:
        return None, str(exc)
    tablas = [[[lectura.normalizar(v) for v in df.iloc[i].tolist()] for i in range(len(df))] for _, df in hojas]

    for filas in tablas:
        encabezado = filas[:80]
        celdas = [c for fila in encabezado for c in fila if c]

        # Cartola de tarjeta: «Posición Por Clientes» del sistema de cuentas por cobrar.
        if any(c.startswith("posicion por clientes") for c in celdas):
            cliente = " ".join(c for c in celdas if "tarjeta" in c)
            campo = next((campo for marca, campo in MARCA_A_CAMPO if marca in cliente), None)
            if campo:
                return campo, ""
            return None, "Es una cartola de tarjeta, pero no se reconoce la marca (Amex, Diners, Visa o Mastercard)."

        # Transbank: liquidación antigua o reporte «Abonos por día».
        if any(c.startswith("abono calculado") for c in celdas) or any(
            "fecha de venta" in fila and "medio de pago" in fila for fila in encabezado
        ):
            moneda = _valor_tras(encabezado, "moneda")
            if "peso" in moneda or "clp" in moneda:
                return None, "Es un reporte de Transbank en pesos: cárgalo en la Conciliación en pesos."
            return "archivo7", ""

        # Cartola del banco: fila con Fecha y una columna de abonos, de una cuenta en dólares
        # («Abonos (USD)» o «Moneda: Dólar Americano»). BancoEstado no indica moneda: es la cuenta en pesos.
        fila_banco = next((f for f in encabezado if "fecha" in f and any("abono" in c for c in f)), None)
        if fila_banco:
            moneda = _valor_tras(encabezado, "moneda")
            if any("usd" in c for c in fila_banco) or "dolar" in moneda or "usd" in moneda:
                return "archivo6", ""
            return None, "Es una cartola en pesos: cárgala en la Conciliación en pesos."

        # ERP (BORDERO del FrontOffice): pagos con tarjeta en dólares.
        if any(any(pago in c for pago in PAGOS_US) for fila in filas for c in fila):
            return "archivo1", ""

    return None, "No parece un ERP, un reporte de Transbank, una cartola del banco ni una cartola de tarjeta en dólares."


def validar_archivos(archivos):
    """Errores de combinación de archivos (los mismos que avisa la pantalla)."""
    errores = []
    if not any(archivos.values()):
        errores.append("Carga al menos un archivo para analizar.")
    if archivos["archivo7"] and not archivos["archivo1"]:
        errores.append("Para analizar Transbank también debes cargar el archivo ERP.")
    if archivos["archivo6"] and not archivos["archivo7"]:
        errores.append("Para buscar el abono en el banco también debes cargar el archivo de Transbank.")
    return errores


_candado = threading.Lock()


def procesar(archivos, identificar=identificar_local, parametros=None):
    """Ejecuta el análisis completo. Devuelve (resultado para la pantalla, reportes Excel).

    `parametros`: tolerancia de redondeo en dólares y ventana de días (ver parametros.py).
    """
    parametros = parametros or Parametros()
    with _candado:
        _limpiar_resultados()
        lector = LectorExcel()
        resultado = {}

        if archivos["archivo6"]:
            resultado.update(_buscar_abono_en_banco(archivos["archivo6"], archivos["archivo7"], lector, identificar))

        if archivos["archivo7"]:
            _conciliar_transbank_con_erp(archivos, lector, identificar, parametros)

        diccionario = _procesar_erp(archivos, lector) if archivos["archivo1"] else {}

        resultado["data"] = _resumen_general(diccionario)
        resultado["data_dolar"] = _resumen_dolar()
        resultado["resumen"] = _resumen_proceso(resultado["data_dolar"], parametros.tolerancia_usd)
        resultado["parametros"] = parametros.como_dict()
        if archivos["archivo1"]:
            _, resultado["resumen"]["erp_repetidos"], resultado["resumen"]["filas_erp_repetidas"] = lector._tablas["erp"]
        resultado["archivos_usados"] = [NOMBRES_ARCHIVO[c] for c, a in archivos.items() if a]
        resultado["periodo"] = _periodo(archivos, lector, identificar)
        resultado["graficos"] = graficos.datos_usd(
            informacion_proceso, MARCA_GRAFICO.get, _num, logica_clp._fecha
        )

        reportes = [
            ("ubicadas", "Transacciones ubicadas", "Abonadas y sus diferencias contra cada cartola.",
             "transacciones_ubicadas.xlsx", excel_ubicadas()),
            ("no_ubicadas", "No ubicadas en el ERP", "Transacciones de Transbank sin registro contable.",
             "transacciones_no_ubicadas.xlsx", excel_no_ubicadas()),
            ("erp_sin_respaldo", "ERP sin respaldo en cartolas", "Documentos del ERP que no aparecen en la cartola de su tarjeta.",
             "erp_sin_respaldo_en_cartolas.xlsx", excel_erp_sin_respaldo()),
        ]
        return resultado, reportes


# ---------------------------------------------------------------------------
# Excel de descarga
# ---------------------------------------------------------------------------
COLUMNAS_PROCESO = [
    "codigo_autorizacion", "documento", "monto_original", "monto_cartola", "diferencia",
    "fecha_venta", "tipo_tarjeta", "status", "observacion", "nota", "extra",
]


def _excel(df, titulo, subtitulo=None):
    """Genera el .xlsx (bytes) con título y subtítulo opcional sobre la tabla."""
    filas_encabezado = 2 if subtitulo else 1

    buffer = BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl", startrow=filas_encabezado)
    buffer.seek(0)

    wb = load_workbook(buffer)
    ws = wb.active
    ultima_columna = max(df.shape[1], 1)

    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ultima_columna)

    if subtitulo:
        ws["A2"] = subtitulo
        ws["A2"].font = Font(italic=True)
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ultima_columna)

    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _df_proceso(extra):
    """Filas de informacion_proceso con extra == 'OK' o 'NO', ordenadas como antes."""
    df = pd.DataFrame(informacion_proceso, columns=COLUMNAS_PROCESO)
    df = df[df["extra"] == extra]
    return df.sort_values(by=["tipo_tarjeta", "status"])


def excel_erp_sin_respaldo():
    """Documentos del ERP que no se encontraron en la cartola de su tarjeta."""
    df = pd.DataFrame({"Documento": documento_inf, "Monto": monto_buscar_inf, "Fecha": fecha_inf, "TC": tc_inf})
    return _excel(df, "Reporte de Transacciones No Encontradas")


def excel_ubicadas():
    """Transacciones de Transbank ubicadas en el ERP, con sus diferencias."""
    return _excel(_df_proceso("OK"), "Reporte de Transacciones Abonadas y Diferencias")


def excel_no_ubicadas():
    """Transacciones de Transbank cuyo código de autorización no está en el ERP."""
    return _excel(
        _df_proceso("NO").drop_duplicates(),
        "Reporte de Transacciones No Encontradas",
        "(Transacciones que no se encuentran en el ERP)",
    )
