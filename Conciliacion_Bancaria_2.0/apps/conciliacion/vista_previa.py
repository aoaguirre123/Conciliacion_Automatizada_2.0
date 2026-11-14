"""Vista previa de cada archivo antes de conciliar (CU-01).

Al soltar un archivo en el recuadro de carga, la aplicación muestra lo que leyó: el período, cuántas
filas trae, los montos totales y las primeras filas, con avisos si algo no calza (por ejemplo, un
BORDERO sin pagos con tarjeta o una cartola sin abonos de Transbank). Así el usuario confirma que
cargó los archivos correctos antes de analizar.

Solo lee: nunca impide la carga. Si un archivo no se puede leer, la vista previa lo dice y la
conciliación informará el error al analizar.
"""
from collections import Counter

from . import lectura, logica, logica_clp
from .bines import identificar_local
from .excepciones import _monto
from .parametros import Parametros

FILAS_MUESTRA = 5


def _fecha(valor):
    return f"{valor:%d-%m-%Y}" if valor else "—"


def _rango_texto(desde, hasta):
    if not desde:
        return "—"
    return _fecha(desde) if desde == hasta else f"{_fecha(desde)} al {_fecha(hasta)}"


def _conteo(contador):
    """Counter -> 'Visa 12 · Mastercard 4', de mayor a menor."""
    return " · ".join(f"{nombre} {n}" for nombre, n in contador.most_common())


def _plural(n, singular, plural=None):
    return f"{n:,}".replace(",", ".") + " " + (singular if n == 1 else (plural or singular + "s"))


def _vista(titulo, resumen, columnas, filas, nombre_filas, avisos=(), rango=None, rol=None, numericas=(), detalle=""):
    """Datos que dibuja la plantilla _vista_previa.html."""
    total = len(filas)
    return {
        "titulo": titulo,
        "detalle": detalle,  # línea corta bajo el nombre del archivo
        "resumen": [(etiqueta, valor) for etiqueta, valor in resumen if valor not in (None, "")],
        "columnas": [{"nombre": c, "numero": c in numericas} for c in columnas],
        "filas": [list(zip(f, (c in numericas for c in columnas))) for f in filas[:FILAS_MUESTRA]],
        "total_filas": total,
        "nombre_filas": nombre_filas,
        "resto": max(0, total - FILAS_MUESTRA),
        "avisos": list(avisos),
        # Para comparar archivos entre sí en el navegador (soltar.js): «base» es el registro del hotel
        # y «ventas» lo que informa Transbank.
        "rango": {"desde": rango[0].isoformat(), "hasta": rango[1].isoformat(), "rol": rol} if rango and rol else None,
    }


def _sin_lectura(titulo, exc):
    return _vista(titulo, [], [], [], "filas", avisos=[f"No se pudo leer: {exc}"])


def _rango(fechas):
    fechas = [f for f in fechas if f]
    return (min(fechas), max(fechas)) if fechas else None


# ---------------------------------------------------------------------------
# Pesos
# ---------------------------------------------------------------------------
def _bordero(archivo):
    pagos, periodo = logica_clp._pagos_de_bordero(archivo)
    total = sum(p["monto"] for p in pagos)
    avisos = []
    if not pagos:
        avisos.append("No trae pagos con tarjeta en pesos (Visa $, Master Card $, Amex $, Red Compra). "
                      "Revisa que sea el BORDERO del período.")
    filas = [[_fecha(p["fecha"]), p["tarjeta"], p["documento"], _monto(p["monto"], "CLP")] for p in pagos]
    return _vista(
        "BORDERO",
        [("Período", _rango_texto(*periodo) if periodo else "—"),
         ("Pagos con tarjeta", _plural(len(pagos), "pago")),
         ("Total pagado con tarjeta", _monto(total, "CLP")),
         ("Por tarjeta", _conteo(Counter(p["tarjeta"] for p in pagos)))],
        ["Fecha", "Tarjeta", "Documento", "Monto"], filas, "pagos", avisos,
        rango=periodo, rol="base", numericas=("Monto",),
    )


def _transbank_clp(archivo):
    liq = logica_clp.leer_transbank(archivo)
    ventas = liq["ventas"]
    avisos = []
    if not ventas:
        avisos.append("El reporte no trae ventas.")
    rango = _rango(v["fecha"] for v in ventas if not (v.get("cuota_num") or 0) > 1)
    filas = [[_fecha(v["fecha"]), v["medio"], v["autorizacion"], v["cuota"] or "—", _monto(v["monto"], "CLP")]
             for v in ventas]
    return _vista(
        "Transbank «Abonos por día»",
        [("Ventas del", _rango_texto(*rango) if rango else "—"),
         ("Fecha de abono", _fecha(liq["fecha_abono"]) if liq.get("fecha_abono") else ""),
         ("Ventas", _plural(len(ventas), "venta")),
         ("Total ventas", _monto(liq["total_ventas"], "CLP")),
         ("Comisión e IVA", _monto(liq["comision"], "CLP") if liq["comision"] else ""),
         ("Total abono", _monto(liq["total_abono"], "CLP")),
         ("Por medio de pago", _conteo(Counter(v["medio"] or "Sin medio" for v in ventas)))],
        ["Fecha de venta", "Medio", "Autorización", "Cuota", "Monto"], filas, "ventas", avisos,
        rango=rango, rol="ventas", numericas=("Monto",),
    )


def _cartola_clp(archivo, parametros):
    abonos = logica_clp.leer_cartola(archivo, parametros)
    avisos = []
    if not abonos:
        palabras = ", ".join(f"«{p}»" for p in parametros.palabras_cartola)
        avisos.append(f"No se encontraron abonos de Transbank: se buscan las glosas con {palabras}. "
                      "Revisa que sea la cartola de la cuenta donde abona Transbank.")
    rango = _rango(a["fecha"] for a in abonos)
    filas = [[_fecha(a["fecha"]), a["descripcion"], _monto(a["monto"], "CLP")] for a in abonos]
    return _vista(
        "Cartola bancaria",
        [("Abonos de Transbank", _plural(len(abonos), "abono")),
         ("Entre el", _rango_texto(*rango) if rango else ""),
         ("Total abonado", _monto(sum(a["monto"] for a in abonos), "CLP") if abonos else "")],
        ["Fecha", "Descripción", "Abono"], filas, "abonos", avisos, numericas=("Abono",),
    )


def de_pesos(archivo, tipo, parametros=None):
    """Vista previa de un archivo de la conciliación en pesos ('bordero', 'transbank' o 'cartola')."""
    titulo = logica_clp.NOMBRES_ARCHIVO.get(tipo, "Archivo")
    try:
        if tipo == "bordero":
            return _bordero(archivo)
        if tipo == "transbank":
            return _transbank_clp(archivo)
        if tipo == "cartola":
            return _cartola_clp(archivo, parametros or Parametros())
    except Exception as exc:  # noqa: BLE001 - la vista previa es informativa: nunca impide la carga
        return _sin_lectura(titulo, exc)
    finally:
        archivo.seek(0)
    return None


# ---------------------------------------------------------------------------
# Dólares
# ---------------------------------------------------------------------------
def _erp(archivo):
    lector = logica.LectorExcel()
    pagos = logica._pagos_erp({"archivo1": [archivo]}, lector)
    periodo = logica_clp.periodo_del_encabezado(lector.hojas(archivo)[0][1]) or _rango(p["fecha"] for p in pagos)
    avisos = []
    if not pagos:
        avisos.append("No trae pagos con tarjeta en dólares (Visa US$, Master Card US$, Amex US$, Diners US$). "
                      "Revisa que sea el ERP del período.")
    marca = lambda p: logica.MARCA_GRAFICO.get(p["tarjeta"], "Sin marca")  # noqa: E731
    filas = [[_fecha(p["fecha"]), marca(p), " / ".join(sorted(p["partes"])) or "—", _monto(-p["valor"], "CLP")]
             for p in pagos]
    return _vista(
        "ERP (BORDERO)",
        [("Período", _rango_texto(*periodo) if periodo else "—"),
         ("Pagos con tarjeta en dólares", _plural(len(pagos), "pago")),
         ("Total en pesos", _monto(-sum(p["valor"] for p in pagos), "CLP")),
         ("Por tarjeta", _conteo(Counter(marca(p) for p in pagos)))],
        ["Fecha", "Tarjeta", "Código", "Valor en pesos"], filas, "pagos", avisos,
        rango=periodo, rol="base", numericas=("Valor en pesos",),
        detalle=f"del {_rango_texto(*periodo)}" if periodo else "",
    )


def _corte_tarjeta(hojas):
    """Fecha de «Posición Por Clientes en 04/12/2025» del encabezado, o None."""
    for _, df in hojas:
        for i in range(min(len(df), 20)):
            for celda in df.iloc[i].tolist():
                texto = lectura.normalizar(celda)
                if texto.startswith("posicion por clientes"):
                    fecha = next((logica_clp._fecha(p) for p in texto.split() if logica_clp._fecha(p)), None)
                    if fecha:
                        return fecha
    return None


def _tarjeta(archivo, campo):
    lector = logica.LectorExcel()
    tabla = lector.leer(archivo, logica.COLS_TARJETA)
    documentos = []
    for _, fila in tabla.iterrows():
        if fila.get("_doc") is None or lectura.numero(fila["_doc"]) is None:
            continue
        usd, clp, _ = logica._montos_tarjeta(fila)
        usd, clp = lectura.numero(usd), lectura.numero(clp)
        fecha = logica_clp._fecha(fila["Unnamed: 1"])
        if fecha is None or (usd is None and clp is None):
            continue
        documentos.append({"fecha": fecha, "documento": logica._texto_codigo(fila["Unnamed: 2"]), "usd": usd, "clp": clp})
    corte = _corte_tarjeta(lector.hojas(archivo))
    avisos = [] if documentos else ["No trae documentos con monto: revisa que sea la posición por clientes de la tarjeta."]
    filas = [[_fecha(d["fecha"]), d["documento"], _monto(d["usd"], "USD"), _monto(d["clp"], "CLP")] for d in documentos]
    return _vista(
        f"Cartola {logica.NOMBRES_ARCHIVO[campo]}",
        [("Posición al", _fecha(corte) if corte else ""),
         ("Documentos", _plural(len(documentos), "documento")),
         ("Total en dólares", _monto(sum(d["usd"] or 0 for d in documentos), "USD")),
         ("Total en pesos", _monto(sum(d["clp"] or 0 for d in documentos), "CLP"))],
        ["Asiento", "Documento", "Dólares", "Pesos"], filas, "documentos", avisos,
        numericas=("Dólares", "Pesos"), detalle=f"posición al {_fecha(corte)}" if corte else "",
    )


def _banco_usd(archivo):
    hojas = lectura.leer_hojas(archivo)
    movimientos = []
    for _, df in hojas:
        for i in range(len(df)):
            textos = [lectura.normalizar(v) for v in df.iloc[i].tolist()]
            if "fecha" not in textos or not any("abono" in t for t in textos):
                continue
            c_fecha = textos.index("fecha")
            c_abono = next(j for j, t in enumerate(textos) if "abono" in t)
            c_desc = next((j for j, t in enumerate(textos) if t.startswith(("descripcion", "glosa", "detalle"))), None)
            for k in range(i + 1, len(df)):
                monto = lectura.numero(df.iat[k, c_abono])
                fecha = logica_clp._fecha(df.iat[k, c_fecha])
                if monto and fecha:
                    desc = logica_clp._texto(df.iat[k, c_desc]) if c_desc is not None else ""
                    movimientos.append({"fecha": fecha, "descripcion": desc, "monto": monto})
            break
        if movimientos:
            break
    avisos = []
    if not movimientos:
        avisos.append("No se encontraron abonos en la cartola.")
    elif not any("transbank" in lectura.normalizar(m["descripcion"]) for m in movimientos):
        avisos.append("Ningún abono dice «Transbank» en la descripción: puede que Transbank abone en otra cuenta. "
                      "El análisis igual buscará el monto del abono entre todos los movimientos.")
    rango = _rango(m["fecha"] for m in movimientos)
    filas = [[_fecha(m["fecha"]), m["descripcion"] or "—", _monto(m["monto"], "USD")] for m in movimientos]
    return _vista(
        "Cartola del banco (dólares)",
        [("Abonos", _plural(len(movimientos), "abono")),
         ("Entre el", _rango_texto(*rango) if rango else ""),
         ("Total abonado", _monto(sum(m["monto"] for m in movimientos), "USD") if movimientos else "")],
        ["Fecha", "Descripción", "Abono"], filas, "abonos", avisos, numericas=("Abono",),
        detalle=f"abonos del {_rango_texto(*rango)}" if rango else "",
    )


def _transbank_usd(archivo):
    lector = logica.LectorExcel()
    tabla, abonos = logica.leer_transbank(archivo, lector, identificar_local)
    ventas = []
    for _, fila in tabla.iterrows():
        codigo, monto = fila["Unnamed: 7"], lectura.numero(fila["Unnamed: 6"])
        if codigo is None or (isinstance(codigo, float) and codigo != codigo) or monto is None:
            continue
        marca = fila["Unnamed: 3"]
        ventas.append({
            "fecha": logica_clp._fecha(fila["Unnamed: 2"]),
            "marca": logica.MARCA_GRAFICO.get(marca, marca if isinstance(marca, str) and marca else "Sin identificar"),
            "codigo": logica._texto_codigo(codigo),
            "monto": monto,
        })
    avisos = []
    if not ventas:
        avisos.append("El reporte no trae ventas.")
    sin_marca = sum(1 for v in ventas if v["marca"] not in logica.MARCA_GRAFICO.values())
    if sin_marca:
        avisos.append(f"{_plural(sin_marca, 'venta')} sin marca reconocida: se buscarán en los pagos de todas las tarjetas.")
    rango = _rango(v["fecha"] for v in ventas)
    filas = [[_fecha(v["fecha"]), v["marca"], v["codigo"], _monto(v["monto"], "USD")] for v in ventas]
    return _vista(
        "Transbank",
        [("Ventas del", _rango_texto(*rango) if rango else "—"),
         ("Ventas", _plural(len(ventas), "venta")),
         ("Total ventas", _monto(sum(v["monto"] for v in ventas), "USD")),
         ("Abono", " + ".join(_monto(a, "USD") for a in abonos) if abonos else ""),
         ("Por marca", _conteo(Counter(v["marca"] for v in ventas)))],
        ["Fecha de venta", "Marca", "Autorización", "Monto"], filas, "ventas", avisos,
        rango=rango, rol="ventas", numericas=("Monto",),
        detalle=f"ventas del {_rango_texto(*rango)}" if rango else "",
    )


def de_dolares(archivo, campo):
    """Vista previa de un archivo de la conciliación en dólares ('archivo1' … 'archivo7')."""
    titulo = logica.NOMBRES_ARCHIVO.get(campo, "Archivo")
    try:
        if campo == "archivo1":
            return _erp(archivo)
        if campo in ("archivo2", "archivo3", "archivo4", "archivo5"):
            return _tarjeta(archivo, campo)
        if campo == "archivo6":
            return _banco_usd(archivo)
        if campo == "archivo7":
            return _transbank_usd(archivo)
    except Exception as exc:  # noqa: BLE001 - la vista previa es informativa: nunca impide la carga
        return _sin_lectura(titulo, exc)
    finally:
        archivo.seek(0)
    return None
