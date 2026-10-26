"""Lectura de las planillas que suben los usuarios, sin importar su formato.

El formato se reconoce por el contenido del archivo, no por la extensión, porque
los portales bancarios y Transbank suelen entregar archivos con la extensión
"equivocada" (por ejemplo, un .xls que en realidad es una página HTML).

Formatos soportados:
- Excel 97-2003 (.xls)
- Excel 2007+ (.xlsx, .xlsm)
- OpenDocument (.ods), si está instalado odfpy
- CSV o texto separado por ; , tab o |
- HTML con tablas (exportaciones "Excel" de portales web), si está instalado lxml

Todas las funciones devuelven DataFrames sin encabezado (header=None): cada módulo
decide dónde empieza su tabla.
"""
import csv
import io
import unicodedata

import pandas as pd


class FormatoNoSoportado(ValueError):
    """El archivo no es una planilla que se pueda leer."""


FIRMA_XLS = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # contenedor OLE2 de Excel 97-2003
FIRMA_ZIP = b"PK\x03\x04"  # .xlsx, .xlsm y .ods son archivos ZIP
# Excel 2.x-5.0 "crudo" (BIFF2/3/4/5 sin contenedor OLE2): el archivo empieza directamente con el
# registro BOF (0x0009, 0x0209, 0x0409 o 0x0809). Es lo que exporta el FrontOffice para el BORDERO.
FIRMAS_BIFF = (b"\x09\x00", b"\x09\x02", b"\x09\x04", b"\x09\x08")


def normalizar(texto):
    """Texto en minúsculas, sin tildes ni espacios repetidos, para comparar encabezados."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    texto = unicodedata.normalize("NFD", str(texto))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(texto.lower().split())


def _nombre(archivo):
    return getattr(archivo, "name", None) or "el archivo"


def _bytes(archivo):
    archivo.seek(0)
    datos = archivo.read()
    archivo.seek(0)
    return datos


def detectar_formato(datos):
    """'xls', 'xlsx', 'ods', 'html' o 'texto' según los primeros bytes."""
    if datos.startswith(FIRMA_XLS) or datos[:2] in FIRMAS_BIFF:
        return "xls"
    if datos.startswith(FIRMA_ZIP):
        return "ods" if b"application/vnd.oasis.opendocument" in datos[:200] else "xlsx"
    inicio = datos[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if inicio.startswith((b"<!doctype html", b"<html", b"<table", b"<?xml", b"<meta")) or b"<table" in inicio:
        return "html"
    return "texto"


def _decodificar(datos):
    for codificacion in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return datos.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1", errors="replace")


def _leer_texto(datos):
    texto = _decodificar(datos)
    muestra = texto[:5000]
    try:
        separador = csv.Sniffer().sniff(muestra, delimiters=";,\t|").delimiter
    except csv.Error:
        separador = ";" if muestra.count(";") > muestra.count(",") else ","
    df = pd.read_csv(io.StringIO(texto), sep=separador, header=None, dtype=object,
                     skip_blank_lines=False, engine="python", on_bad_lines="skip")
    return [("Hoja1", df)]


def _leer_html(datos, nombre):
    try:
        tablas = pd.read_html(io.StringIO(_decodificar(datos)), header=None)
    except ImportError as exc:
        raise FormatoNoSoportado(
            f"{nombre} es una página web guardada como Excel. Ábrelo en Excel y guárdalo como .xlsx, "
            "o instala lxml (pip install lxml)."
        ) from exc
    except ValueError as exc:
        raise FormatoNoSoportado(f"{nombre} parece una página web pero no contiene tablas.") from exc
    return [(f"Tabla{i}", t.astype(object)) for i, t in enumerate(tablas, start=1)]


def leer_hojas(archivo):
    """Lista de (nombre de hoja, DataFrame sin encabezado) con todas las hojas del archivo."""
    nombre = _nombre(archivo)
    datos = _bytes(archivo)
    if not datos:
        raise FormatoNoSoportado(f"{nombre} está vacío.")

    formato = detectar_formato(datos)
    if formato == "texto" and b"\x00" in datos[:4096]:
        # binario desconocido: probar como Excel antes de rendirse
        for motor in ("xlrd", "openpyxl"):
            try:
                return _leer_excel(datos, motor, nombre)
            except FormatoNoSoportado:
                continue
        raise FormatoNoSoportado(f"{nombre} no es una planilla Excel, CSV ni HTML reconocible.")
    if formato == "texto":
        return _leer_texto(datos)
    if formato == "html":
        return _leer_html(datos, nombre)

    return _leer_excel(datos, {"xls": "xlrd", "xlsx": "openpyxl", "ods": "odf"}[formato], nombre)


def _leer_excel(datos, motor, nombre):
    # xlrd escribe avisos ("No CODEPAGE record...") en la consola; se descartan.
    opciones = {"logfile": io.StringIO()} if motor == "xlrd" else {}
    try:
        hojas = pd.read_excel(io.BytesIO(datos), sheet_name=None, header=None, engine=motor, dtype=object,
                              engine_kwargs=opciones)
    except ImportError as exc:
        paquete = {"xlrd": "xlrd", "openpyxl": "openpyxl", "odf": "odfpy"}[motor]
        raise FormatoNoSoportado(
            f"Para leer {nombre} falta el paquete {paquete} (pip install {paquete}), "
            "o guarda el archivo como .xlsx."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - archivo dañado o protegido con contraseña
        raise FormatoNoSoportado(f"No se pudo abrir {nombre}: {exc}") from exc
    return [(hoja, df) for hoja, df in hojas.items() if not df.empty] or [("Hoja1", pd.DataFrame())]


def primera_hoja(archivo):
    return leer_hojas(archivo)[0][1]


def buscar_tabla(archivo, es_encabezado):
    """(DataFrame, fila del encabezado) de la primera hoja que tenga una fila que cumpla
    `es_encabezado(lista de textos normalizados)`. None si ninguna la tiene."""
    for _, df in leer_hojas(archivo):
        for i in range(len(df)):
            if es_encabezado([normalizar(v) for v in df.iloc[i].tolist()]):
                return df, i
    return None


def tabla_posicional(df, columnas):
    """Imita pd.read_excel(usecols=columnas) del código original: la primera fila se
    descarta como encabezado y cada columna se llama 'Unnamed: <posición>'.

    A diferencia de usecols, no falla si el archivo tiene menos columnas (las que
    faltan quedan vacías) y no depende de qué texto haya en la primera fila.
    """
    datos = df.iloc[1:].reset_index(drop=True)
    salida = pd.DataFrame(index=datos.index)
    for c in columnas:
        columna = datos.iloc[:, c] if c < datos.shape[1] else pd.Series(float("nan"), index=datos.index)
        try:  # columnas numéricas que vinieron como texto (CSV) pasan a número
            columna = pd.to_numeric(columna)
        except (ValueError, TypeError):
            columna = columna.infer_objects()
        salida[f"Unnamed: {c}"] = columna
    return salida


def numero(valor):
    """Convierte montos como 1234, '1.234', '$ 1.234,56', '1,234.56' o '(500)' a float.

    Devuelve None si el valor está vacío o no es un número.
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NA:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if hasattr(valor, "item"):  # numpy
        return float(valor.item())
    texto = str(valor).strip().replace("$", "").replace("US", "").replace("\xa0", "").replace(" ", "")
    negativo = texto.startswith("(") and texto.endswith(")")
    texto = texto.strip("()")
    if not texto or texto in ("-", "N/A"):
        return None
    if "," in texto and "." in texto:
        # el separador decimal es el que aparece al final
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        partes = texto.split(",")
        texto = texto.replace(",", ".") if len(partes) == 2 and len(partes[1]) != 3 else texto.replace(",", "")
    elif texto.count(".") > 1 or (texto.count(".") == 1 and len(texto.split(".")[1]) == 3 and len(texto.split(".")[0]) <= 3 and texto.split(".")[0] not in ("0", "")):
        texto = texto.replace(".", "")  # 1.234.567 o 1.234 (miles chilenos)
    try:
        resultado = float(texto)
    except ValueError:
        return None
    return -resultado if negativo else resultado
