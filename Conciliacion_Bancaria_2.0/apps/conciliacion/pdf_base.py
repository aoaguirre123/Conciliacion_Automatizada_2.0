"""Piezas comunes de los PDF de la aplicación (reporte de excepciones y documentos de cada conciliación)."""
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as canvas_mod

AZUL = colors.HexColor("#0A2C4A")
DORADO = colors.HexColor("#C9A227")
GRIS = colors.HexColor("#56636F")
LINEA = colors.HexColor("#DBE1E7")
FONDO = colors.HexColor("#F1F5F9")
ENCABEZADO = colors.HexColor("#E6EEF6")
CEBRA = colors.HexColor("#F8FAFC")
TINTA = colors.HexColor("#15212D")
HOTEL = "Hotel Plaza San Francisco"


def escapar(texto):
    return str("" if texto is None else texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def lienzo_con_pie(pie_texto):
    """Clase de lienzo para doc.build(canvasmaker=...) con línea dorada, texto y «Página n de N»."""

    class ConPaginas(canvas_mod.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._paginas = []

        def showPage(self):
            self._paginas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas)
            for estado in self._paginas:
                self.__dict__.update(estado)
                ancho, _ = self._pagesize
                self.setStrokeColor(DORADO)
                self.setLineWidth(1.2)
                self.line(1.5 * cm, 1.25 * cm, ancho - 1.5 * cm, 1.25 * cm)
                self.setFont("Helvetica", 7.5)
                self.setFillColor(GRIS)
                self.drawString(1.5 * cm, 0.85 * cm, pie_texto)
                self.drawRightString(ancho - 1.5 * cm, 0.85 * cm, f"Página {self._pageNumber} de {total}")
                super().showPage()
            super().save()

    return ConPaginas
