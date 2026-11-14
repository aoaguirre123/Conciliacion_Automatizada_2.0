"""Documentos de una conciliación en PDF.

Los reportes de cada conciliación se guardan en Excel (Reporte.contenido). Este módulo los convierte
a PDF sin depender de Excel ni LibreOffice: lee cada hoja con openpyxl y la dibuja con reportlab.

- Las filas con un solo texto al inicio (títulos y subtítulos de la hoja) salen como encabezados.
- Las filas con varias celdas forman una tabla; la primera es el encabezado y se repite en cada página.
- Los montos usan el formato chileno ($ 1.234.567 / US$ 1.234,56) y las fechas dd-mm-aaaa.
- Las sumas de la hoja Resumen (=SUM(...)) se calculan, porque el archivo no guarda su resultado.
- Las hojas anchas usan una página A3 apaisada para que las columnas se lean.
"""
import re
from datetime import date, datetime
from io import BytesIO

from django.utils.timezone import localtime
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .pdf_base import AZUL, CEBRA, ENCABEZADO, GRIS, LINEA, TINTA, HOTEL, escapar, lienzo_con_pie

SUMA = re.compile(r"^=SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)$", re.IGNORECASE)
COLUMNAS_A3 = 12  # desde aquí la hoja va en A3 apaisada

# Encabezados técnicos de los Excel en dólares, con su nombre para leer.
NOMBRES = {
    "codigo_autorizacion": "Código autorización", "documento": "Documento ERP", "monto_original": "Monto Transbank",
    "monto_cartola": "Monto cartola", "diferencia": "Diferencia", "fecha_venta": "Fecha venta",
    "tipo_tarjeta": "Tarjeta", "status": "Estado", "observacion": "Observación", "nota": "Nota", "extra": "Ubicada",
}


def _encabezado(texto):
    texto = str(texto or "").strip()
    if texto in NOMBRES:
        return NOMBRES[texto]
    return texto[:1].upper() + texto[1:].replace("_", " ") if "_" in texto else texto


def _estilos(tamano):
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=tamano, leading=tamano * 1.25, textColor=TINTA)
    return {
        "celda": base,
        "numero": ParagraphStyle("numero", parent=base, alignment=TA_RIGHT),
        "encabezado": ParagraphStyle("encabezado", parent=base, fontName="Helvetica-Bold", textColor=AZUL),
        "encabezado_num": ParagraphStyle("encabezado_num", parent=base, fontName="Helvetica-Bold", textColor=AZUL,
                                         alignment=TA_RIGHT),
        "titulo_doc": ParagraphStyle("titulo_doc", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=AZUL),
        "titulo": ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=AZUL,
                                 spaceAfter=2),
        "texto": ParagraphStyle("texto", fontName="Helvetica", fontSize=8.5, leading=11, textColor=GRIS, spaceAfter=4),
    }


def _moneda_formato(formato, moneda):
    formato = formato or ""
    if "US$" in formato or ('"$"' in formato and moneda == "USD"):
        return "USD"
    if "$" in formato:
        return "USD" if moneda == "USD" else "CLP"
    return None


def _numero(valor, decimales):
    texto = f"{abs(valor):,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if valor < 0 else "") + texto


def _texto_celda(valor, formato, moneda):
    """(texto, es_numero)"""
    if valor is None:
        return "", False
    if isinstance(valor, datetime):
        return (valor.strftime("%d-%m-%Y %H:%M") if (valor.hour or valor.minute) else valor.strftime("%d-%m-%Y")), False
    if isinstance(valor, date):
        return valor.strftime("%d-%m-%Y"), False
    if isinstance(valor, bool):
        return "Sí" if valor else "No", False
    if isinstance(valor, (int, float)):
        tipo = _moneda_formato(formato, moneda)
        if tipo == "USD":
            return f"US$ {_numero(valor, 2)}", True
        if tipo == "CLP":
            return f"$ {_numero(round(valor), 0)}", True
        if isinstance(valor, float) and not valor.is_integer():
            return _numero(valor, 2), True
        # Con formato de miles se separa; si no (códigos, documentos, cantidades), tal cual.
        return (_numero(valor, 0) if "#,##0" in (formato or "") else str(int(valor))), True
    return str(valor).strip(), False


def _evaluar_sumas(ws):
    """Reemplaza =SUM(K5:K40) por su resultado (el Excel se calcula al abrirlo, no trae el valor)."""
    for fila in ws.iter_rows():
        for celda in fila:
            m = SUMA.match(str(celda.value or ""))
            if m:
                col, desde, _, hasta = m.groups()
                total = 0.0
                for r in range(int(desde), int(hasta) + 1):
                    v = ws[f"{col}{r}"].value
                    if isinstance(v, (int, float)):
                        total += v
                celda.value = total


def _bloques(ws, moneda):
    """Divide la hoja en títulos y tablas. Devuelve [("titulo"|"texto"|"tabla", contenido)]."""
    _evaluar_sumas(ws)
    filas = []
    for fila in ws.iter_rows():
        celdas = [(c.value, c.number_format) for c in fila]
        while celdas and celdas[-1][0] in (None, ""):
            celdas.pop()
        filas.append(celdas)

    bloques, tabla = [], []
    anchos_excel = [ws.column_dimensions[get_column_letter(j)].width or 0 for j in range(1, ws.max_column + 1)]
    for celdas in filas + [[]]:
        llenas = [v for v, _ in celdas if v not in (None, "")]
        es_texto = len(llenas) == 1 and celdas and celdas[0][0] not in (None, "") and isinstance(celdas[0][0], str) \
            and (not tabla or len(celdas) == 1)
        if not llenas or es_texto:
            if tabla:
                bloques.append(("tabla", (tabla, anchos_excel)))
                tabla = []
            if es_texto:
                bloques.append(("titulo" if not bloques else "texto", celdas[0][0]))
            continue
        tabla.append([_texto_celda(v, f, moneda) for v, f in celdas])
    return bloques


def _tabla(contenido, ancho, estilos):
    filas, anchos_excel = contenido
    columnas = max(len(f) for f in filas)
    filas = [f + [("", False)] * (columnas - len(f)) for f in filas]
    # Quitar columnas vacías.
    usadas = [j for j in range(columnas) if any(f[j][0] for f in filas)]
    filas = [[f[j] for j in usadas] for f in filas]
    filas[0] = [(_encabezado(t), n) for t, n in filas[0]]
    numericas = [all(f[k][1] or not f[k][0] for f in filas[1:]) and any(f[k][1] for f in filas[1:])
                 for k in range(len(usadas))]

    # Ancho: el que trae la columna en el Excel (pensado para su contenido) o, si no tiene, según el texto.
    tamano = estilos["celda"].fontSize
    por_caracter = tamano * 0.52
    base = []
    for k, j in enumerate(usadas):
        excel = anchos_excel[j] if j < len(anchos_excel) else 0
        if not excel or excel == 13:  # 13 = ancho por defecto de openpyxl (columna sin ancho definido)
            excel = min(max(max((len(f[k][0]) for f in filas), default=6), 6), 40)
        base.append(excel)
    anchos = [b * por_caracter for b in base]
    # Los números y fechas no se cortan: su columna tiene al menos el ancho de su texto más largo.
    for k in range(len(usadas)):
        if numericas[k] or all(len(f[k][0]) <= 12 for f in filas[1:]):
            largo = max((len(f[k][0]) for f in filas[1:]), default=0)
            palabra = max((len(p) for p in filas[0][k][0].split()), default=0)  # que el título no corte palabras
            anchos[k] = max(anchos[k], (max(largo, palabra) + 1.5) * por_caracter)
    # Ajustar al ancho de la página: se achican o agrandan solo las columnas de texto.
    fijas = [k for k in range(len(usadas)) if numericas[k] or all(len(f[k][0]) <= 12 for f in filas[1:])]
    libres = [k for k in range(len(usadas)) if k not in fijas] or list(range(len(usadas)))
    sobra = ancho - sum(anchos)
    total_libres = sum(anchos[k] for k in libres) or 1
    for k in libres:
        anchos[k] = max(anchos[k] + sobra * anchos[k] / total_libres, 4 * por_caracter)
    escala = ancho / sum(anchos)
    if escala < 1:
        anchos = [a * escala for a in anchos]

    datos = [[Paragraph(escapar(t), estilos["encabezado_num"] if numericas[k] else estilos["encabezado"])
              for k, (t, _) in enumerate(filas[0])]]
    for f in filas[1:]:
        datos.append([Paragraph(escapar(t), estilos["numero"] if numericas[k] else estilos["celda"])
                      for k, (t, _) in enumerate(f)])
    tabla = LongTable(datos, colWidths=anchos, repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), ENCABEZADO),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, AZUL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(2, len(datos), 2):
        estilo.append(("BACKGROUND", (0, i), (-1, i), CEBRA))
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _hojas(contenido):
    libro = load_workbook(BytesIO(bytes(contenido)))
    return [ws for ws in libro.worksheets if ws.max_row > 1 or ws["A1"].value]


def _ancho_maximo(hojas):
    return max((ws.max_column for ws in hojas), default=1)


def _portada(conciliacion, estilos):
    """Primera página del PDF con todos los documentos: datos de la conciliación y su resultado."""
    c = conciliacion
    partes = [Paragraph(f"Conciliación en {escapar(c.get_moneda_display().lower())} N° {c.pk}", estilos["titulo_doc"])]
    periodo = "sin período"
    if c.hasta:
        periodo = c.hasta.strftime("%d-%m-%Y") if not c.desde or c.desde == c.hasta else \
            f"{c.desde.strftime('%d-%m-%Y')} al {c.hasta.strftime('%d-%m-%Y')}"
    usuario = (c.usuario.get_full_name() or c.usuario.get_username()) if c.usuario else "—"
    simbolo = c.simbolo
    por_revisar = _numero(float(c.monto_por_revisar), 2 if c.moneda == "USD" else 0)
    filas = [
        ["Período conciliado", periodo],
        ["Fecha de la conciliación", localtime(c.creada).strftime("%d-%m-%Y %H:%M")],
        ["Hecha por", usuario],
        ["Resultado", "Cuadrado" if c.cuadrado else f"Por revisar: {simbolo} {por_revisar}"],
    ]
    parametros = (c.resultado or {}).get("parametros")
    if parametros:
        if c.moneda == "CLP":
            criterio = (f"tolerancia de $ {_numero(parametros['tolerancia_clp'], 0)} · fechas a "
                        f"{parametros['ventana_dias']} días como máximo · palabras clave de la cartola: "
                        f"{', '.join(parametros['palabras_cartola'])}")
        else:
            criterio = (f"tolerancia de US$ {_numero(parametros['tolerancia_usd'], 2)} · fechas a "
                        f"{parametros['ventana_dias']} días como máximo")
        filas.append(["Criterios usados", criterio])
    for a in c.archivos or []:
        filas.append([a.get("etiqueta", "Archivo"), a.get("nombre", "")])
    tabla = Table([[Paragraph(escapar(a), estilos["encabezado"]), Paragraph(escapar(b), estilos["celda"])] for a, b in filas],
                  colWidths=[6 * cm, 18 * cm], hAlign="LEFT")
    tabla.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINEA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    partes += [Spacer(1, 10), tabla]
    return partes


def generar(conciliacion, reportes, usuario=""):
    """PDF con los documentos dados (uno o todos). Si son todos, lleva una portada con el resumen."""
    todos = len(reportes) > 1
    hojas_por_reporte = [(r, _hojas(r.contenido)) for r in reportes]
    ancho_max = max((_ancho_maximo(h) for _, h in hojas_por_reporte), default=1)
    pagina = landscape(A3 if ancho_max >= COLUMNAS_A3 else A4)
    tamano = 7.5 if pagina == landscape(A4) else 7.2

    salida = BytesIO()
    titulo = "Documentos de la conciliación" if todos else reportes[0].titulo
    doc = SimpleDocTemplate(salida, pagesize=pagina, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.7 * cm,
                            title=f"{titulo} N° {conciliacion.pk}", author=HOTEL, subject="Conciliación bancaria")
    estilos = _estilos(tamano)
    pie = (f"{HOTEL} · Conciliación en {conciliacion.get_moneda_display().lower()} N° {conciliacion.pk} · "
           f"generado el {localtime().strftime('%d-%m-%Y %H:%M')}" + (f" por {usuario}" if usuario else ""))

    partes = _portada(conciliacion, estilos) if todos else []
    for i, (reporte, hojas) in enumerate(hojas_por_reporte):
        if todos or i:
            partes.append(PageBreak())
        if not todos:
            partes.append(Paragraph(f"{escapar(reporte.titulo)} · conciliación N° {conciliacion.pk}", estilos["titulo_doc"]))
            partes.append(Paragraph(escapar(reporte.descripcion), estilos["texto"]))
            partes.append(Spacer(1, 6))
        else:
            partes.append(Paragraph(escapar(reporte.titulo), estilos["titulo_doc"]))
            partes.append(Paragraph(escapar(reporte.descripcion), estilos["texto"]))
        for j, ws in enumerate(hojas):
            bloques = _bloques(ws, conciliacion.moneda)
            if len(hojas) > 1 and not any(t == "titulo" for t, _ in bloques):
                partes.append(Paragraph(escapar(ws.title), estilos["titulo"]))
            for tipo, contenido in bloques:
                if tipo == "tabla":
                    partes.append(_tabla(contenido, doc.width, estilos))
                    partes.append(Spacer(1, 10))
                else:
                    partes.append(Paragraph(escapar(contenido), estilos["titulo" if tipo == "titulo" else "texto"]))
            if not bloques:
                partes.append(Paragraph("Sin datos.", estilos["texto"]))
    doc.build(partes, canvasmaker=lienzo_con_pie(pie))
    return salida.getvalue()
