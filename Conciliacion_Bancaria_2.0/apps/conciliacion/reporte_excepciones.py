"""Reporte de excepciones (CU-05): PDF ejecutivo y Excel multilote.

Toma las excepciones ya filtradas (estado, tipo, moneda, fechas de venta o una conciliación) y arma:
- PDF: encabezado con el filtro, resumen por estado y por tipo, y el detalle con código, monto,
  estado y acción sugerida. Si no hay excepciones, lo dice: «Cuadratura 100 % limpia».
- Excel: hoja «Resumen» y hoja «Excepciones» con todas las columnas, filtros y totales; una fila
  por excepción de cualquier conciliación (de ahí «multilote»).
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from django.utils.timezone import localtime
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import excepciones as ex

AZUL = "0A2C4A"
DORADO = "C9A227"
HOTEL = "Hotel Plaza San Francisco"


@dataclass
class Datos:
    excepciones: list
    filtro: dict
    texto_estado: str
    conciliacion: object = None
    usuario: str = ""
    generado: datetime = field(default_factory=datetime.now)

    @property
    def multilote(self):
        return self.conciliacion is None


# ---------------------------------------------------------------------------
# Textos comunes
# ---------------------------------------------------------------------------
def _fecha(valor):
    return valor.strftime("%d-%m-%Y") if valor else ""


def _monto(valor, moneda):
    if valor is None:
        return "—"
    valor = float(valor)
    if moneda == "USD":
        texto = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{'-' if valor < 0 else ''}US$ {texto}"
    return f"{'-' if valor < 0 else ''}$ " + f"{round(abs(valor)):,.0f}".replace(",", ".")


def _periodo(c):
    if not c.hasta:
        return "sin período"
    if not c.desde or c.desde == c.hasta:
        return _fecha(c.hasta)
    return f"{_fecha(c.desde)} al {_fecha(c.hasta)}"


def descripcion_filtro(datos):
    """Líneas que explican qué incluye el reporte."""
    f = datos.filtro
    lineas = []
    if datos.conciliacion:
        c = datos.conciliacion
        lineas.append(f"Conciliación N° {c.pk} en {c.get_moneda_display().lower()} · período conciliado {_periodo(c)} · "
                      f"hecha el {localtime(c.creada).strftime('%d-%m-%Y %H:%M')}")
    else:
        moneda = {"CLP": "en pesos", "USD": "en dólares"}.get(f.get("moneda"), "en pesos y dólares")
        lineas.append(f"Todas las conciliaciones {moneda} (la última vez que se concilió cada venta)")
    partes = [f"Estado: {datos.texto_estado.lower()}"]
    if f.get("categoria"):
        partes.append(f"tipo: {ex.NOMBRE_CATEGORIA[f['categoria']].lower()}")
    if f.get("desde") or f.get("hasta"):
        if f.get("desde") and f.get("hasta"):
            partes.append(f"ventas del {_fecha(f['desde'])} al {_fecha(f['hasta'])}")
        elif f.get("desde"):
            partes.append(f"ventas desde el {_fecha(f['desde'])}")
        else:
            partes.append(f"ventas hasta el {_fecha(f['hasta'])}")
    lineas.append(" · ".join(partes))
    return lineas


def _estado_texto(e):
    if not e.vigente and e.reemplazada_por_id:
        return f"Se gestiona en la N° {e.reemplazada_por_id}"
    return e.get_estado_display()


def resumen(datos):
    """Cantidades por estado, por tipo y montos de Transbank por moneda."""
    lista = datos.excepciones
    por_estado = Counter(e.estado for e in lista if e.vigente or datos.conciliacion is None)
    tipos = defaultdict(lambda: {"cantidad": 0, "montos": defaultdict(float)})
    for e in lista:
        t = tipos[e.categoria]
        t["cantidad"] += 1
        if e.monto is not None:
            t["montos"][e.conciliacion.moneda] += float(e.monto)
    orden = [clave for clave, _ in ex.CATEGORIAS]
    por_tipo = [
        {"tipo": ex.NOMBRE_CATEGORIA[clave], "cantidad": tipos[clave]["cantidad"],
         "monto": " · ".join(_monto(v, m) for m, v in sorted(tipos[clave]["montos"].items()))}
        for clave in sorted(tipos, key=orden.index)
    ]
    return {
        "total": len(lista),
        "pendientes": por_estado.get("pendiente", 0),
        "en_revision": por_estado.get("en_revision", 0),
        "resueltas": por_estado.get("resuelta", 0),
        "por_tipo": por_tipo,
    }


# ---------------------------------------------------------------------------
# PDF ejecutivo
# ---------------------------------------------------------------------------
def pdf(datos):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    azul, dorado = colors.HexColor("#" + AZUL), colors.HexColor("#" + DORADO)
    gris, linea = colors.HexColor("#56636F"), colors.HexColor("#DBE1E7")
    fondo = colors.HexColor("#F1F5F9")
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#15212D"))
    chico = ParagraphStyle("chico", parent=base, fontSize=7.2, leading=9)
    derecha = ParagraphStyle("derecha", parent=chico, alignment=TA_RIGHT)
    titulo = ParagraphStyle("titulo", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=azul)
    subtitulo = ParagraphStyle("subtitulo", parent=base, fontSize=9, leading=12, textColor=gris)
    seccion = ParagraphStyle("seccion", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=14,
                             textColor=azul, spaceBefore=10, spaceAfter=5)
    cifra = ParagraphStyle("cifra", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=azul)

    def p(texto, estilo=chico):
        texto = str(texto or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(texto, estilo)

    pie_texto = f"{HOTEL} · Reporte de excepciones · generado el {datos.generado.strftime('%d-%m-%Y %H:%M')}"
    if datos.usuario:
        pie_texto += f" por {datos.usuario}"

    from .pdf_base import lienzo_con_pie

    ConPaginas = lienzo_con_pie(pie_texto)

    salida = BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.7 * cm, title="Reporte de excepciones",
                            author=HOTEL, subject="Conciliación bancaria")
    ancho = doc.width
    partes = [p("Reporte de excepciones", titulo)]
    for linea_filtro in descripcion_filtro(datos):
        partes.append(p(linea_filtro, subtitulo))
    partes.append(Spacer(1, 10))

    if not datos.excepciones:
        caja = Table([[p("Cuadratura 100 % limpia", ParagraphStyle("ok", parent=cifra, textColor=colors.HexColor("#0C4A38")))],
                      [p("No hay excepciones con este filtro: todas las ventas de Transbank quedaron conciliadas "
                         "o ya no quedan casos en este estado.", base)]],
                     colWidths=[ancho])
        caja.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E2F1EA")),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#9FD0B9")),
            ("LEFTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
        ]))
        partes.append(caja)
        doc.build(partes, canvasmaker=ConPaginas)
        return salida.getvalue()

    r = resumen(datos)
    tarjetas = [
        ("Excepciones", r["total"]), ("Pendientes", r["pendientes"]),
        ("En revisión", r["en_revision"]), ("Resueltas", r["resueltas"]),
    ]
    fila = [[p(str(valor), cifra), p(texto, subtitulo)] for texto, valor in tarjetas]
    resumen_tabla = Table([[Table([[a], [b]], colWidths=[ancho / 4 - 8]) for a, b in fila]], colWidths=[ancho / 4] * 4)
    resumen_tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fondo),
        ("LINEBEFORE", (1, 0), (-1, -1), 2, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    partes.append(resumen_tabla)

    partes.append(p("Por tipo de excepción", seccion))
    tipos = [[p("Tipo", ParagraphStyle("e", parent=chico, fontName="Helvetica-Bold")),
              p("Cantidad", ParagraphStyle("e2", parent=derecha, fontName="Helvetica-Bold")),
              p("Monto en Transbank", ParagraphStyle("e3", parent=derecha, fontName="Helvetica-Bold"))]]
    tipos += [[p(t["tipo"]), p(t["cantidad"], derecha), p(t["monto"], derecha)] for t in r["por_tipo"]]
    tabla_tipos = Table(tipos, colWidths=[ancho * 0.45, ancho * 0.15, ancho * 0.4], hAlign="LEFT")
    tabla_tipos.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6EEF6")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, linea),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    partes.append(tabla_tipos)

    partes.append(p("Detalle", seccion))
    encabezado = ["Fecha", "Medio", "Código", "Tipo", "Monto", "Diferencia", "Estado", "Acción sugerida", "Comentario"]
    anchos = [52, 56, 54, 92, 62, 56, 62, 0, 96]
    if datos.multilote:
        encabezado.insert(0, "N°")
        anchos.insert(0, 26)
    anchos[encabezado.index("Acción sugerida")] = ancho - sum(anchos)
    negrita = ParagraphStyle("enc", parent=chico, fontName="Helvetica-Bold", textColor=azul)
    negrita_derecha = ParagraphStyle("enc_d", parent=negrita, alignment=TA_RIGHT)
    filas = [[p(t, negrita_derecha if t in ("Monto", "Diferencia") else negrita) for t in encabezado]]
    for e in datos.excepciones:
        moneda = e.conciliacion.moneda
        celdas = [
            p(_fecha(e.fecha)), p(e.medio), p(e.codigo), p(e.get_categoria_display()),
            p(_monto(e.monto, moneda), derecha), p(_monto(e.diferencia, moneda) if e.diferencia else "—", derecha),
            p(_estado_texto(e)), p(e.sugerencia), p(e.comentario),
        ]
        if datos.multilote:
            celdas.insert(0, p(e.conciliacion_id))
        filas.append(celdas)
    detalle = LongTable(filas, colWidths=anchos, repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6EEF6")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, azul),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, linea),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(2, len(filas), 2):
        estilo.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC")))
    detalle.setStyle(TableStyle(estilo))
    partes.append(detalle)
    doc.build(partes, canvasmaker=ConPaginas)
    return salida.getvalue()


# ---------------------------------------------------------------------------
# Excel multilote
# ---------------------------------------------------------------------------
FUENTE = Font(name="Arial", size=10)
NEGRITA = Font(name="Arial", size=10, bold=True)
TITULO = Font(name="Arial", size=13, bold=True, color=AZUL)
GRIS = Font(name="Arial", size=9, color="56636F")
ENCABEZADO = PatternFill("solid", fgColor="E6EEF6")
FORMATO = {"CLP": '"$"#,##0;-"$"#,##0', "USD": '"US$"#,##0.00;-"US$"#,##0.00'}


def excel(datos):
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = "Reporte de excepciones"
    ws["A1"].font = TITULO
    fila = 2
    for linea in descripcion_filtro(datos) + [f"Generado el {datos.generado.strftime('%d-%m-%Y %H:%M')}"
                                              + (f" por {datos.usuario}" if datos.usuario else "")]:
        ws.cell(fila, 1, linea).font = GRIS
        fila += 1
    fila += 1
    if not datos.excepciones:
        ws.cell(fila, 1, "Cuadratura 100 % limpia: no hay excepciones con este filtro.").font = Font(
            name="Arial", size=11, bold=True, color="0C4A38")
    else:
        r = resumen(datos)
        for texto, valor in (("Excepciones", r["total"]), ("Pendientes", r["pendientes"]),
                             ("En revisión", r["en_revision"]), ("Resueltas", r["resueltas"])):
            ws.cell(fila, 1, texto).font = FUENTE
            ws.cell(fila, 2, valor).font = NEGRITA
            fila += 1
        fila += 1
        for col, texto in enumerate(("Tipo de excepción", "Cantidad", "Monto en Transbank"), 1):
            celda = ws.cell(fila, col, texto)
            celda.font, celda.fill = NEGRITA, ENCABEZADO
        for t in r["por_tipo"]:
            fila += 1
            ws.cell(fila, 1, t["tipo"]).font = FUENTE
            ws.cell(fila, 2, t["cantidad"]).font = FUENTE
            ws.cell(fila, 3, t["monto"]).font = FUENTE
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 30

    hoja = wb.create_sheet("Excepciones")
    columnas = [
        ("N° conciliación", 14), ("Moneda", 9), ("Período conciliado", 24), ("Fecha venta", 12), ("Medio / marca", 16),
        ("Código autorización", 18), ("Tipo de excepción", 30), ("Tipo automático", 30), ("Monto Transbank", 16),
        ("Monto BORDERO / cartola", 18), ("Diferencia", 13), ("Estado", 22), ("Acción sugerida", 80),
        ("Comentario", 40), ("Gestionada por", 20), ("Última gestión", 17), ("Observación del cruce", 40),
    ]
    for col, (texto, ancho_col) in enumerate(columnas, 1):
        celda = hoja.cell(1, col, texto)
        celda.font, celda.fill = NEGRITA, ENCABEZADO
        celda.alignment = Alignment(vertical="center", wrap_text=True)
        hoja.column_dimensions[get_column_letter(col)].width = ancho_col
    for i, e in enumerate(datos.excepciones, 2):
        c = e.conciliacion
        valores = [
            c.pk, c.moneda, _periodo(c), e.fecha, e.medio, e.codigo, e.get_categoria_display(),
            e.get_categoria_auto_display(), e.monto, e.monto_registro, e.diferencia, _estado_texto(e), e.sugerencia,
            e.comentario, (e.actualizada_por.get_full_name() or e.actualizada_por.get_username()) if e.actualizada_por else "",
            localtime(e.actualizada).replace(tzinfo=None) if e.actualizada else None, e.detalle,
        ]
        for col, valor in enumerate(valores, 1):
            celda = hoja.cell(i, col, float(valor) if col in (9, 10, 11) and valor is not None else valor)
            celda.font = FUENTE
            celda.alignment = Alignment(vertical="top", wrap_text=col in (13, 14, 17))
            if col in (9, 10, 11):
                celda.number_format = FORMATO[c.moneda]
            elif col == 4 and valor:
                celda.number_format = "DD-MM-YYYY"
            elif col == 16 and valor:
                celda.number_format = "DD-MM-YYYY HH:MM"
    hoja.freeze_panes = "A2"
    if datos.excepciones:
        hoja.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}{len(datos.excepciones) + 1}"
    else:
        hoja.cell(2, 1, "Cuadratura 100 % limpia: no hay excepciones con este filtro.").font = NEGRITA

    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()
