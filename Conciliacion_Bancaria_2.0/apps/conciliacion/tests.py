"""Pruebas de lectura de archivos, motor en dólares, cartolas en pesos y formato chileno.

Usan archivos sintéticos generados en memoria (el repositorio es público: no se
incluyen datos reales del hotel). Ejecutar con:

    python manage.py test apps.conciliacion
"""
import io
import struct
from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import translation
from openpyxl import Workbook, load_workbook

from . import lectura, logica, logica_clp


# ---------------------------------------------------------------------------
# Generadores de archivos de prueba
# ---------------------------------------------------------------------------
def xlsx(nombre, hojas):
    """hojas: {nombre_hoja: [fila, fila, ...]} -> archivo subido .xlsx"""
    wb = Workbook()
    wb.remove(wb.active)
    for titulo, filas in hojas.items():
        ws = wb.create_sheet(titulo)
        for fila in filas:
            ws.append(list(fila))
    salida = io.BytesIO()
    wb.save(salida)
    return SimpleUploadedFile(nombre, salida.getvalue())


def texto(nombre, contenido, codificacion="utf-8"):
    return SimpleUploadedFile(nombre, contenido.encode(codificacion))


def fila(ancho, **valores):
    """Fila con `ancho` columnas; valores por posición: fila(11, c3=5001, c8=-100)."""
    datos = [None] * ancho
    datos[0] = "x"
    for clave, valor in valores.items():
        datos[int(clave[1:])] = valor
    return datos


def archivos_usd(formato_tarjeta="xlsx", titulo_en_primera_fila=False):
    """ERP, Transbank, Mastercard y banco mínimos para una venta MC de US$ 100 que cuadra."""
    primera = [["REPORTE ERP", None, None, "Documento"] + [None] * 7] if titulo_en_primera_fila else [[None] * 11]
    erp = xlsx("erp.xlsx", {"ERP": primera + [
        fila(11, c3=5001, c5="Pago Master Card US$", c8=-100, c9="AUTH123", c10="01-09-2026"),
        fila(11, c3=5002, c5="Pago Master Card US$", c8=-50, c9="AUTH999", c10="02-09-2026"),
    ]})
    tbk = xlsx("tbk.xlsx", {"TBK": [[None] * 11,
        fila(11, c1="detalle", c2="01-09-2026", c3="MC", c6=100.0, c7="AUTH123"),
        fila(11, c1="Abono Calculado (=):", c2=100.0),
    ]})
    filas_mc = [[None] * 15, fila(15, c2=5001, c12=100.0, c13=100.0)]
    if formato_tarjeta == "csv":
        lineas = [";".join("" if v is None else str(v).replace(".", ",") for v in f) for f in filas_mc]
        mastercard = texto("mastercard.csv", "\n".join(lineas))
    elif formato_tarjeta == "html":
        celdas = "".join(
            "<tr>" + "".join(f"<td>{'' if v is None else v}</td>" for v in f) + "</tr>" for f in filas_mc
        )
        mastercard = texto("mastercard.xls", f"<html><body><table>{celdas}</table></body></html>")
    else:
        mastercard = xlsx("mastercard.xlsx", {"MC": filas_mc})
    banco = xlsx("banco.xlsx", {"Hoja1": [
        [None, "Fecha", None, "Descripción", None, "Canal o Sucursal", "Nro. Docto.", "Cargos (USD)", "Abonos (USD)", "Saldo (USD)"],
        [None, "01/09/2026", None, "Abono Transbank", None, "Oficina Central", None, None, 100, 1000],
    ]})
    return {"archivo1": erp, "archivo2": None, "archivo3": None, "archivo4": None,
            "archivo5": mastercard, "archivo6": banco, "archivo7": tbk}


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
class LecturaTests(SimpleTestCase):
    def test_detecta_formato_por_contenido(self):
        self.assertEqual(lectura.detectar_formato(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1resto"), "xls")
        self.assertEqual(lectura.detectar_formato(b"PK\x03\x04resto"), "xlsx")
        self.assertEqual(lectura.detectar_formato(b"\xef\xbb\xbf<html><table>"), "html")
        self.assertEqual(lectura.detectar_formato(b"Fecha;Monto\n01-09-2026;100"), "texto")

    def test_detecta_xls_antiguo_sin_contenedor_ole2(self):
        # El FrontOffice exporta el BORDERO como Excel 4.0 (BIFF4): empieza con el registro BOF 0x0409.
        for firma in (b"\x09\x00", b"\x09\x02", b"\x09\x04", b"\x09\x08"):
            self.assertEqual(lectura.detectar_formato(firma + b"\x06\x00\x00\x00\x10\x00"), "xls")

    def test_lee_todas_las_hojas(self):
        archivo = xlsx("cartola.xlsx", {"Resumen": [["Saldo", 1]], "Movimientos": [["Fecha", "Monto"]]})
        self.assertEqual([h for h, _ in lectura.leer_hojas(archivo)], ["Resumen", "Movimientos"])

    def test_csv_con_punto_y_coma_y_latin1(self):
        archivo = texto("datos.csv", "Fecha;Descripción;Monto\n01-09-2026;Depósito;1.234", "latin-1")
        df = lectura.primera_hoja(archivo)
        self.assertEqual(df.iat[1, 1], "Depósito")
        self.assertEqual(lectura.numero(df.iat[1, 2]), 1234)

    def test_archivo_vacio_da_error_claro(self):
        with self.assertRaises(lectura.FormatoNoSoportado):
            lectura.leer_hojas(SimpleUploadedFile("vacio.xlsx", b""))

    def test_numero(self):
        casos = {
            1234: 1234, "1.234": 1234, "1.234.567": 1234567, "$ 1.234.567": 1234567,
            "1.234,56": 1234.56, "1,234.56": 1234.56, "100,5": 100.5, "0.125": 0.125,
            "(500)": -500, "-": None, "": None, None: None, "N/A": None, "US$ 25,90": 25.9,
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(lectura.numero(entrada), esperado)

    def test_tabla_posicional_tolera_columnas_faltantes(self):
        import pandas as pd
        tabla = lectura.tabla_posicional(pd.DataFrame([[None, None], ["a", 1]]), [1, 5])
        self.assertEqual(list(tabla.columns), ["Unnamed: 1", "Unnamed: 5"])
        self.assertEqual(tabla.iat[0, 0], 1)


# ---------------------------------------------------------------------------
# Motor en dólares con distintos formatos
# ---------------------------------------------------------------------------
class MotorDolaresTests(SimpleTestCase):
    def procesar(self, **kwargs):
        resultado, reportes = logica.procesar(archivos_usd(**kwargs))
        return resultado, reportes

    def verificar_cuadra(self, resultado):
        self.assertEqual(resultado["resumen"]["ubicadas"], 1)
        self.assertTrue(resultado["resumen"]["cuadrado"])
        self.assertEqual(resultado["ws"], 1, "debió encontrar el abono de US$ 100 en el banco")
        self.assertEqual(resultado["data_dolar"][2]["ventas_tbk"], 100.0)

    def test_cartola_de_tarjeta_xlsx(self):
        # Antes fallaba con "Excel xlsx file; not supported" (engine="xlrd" fijo).
        self.verificar_cuadra(self.procesar(formato_tarjeta="xlsx")[0])

    def test_cartola_de_tarjeta_csv(self):
        self.verificar_cuadra(self.procesar(formato_tarjeta="csv")[0])

    def test_cartola_de_tarjeta_html_disfrazada_de_xls(self):
        try:
            import lxml  # noqa: F401
        except ImportError:
            self.skipTest("lxml no está instalado")
        self.verificar_cuadra(self.procesar(formato_tarjeta="html")[0])

    def test_texto_en_la_primera_fila_no_cambia_las_columnas(self):
        # Antes un título en la fila 1 renombraba las columnas y fallaba con KeyError.
        self.verificar_cuadra(self.procesar(titulo_en_primera_fila=True)[0])

    def test_reporte_abonos_por_dia_en_dolares(self):
        # Formato nuevo del portal: todos los medios en un archivo; la marca sale del BIN.
        archivos = archivos_usd()
        archivos["archivo7"] = transbank("abonos.xlsx", [
            ("Crédito", 100.0, 0.0, "AUTH123", "1", "5172 34** **** 1480"),
        ], moneda="Dólares")
        resultado = logica.procesar(archivos)[0]
        self.verificar_cuadra(resultado)
        self.assertEqual(resultado["abono_calculado"], 100.0)

    def test_codigo_con_cero_a_la_izquierda(self):
        archivos = archivos_usd()
        archivos["archivo1"] = xlsx("erp.xlsx", {"ERP": [[None] * 11,
            fila(11, c3=5001, c5="Pago Master Card US$", c8=-100, c9="88459", c10="01-09-2026")]})
        archivos["archivo7"] = transbank("abonos.xlsx", [
            ("Crédito", 100.0, 0.0, "088459", "1", "5172 34** **** 1480"),
        ], moneda="Dólares")
        self.verificar_cuadra(logica.procesar(archivos)[0])

    def test_reporte_en_pesos_se_rechaza_en_dolares(self):
        archivos = archivos_usd()
        archivos["archivo7"] = transbank("abonos.xlsx", VENTAS_MIXTAS, moneda="Pesos")
        with self.assertRaisesRegex(logica.ArchivoNoValido, "pesos"):
            logica.procesar(archivos)

    def test_genera_los_tres_excel(self):
        _, reportes = self.procesar()
        self.assertEqual([r[0] for r in reportes], ["ubicadas", "no_ubicadas", "erp_sin_respaldo"])
        for clave, *_, contenido in reportes:
            self.assertTrue(contenido.startswith(b"PK"), clave)


class MontosCorridosTests(SimpleTestCase):
    """En la posición por cliente los montos chicos vienen una columna a la derecha."""

    def procesar(self, fila_tarjeta, pesos=-2941, dolares=2.99):
        archivos = archivos_usd()
        archivos["archivo1"] = xlsx("erp.xlsx", {"ERP": [[None] * 11,
            fila(11, c3=5001, c5="Pago Master Card US$", c8=pesos, c9="AUTH123", c10="01-09-2026")]})
        archivos["archivo7"] = xlsx("tbk.xlsx", {"TBK": [[None] * 11,
            fila(11, c1="detalle", c2="01-09-2026", c3="MC", c6=dolares, c7="AUTH123"),
            fila(11, c1="Abono Calculado (=):", c2=dolares)]})
        archivos["archivo5"] = xlsx("mastercard.xlsx", {"MC": [[None] * 15, fila_tarjeta]})
        resultado = logica.procesar(archivos)[0]
        return resultado, resultado["data_dolar"][2]

    def test_dolares_en_saldo_y_pesos_en_saldo_corregido(self):
        resultado, mastercard = self.procesar(fila(15, c2=5001, c13=2.99, c14=2941))
        self.assertEqual(mastercard["ventas_tbk"], 2.99)
        self.assertEqual(resultado["resumen"]["ubicadas"], 1)
        self.assertTrue(resultado["resumen"]["cuadrado"])

    def test_dolares_distintos_en_fila_corrida_dejan_diferencia(self):
        resultado, mastercard = self.procesar(fila(15, c2=5001, c13=2.5, c14=2941))
        self.assertEqual(mastercard["ventas_cm"], 2.5)
        self.assertEqual(resultado["resumen"]["diferencia_total"], 0.49)
        self.assertFalse(resultado["resumen"]["cuadrado"])

    def test_pesos_corridos_con_dolares_en_su_columna(self):
        resultado, mastercard = self.procesar(fila(15, c2=5001, c12=2.99, c14=2941))
        self.assertEqual(mastercard["ventas_tbk"], 2.99)
        self.assertTrue(resultado["resumen"]["cuadrado"])

    def test_fila_normal_no_cambia(self):
        fila_normal = {"Unnamed: 12": 137.04, "Unnamed: 13": 133612, "Unnamed: 14": None}
        self.assertEqual(logica._montos_tarjeta(fila_normal), (137.04, 133612, None))

    def test_solo_saldo_no_se_considera_corrida(self):
        fila_saldo = {"Unnamed: 12": None, "Unnamed: 13": 133612, "Unnamed: 14": None}
        self.assertEqual(logica._montos_tarjeta(fila_saldo), (None, 133612, None))


class CruceDolaresTests(SimpleTestCase):
    """Cómo se vincula cada venta de Transbank con su pago del ERP."""

    def pago(self, cuenta, codigo, valor=-1000, fecha="10-09-2026", tarjeta="Master Card US$"):
        return fila(11, c3=cuenta, c5=f"Pago {tarjeta}", c8=valor, c9=codigo, c10=fecha)

    def venta(self, codigo, monto=100.0, fecha="10-09-2026", tipo="MC"):
        return fila(11, c1="detalle", c2=fecha, c3=tipo, c6=monto, c7=codigo)

    def posicion(self, cuenta, dolares=100.0, pesos=1000):
        return fila(15, c2=cuenta, c12=dolares, c13=pesos)

    def procesar(self, pagos, ventas, posiciones, visa=None):
        archivos = archivos_usd()
        archivos["archivo1"] = xlsx("erp.xlsx", {"ERP": [[None] * 11, *pagos]})
        archivos["archivo7"] = xlsx("tbk.xlsx", {"TBK": [[None] * 11, *ventas]})
        archivos["archivo5"] = xlsx("mc.xlsx", {"MC": [[None] * 15, *posiciones]})
        if visa:
            archivos["archivo4"] = xlsx("visa.xlsx", {"Visa": [[None] * 15, *visa]})
        return logica.procesar(archivos)

    def registros(self, *args, **kwargs):
        resumen = self.procesar(*args, **kwargs)[0]["resumen"]
        return resumen, list(logica.informacion_proceso)

    def test_entre_codigos_repetidos_toma_el_de_la_fecha_de_la_venta(self):
        resumen, [reg] = self.registros(
            [self.pago(1, "777", -5000, "10-06-2026"), self.pago(2, "777", -1000, "10-09-2026")],
            [self.venta("777")], [self.posicion(1, 500.0, 5000), self.posicion(2)])
        self.assertEqual(reg["documento"], 2)
        self.assertEqual(reg["monto_cartola"], 100.0)
        self.assertTrue(resumen["cuadrado"])

    def test_el_mismo_dia_toma_el_de_monto_mas_cercano(self):
        _, [reg] = self.registros(
            [self.pago(1, "777", -5000), self.pago(2, "777", -1000)],
            [self.venta("777")], [self.posicion(1, 500.0, 5000), self.posicion(2)])
        self.assertEqual(reg["documento"], 2)

    def test_codigo_en_otra_fecha_y_otro_monto_no_vincula(self):
        resumen, [reg] = self.registros(
            [self.pago(1, "777", -5000, "10-06-2026"), self.pago(9, "111", -1000)],
            [self.venta("777", fecha="10-09-2026")], [self.posicion(1, 500.0, 5000)])
        self.assertEqual(reg["extra"], "NO")
        self.assertIn("otra fecha", reg["nota"])
        self.assertEqual(resumen["por_revisar"], 100.0)

    def test_parte_de_un_numero_no_es_el_codigo(self):
        resumen, _ = self.registros([self.pago(1, "135870")], [self.venta("3587")], [self.posicion(1, 999.0)])
        self.assertEqual((resumen["ubicadas"], resumen["no_ubicadas"]), (0, 1))

    def test_codigo_dentro_de_un_texto_con_varias_partes(self):
        _, [reg] = self.registros([self.pago(1, "00 DUAL 00819067")], [self.venta("819067")], [self.posicion(1)])
        self.assertEqual(reg["documento"], 1)

    def test_codigo_digitado_distinto(self):
        _, [reg] = self.registros([self.pago(1, "09H8E08")], [self.venta("9H8EO8")], [self.posicion(1)])
        self.assertEqual(reg["documento"], 1)
        self.assertIn("digitado", reg["nota"])

    def test_cada_pago_se_usa_una_sola_vez(self):
        resumen, _ = self.registros([self.pago(1, "777")], [self.venta("777"), self.venta("777")], [self.posicion(1)])
        self.assertEqual((resumen["ubicadas"], resumen["no_ubicadas"]), (1, 1))

    def test_pago_de_otra_tarjeta_no_vincula(self):
        resumen, [reg] = self.registros(
            [self.pago(1, "777", tarjeta="Visa US$")], [self.venta("777", tipo="MC")],
            [self.posicion(99)], visa=[self.posicion(1)])
        self.assertEqual(resumen["ubicadas"], 0)
        self.assertIn("otra tarjeta", reg["nota"])

    def test_otro_codigo_con_mismo_monto_y_fecha_se_marca_para_revisar(self):
        resumen, [reg] = self.registros([self.pago(1, "555")], [self.venta("777")], [self.posicion(1)])
        self.assertEqual(reg["documento"], 1)
        self.assertIn("revisar", reg["nota"])
        self.assertEqual(resumen["con_nota"], 1)

    def test_su_propio_codigo_con_otro_monto_gana_a_otro_codigo_con_el_mismo_monto(self):
        _, [reg] = self.registros(
            [self.pago(1, "555"), self.pago(2, "777", -2000)], [self.venta("777")],
            [self.posicion(1), self.posicion(2, 100.40, 2000)])
        self.assertEqual(reg["documento"], 2)
        self.assertEqual(reg["estado"], "diferencia")

    def test_reversa_y_pago_dividido_en_dos_documentos(self):
        # Caso real: US$ 364,50 pagados en 243 + 121,50, con una reversa del primero.
        resumen, [reg] = self.registros(
            [self.pago(1, "503Z", 2000), self.pago(1, "503Z", -2000), self.pago(2, "503Z", -1000), self.pago(1, "503Z", -2000)],
            [self.venta("00503Z", 364.5)], [self.posicion(1, 243.0, 2000), self.posicion(2, 121.5, 1000)])
        self.assertEqual(reg["documento"], "2 + 1")
        self.assertEqual(reg["monto_cartola"], 364.5)
        self.assertIn("dividido", reg["nota"])
        self.assertTrue(resumen["cuadrado"])

    def test_redondeo_hasta_diez_centavos_inclusive(self):
        resumen, [reg] = self.registros([self.pago(1, "777")], [self.venta("777", 100.0)], [self.posicion(1, 100.10)])
        self.assertEqual(reg["estado"], "redondeo")
        self.assertIn("redondeo", reg["nota"])
        self.assertEqual((resumen["redondeo"], resumen["diferencias"], resumen["por_revisar"]), (1, 0, 0))
        self.assertTrue(resumen["cuadrado"])
        self.assertEqual(resumen["diferencia_total"], -0.1)

    def test_sobre_diez_centavos_es_diferencia_de_monto(self):
        resumen, [reg] = self.registros([self.pago(1, "777")], [self.venta("777", 100.0)], [self.posicion(1, 100.11)])
        self.assertEqual(reg["estado"], "diferencia")
        self.assertEqual((resumen["redondeo"], resumen["diferencias"], resumen["por_revisar"]), (0, 1, 0.11))
        self.assertFalse(resumen["cuadrado"])

    def test_varias_diferencias_de_redondeo_no_descuadran(self):
        resumen, _ = self.registros(
            [self.pago(1, "777"), self.pago(2, "888")], [self.venta("777"), self.venta("888")],
            [self.posicion(1, 100.10), self.posicion(2, 100.09)])
        self.assertEqual(resumen["redondeo"], 2)
        self.assertTrue(resumen["cuadrado"])

    def test_columnas_y_signo_coinciden_con_el_excel(self):
        resultado, reportes = self.procesar([self.pago(1, "777")], [self.venta("777", 100.0)], [self.posicion(1, 99.5)])
        mastercard = resultado["data_dolar"][2]
        self.assertEqual((mastercard["ventas_cm"], mastercard["ventas_tbk"], mastercard["diferencia"]), (99.5, 100.0, 0.5))
        self.assertEqual(logica.informacion_proceso[0]["diferencia"], 0.5)
        hoja = load_workbook(io.BytesIO(reportes[0][-1])).active
        encabezados = [c.value for c in hoja[2]]
        self.assertIn("monto_cartola", encabezados)
        self.assertEqual(hoja.cell(row=3, column=encabezados.index("diferencia") + 1).value, 0.5)

    def test_venta_sin_marca_toma_la_marca_del_pago(self):
        resultado, _ = self.procesar([self.pago(1, "777")], [self.venta("777", tipo="Sin identificar")], [self.posicion(1)])
        self.assertEqual(resultado["resumen"]["ubicadas"], 1)
        self.assertEqual(resultado["resumen"]["sin_marca"], 1)
        self.assertEqual(resultado["data_dolar"][2]["ventas_tbk"], 100.0)
        self.assertIn("ERP", logica.informacion_proceso[0]["nota"])

    def test_venta_sin_marca_ni_registro_queda_a_la_vista(self):
        resumen, [reg] = self.registros([self.pago(1, "111")], [self.venta("777", 50.0, tipo="Sin identificar")], [self.posicion(1)])
        self.assertEqual((resumen["no_ubicadas"], resumen["sin_marca"], resumen["por_revisar"]), (1, 1, 50.0))
        self.assertIn("no identificada", reg["nota"])

    def test_encabezados_del_reporte_no_son_ventas(self):
        resumen, _ = self.registros(
            [self.pago(1, "777")],
            [fila(11, c1="Tipo Transacción", c2="Fecha Venta", c3="Tipo Tarjeta", c6="Monto Original Venta", c7="Código Autorización Venta"),
             self.venta("777")], [self.posicion(1)])
        self.assertEqual((resumen["ubicadas"], resumen["no_ubicadas"]), (1, 0))

    def test_venta_fuera_del_periodo_no_suma_a_por_revisar(self):
        resumen, [reg] = self.registros([self.pago(1, "111")], [self.venta("777", fecha="10-01-2026")], [self.posicion(1, 1.0)])
        self.assertEqual(reg["estado"], "fuera_periodo")
        self.assertEqual((resumen["fuera_periodo"], resumen["por_revisar"]), (1, 0))

    def test_erp_contra_cartola_incluye_las_cuatro_tarjetas(self):
        archivos = archivos_usd()
        tarjetas = {"archivo2": "Amex US$", "archivo3": "Dinners US$", "archivo4": "Visa US$", "archivo5": "Master Card US$"}
        pagos = []
        for n, (campo, nombre) in enumerate(tarjetas.items(), start=1):
            pagos += [self.pago(n, f"{n}11", -1000 * n, tarjeta=nombre), self.pago(90 + n, f"{n}22", -77, tarjeta=nombre)]
            archivos[campo] = xlsx(f"{campo}.xlsx", {"Hoja": [[None] * 15, self.posicion(n, 10.0, 1000 * n)]})
        archivos["archivo1"] = xlsx("erp.xlsx", {"ERP": [[None] * 11, *pagos]})
        resultado = logica.procesar(archivos)[0]
        ventas_cm = {f["cuenta"]: f["ventas_cm"] for f in resultado["data"]}
        self.assertEqual(ventas_cm, {"Amex US$": 1000, "Dinners US$": 2000, "Visa US$": 3000, "Master Card US$": 4000, "Total": 10000})
        self.assertEqual(resultado["resumen"]["erp_sin_tarjeta"], 4)
        self.assertEqual(set(logica.tc_inf), set(tarjetas.values()))

    def test_erp_contra_cartola_exige_el_mismo_monto_tambien_en_amex(self):
        archivos = archivos_usd()
        archivos["archivo1"] = xlsx("erp.xlsx", {"ERP": [[None] * 11, self.pago(1, "111", -1000, tarjeta="Amex US$")]})
        archivos["archivo2"] = xlsx("amex.xlsx", {"Amex": [[None] * 15, self.posicion(1, 10.0, 5000)]})
        resultado = logica.procesar(archivos)[0]
        self.assertEqual(resultado["data"][0]["ventas_cm"], 0)
        self.assertEqual(resultado["resumen"]["erp_sin_tarjeta"], 1)

    def test_tarjeta_sin_cartola_cargada_no_cuenta_como_sin_respaldo(self):
        archivos = archivos_usd()
        archivos["archivo1"] = xlsx("erp.xlsx", {"ERP": [[None] * 11, self.pago(1, "111", tarjeta="Visa US$")]})
        self.assertEqual(logica.procesar(archivos)[0]["resumen"]["erp_sin_tarjeta"], 0)

    def test_pago_que_no_esta_en_la_cartola_es_diferencia(self):
        resumen, [reg] = self.registros([self.pago(1, "777")], [self.venta("777", 80.0)], [self.posicion(99)])
        self.assertEqual((reg["monto_cartola"], reg["diferencia"], reg["estado"]), (0.0, 80.0, "diferencia"))
        self.assertIn("NO ESTA", reg["status"])
        self.assertEqual(resumen["por_revisar"], 80.0)


# ---------------------------------------------------------------------------
# Cartolas en pesos: Banco de Chile y BancoEstado
# ---------------------------------------------------------------------------
class CartolaPesosTests(SimpleTestCase):
    def test_banco_de_chile(self):
        archivo = xlsx("cartola.xlsx", {"Hoja1": [
            [None, "Cuenta N°:", None, "00-000-00000-00"],
            [None, "Fecha", None, "Descripción", None, "Canal o Sucursal", "Nro. Docto.", "Cargos (CLP)", "Abonos (CLP)", "Saldo (CLP)"],
            [None, "08/09/2026", None, "Pago: Abono Comer. Tc Tbk 0966893109", None, "Oficina Central", None, None, 2597371, 1],
            [None, "08/09/2026", None, "Traspaso De: Cliente", None, "Internet", None, None, 90321, 1],
        ]})
        abonos = logica_clp.leer_cartola(archivo)
        self.assertEqual([a["monto"] for a in abonos], [2597371])

    def test_bancoestado_con_hoja_resumen(self):
        # BancoEstado: hoja "Resumen" primero y los movimientos en la hoja "Movimientos".
        archivo = xlsx("Excel_Cartola_Historica_Cuenta_Corriente.xlsx", {
            "Resumen": [["Nombre Empresa", None, None, None, "EMPRESA DE PRUEBA"], ["Saldo Inicial", None, None, None, "$1.000"]],
            "Movimientos": [
                ["Fecha", "Sucursal", "N° Cuenta Corriente", "Alias", "N° Cartola", "N° Operación",
                 "Descripción", "Cheques / Cargos", "Depósitos / Abonos", "Saldo"],
                ["20/10/2026", "Stgo.principal", "00000000000", "EMPRESA", "074", "1800958",
                 "Abono transbank tarjeta debito", 0, 404461, 1],
                ["20/10/2026", "Stgo.principal", "00000000000", "EMPRESA", "074", "1350266",
                 "Pagos varios transbank rut 96689310-9 transbank s.a.", 0, 1459396, 1],
                ["20/10/2026", "Stgo.principal", "00000000000", "EMPRESA", "074", "1",
                 "Transferencia de un cliente", 0, 5000, 1],
            ],
        })
        abonos = logica_clp.leer_cartola(archivo)
        self.assertEqual([a["monto"] for a in abonos], [404461, 1459396])
        self.assertEqual(str(abonos[0]["fecha"]), "2026-10-20")

    def test_cartola_sin_encabezado_da_error_claro(self):
        archivo = xlsx("otra.xlsx", {"Hoja1": [["Nada", "que", "ver"]]})
        with self.assertRaisesMessage(logica_clp.ArchivoInvalido, "Depósitos / Abonos"):
            logica_clp.leer_cartola(archivo)


class BorderoTests(SimpleTestCase):
    def bordero(self, filas):
        encabezado = ["Hab", "Tipo Hab", "Reserva", "Cuenta", "Cod. Deb.", "Descripción", None, "Factura",
                      "Valor", "Documento", "Fecha", "Hora", "Usuario", "Designación"]
        periodo = [None, None, None, None, None, "Periodo de:", None, "01/10/2026", None, "hasta", "22/10/2026"]
        return xlsx("bordero.xlsx", {"Hoja1": [periodo, encabezado] + filas})

    def test_iva_debito_fiscal_no_es_un_pago_con_tarjeta(self):
        archivo = self.bordero([
            [None, None, None, 1, "V$", "Visa $", 1, None, -15000, "706537", "04/10/2026"],
            [None, None, None, 2, "IVA", "IVA Débito Fiscal", 2, None, -10953, "Impostos unificados", "04/10/2026"],
            [None, None, None, 3, "RCO", "Red Compra", 3, None, -5000, "123456", "04/10/2026"],
            [None, None, None, 4, "ZZ$", "Tarjeta Visa nueva", 4, None, -700, "999", "04/10/2026"],
        ])
        pagos, periodo = logica_clp.leer_bordero(archivo)
        self.assertEqual(sorted(p["cod"] for p in pagos), ["RCO", "V$", "ZZ$"])
        self.assertEqual(str(periodo[1]), "2026-10-22")


def transbank(nombre, ventas, medio_reporte="Todos", fecha="08 septiembre 2026", moneda="Pesos"):
    """Reporte «Abonos por día» sintético con la misma disposición que entrega Transbank.

    ventas: [(medio, monto, comisión, código de autorización, número único[, N° de tarjeta])]
    """
    def f(**valores):
        return fila(32, **valores)
    arriba = f(c1="Fecha de venta", c2="Tipo de movimiento", c4="Nombre local", c5="Medio de pago", c6="Ventas",
               c24="Identificador", c30="ID transacción (TID)")
    abajo = f(c6="Monto original de venta (+)", c9="N° de cuota", c10="Monto venta válido para abono (+)",
              c11="Comisión Transbank (-)", c12="IVA Comisión Transbank (-)", c13="Total abono (=)",
              c24="N° de tarjeta", c25="Código de autorización de venta", c28="Número único")
    detalle = [f(c1="07 septiembre 2026", c2="Venta", c4="HOTEL, CALLE 1", c5=v[0], c6=v[1], c9="S/C", c10=v[1],
                 c11=v[2], c12=0, c13=v[1] - v[2], c24=v[5] if len(v) > 5 else "4513 68** **** 6158", c25=v[3],
                 c28=v[4], c30="1")
               for v in ventas]
    filas = [
        f(c1="Reporte:", c2="Abonos por día", c8="Periodo de consulta:", c9=fecha),
        f(c1="Empresa:", c7="Moneda:", c9="Medio de pago:"),
        f(c1="HOTEL", c7=moneda, c9=medio_reporte),
        f(c1="Total ventas (+)", c3=sum(v[1] for v in ventas)),
        f(c1="Comisión Transbank (-)", c3=sum(v[2] for v in ventas)),
        f(c1="IVA de comisión Transbank (-)", c3=0),
        f(c1="Total abono", c3=sum(v[1] - v[2] for v in ventas)),
        arriba, abajo,
    ] + detalle
    return xlsx(nombre, {"Hoja1": filas})


def bordero_clp(pagos):
    """pagos: [(código tarjeta, monto, documento)] -> BORDERO del 07-09-2026."""
    encabezado = ["Hab", "Tipo Hab", "Reserva", "Cuenta", "Cod. Deb.", "Descripción", None, "Factura",
                  "Valor", "Documento", "Fecha", "Hora", "Usuario", "Designación"]
    periodo = [None, None, None, None, None, "Periodo de:", None, "07/09/2026", None, "hasta", "07/09/2026"]
    filas = [[None, None, None, i, cod, "Pago", i, None, -monto, doc, "07/09/2026"] for i, (cod, monto, doc) in enumerate(pagos, 1)]
    return xlsx("bordero.xlsx", {"Hoja1": [periodo, encabezado] + filas})


def cartola_clp(abonos):
    filas = [[None, "Fecha", None, "Descripción", None, "Canal o Sucursal", "Nro. Docto.", "Cargos (CLP)", "Abonos (CLP)", "Saldo (CLP)"]]
    filas += [[None, "08/09/2026", None, "Pago: Abono Comer. Tbk", None, "Oficina Central", None, None, m, 1] for m in abonos]
    return xlsx("cartola.xlsx", {"Hoja1": filas})


VENTAS_MIXTAS = [
    ("Crédito", 10000, 200, "000111", "9001"),
    ("Crédito", 20000, 400, "000222", "9002"),
    ("Débito", 5000, 50, "000333", "9003"),
    ("Prepago", 3000, 30, "000444", "9004"),
]
PAGOS_MIXTOS = [("V$", 10000, "111"), ("MC$", 20000, "222"), ("RCO", 5000, "333"), ("RCO", 3000, "444")]


class TransbankMixtoTests(SimpleTestCase):
    def procesar(self, transbank, abonos=None):
        archivos = {"bordero": bordero_clp(PAGOS_MIXTOS), "transbank": transbank}
        if abonos is not None:
            archivos["cartola"] = cartola_clp(abonos)
        return logica_clp.procesar(archivos)[0]

    def por_medio(self, resultado):
        return {m["medio"]: (m["ventas"], m["total_ventas"]) for m in resultado["medios"]}

    def test_un_archivo_con_los_tres_medios_se_separa_por_venta(self):
        r = self.procesar([transbank("tbk.xlsx", VENTAS_MIXTAS)])
        self.assertEqual(self.por_medio(r), {"Crédito": (2, 30000), "Débito": (1, 5000), "Prepago": (1, 3000)})
        self.assertEqual(r["resumen"]["conciliadas"], 4)
        self.assertEqual(r["resumen"]["por_revisar"], 0)

    def test_el_mismo_archivo_subido_tres_veces_no_triplica(self):
        datos = transbank("tbk.xlsx", VENTAS_MIXTAS).read()
        copias = [SimpleUploadedFile(f"tbk{i}.xlsx", datos) for i in range(3)]
        r = self.procesar(copias)
        self.assertEqual(r["total_medios"]["ventas"], 4)
        self.assertEqual(r["total_medios"]["total_ventas"], 38000)
        self.assertEqual(r["resumen"]["archivos_repetidos"], ["tbk1.xlsx", "tbk2.xlsx"])
        self.assertEqual(r["resumen"]["sin_registro"], 0)

    def test_venta_repetida_en_dos_archivos_distintos_se_cuenta_una_vez(self):
        juntos = transbank("todos.xlsx", VENTAS_MIXTAS)
        solo_debito = transbank("debito.xlsx", [VENTAS_MIXTAS[2]], medio_reporte="Débito")
        r = self.procesar([juntos, solo_debito])
        self.assertEqual(r["total_medios"]["ventas"], 4)
        self.assertEqual(r["resumen"]["ventas_repetidas"], 1)

    def test_medio_del_encabezado_si_el_detalle_no_lo_trae(self):
        ventas = [("", 10000, 200, "000111", "9001")]
        r = self.procesar([transbank("credito.xlsx", ventas, medio_reporte="Crédito")])
        self.assertEqual(self.por_medio(r), {"Crédito": (1, 10000)})

    def test_abono_por_medio_en_la_cartola(self):
        r = self.procesar([transbank("tbk.xlsx", VENTAS_MIXTAS)], abonos=[29400, 4950, 2970])
        self.assertEqual({m["medio"]: m["banco"] for m in r["medios"]},
                         {"Crédito": "encontrado", "Débito": "encontrado", "Prepago": "encontrado"})
        self.assertEqual(r["resumen"]["abonos_faltantes"], [])

    def test_abono_conjunto_de_debito_y_prepago(self):
        r = self.procesar([transbank("tbk.xlsx", VENTAS_MIXTAS)], abonos=[29400, 4950 + 2970])
        medios = {m["medio"]: m for m in r["medios"]}
        self.assertEqual(medios["Crédito"]["nota_banco"], "")
        self.assertEqual(medios["Débito"]["banco"], "encontrado")
        self.assertEqual(medios["Prepago"]["nota_banco"], "Abono conjunto: Débito + Prepago")

    def test_reporte_en_dolares_se_rechaza_en_pesos(self):
        with self.assertRaisesRegex(logica_clp.ArchivoInvalido, "dólares"):
            self.procesar([transbank("usd.xlsx", VENTAS_MIXTAS, moneda="Dólares")])

    def test_abono_faltante(self):
        r = self.procesar([transbank("tbk.xlsx", VENTAS_MIXTAS)], abonos=[29400])
        self.assertEqual(r["resumen"]["abonos_faltantes"], ["Débito", "Prepago"])
        self.assertFalse(r["resumen"]["cuadrado"])


# ---------------------------------------------------------------------------
# Formato chileno de números
# ---------------------------------------------------------------------------
class FormatoChileTests(SimpleTestCase):
    def render(self, plantilla, **contexto):
        with translation.override("es-cl"):
            return Template(plantilla).render(Context(contexto))

    def test_miles_con_punto(self):
        self.assertEqual(self.render('{{ v|floatformat:"0g" }}', v=1234567), "1.234.567")

    def test_decimales_con_coma(self):
        self.assertEqual(self.render('{{ v|floatformat:"2g" }}', v=24873.45), "24.873,45")

    def test_negativos(self):
        self.assertEqual(self.render('{{ v|floatformat:"2g" }}', v=-18.25), "-18,25")


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
@override_settings(ALLOWED_HOSTS=["testserver"])
class PantallasTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026")

    def test_pide_login(self):
        respuesta = self.client.get("/conciliacion/pesos/")
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("/usuarios/login/", respuesta["Location"])

    def test_login_por_correo(self):
        respuesta = self.client.post("/usuarios/login/", {"email": "PRUEBA@hotel.cl", "password": "Clave-Prueba-2026"})
        self.assertEqual(respuesta.status_code, 302)

    @mock.patch("apps.conciliacion.dolar.obtener_serie_dolar", return_value=[])  # sin internet
    def test_conciliacion_usd_se_guarda_en_el_historial(self, _dolar):
        self.client.force_login(self.usuario)
        archivos = {campo: a for campo, a in archivos_usd(formato_tarjeta="xlsx").items() if a}
        respuesta = self.client.post("/conciliacion/", archivos)
        self.assertEqual(respuesta.status_code, 302)
        detalle = self.client.get(respuesta["Location"])
        self.assertContains(detalle, "Abono encontrado en el banco")
        self.assertContains(detalle, "guardada en el historial")

    def test_archivo_equivocado_en_pesos_muestra_error(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post("/conciliacion/pesos/", {
            "bordero": xlsx("bordero.xlsx", {"Hoja1": [["no", "es", "un", "bordero"]]}),
            "transbank": xlsx("tbk.xlsx", {"Hoja1": [["tampoco"]]}),
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "No se pudo completar el análisis")

    def test_pesos_con_varios_archivos_de_transbank_se_guarda(self):
        self.client.force_login(self.usuario)
        datos = transbank("tbk.xlsx", VENTAS_MIXTAS).read()
        respuesta = self.client.post("/conciliacion/pesos/", {
            "bordero": bordero_clp(PAGOS_MIXTOS),
            "transbank": [SimpleUploadedFile("tbk.xlsx", datos), SimpleUploadedFile("tbk_copia.xlsx", datos)],
        })
        self.assertEqual(respuesta.status_code, 302)
        detalle = self.client.get(respuesta["Location"])
        self.assertContains(detalle, "Se ignoraron datos repetidos de Transbank")
        self.assertContains(detalle, "tbk_copia.xlsx")
        self.assertContains(detalle, "38.000")
        corte = '<strong class="fecha-periodo">07-09-2026</strong>'
        self.assertContains(detalle, corte)
        self.assertContains(self.client.get("/conciliacion/historial/"), corte)

    def test_identifica_cada_archivo_soltado_en_el_recuadro(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post("/conciliacion/pesos/identificar/", {"archivos": [
            cartola_clp([]),
            transbank("tbk.xlsx", VENTAS_MIXTAS),
            bordero_clp(PAGOS_MIXTOS),
            xlsx("otro.xlsx", {"Hoja1": [["nada", "que", "ver"]]}),
            texto("vacio.csv", ""),
            transbank("tbk_usd.xlsx", VENTAS_MIXTAS, moneda="Dólar"),
        ]})
        archivos = respuesta.json()["archivos"]
        self.assertEqual([a["tipo"] for a in archivos], ["cartola", "transbank", "bordero", None, None, None])
        self.assertIn("dólares", archivos[-1]["motivo"])

    def test_identifica_cada_archivo_soltado_en_dolares(self):
        self.client.force_login(self.usuario)
        usd = archivos_usd()
        visa = xlsx("visa.xls", {"Sheet 1": [
            ["HOTEL PLAZA SAN FRANCISCO"],
            ["Posición Por Clientes en 04/12/2025 - Sin Inclusión de Anticipos"],
            ["Cliente:", "96.689.310//9 - - TRANSBANK - TARJETA VISA US$"],
        ]})
        respuesta = self.client.post("/conciliacion/identificar/", {"archivos": [
            usd["archivo1"], usd["archivo7"], usd["archivo6"], visa,
            cartola_clp([]), transbank("tbk_clp.xlsx", VENTAS_MIXTAS),
        ]})
        archivos = respuesta.json()["archivos"]
        self.assertEqual([a["tipo"] for a in archivos], ["archivo1", "archivo7", "archivo6", "archivo4", None, None])
        self.assertIn("pesos", archivos[-1]["motivo"])


class VariosBorderosTests(SimpleTestCase):
    """Un BORDERO por tarjeta: todos se juntan en una sola conciliación."""

    def _bordero(self, nombre, pagos):
        archivo = bordero_clp(pagos)
        archivo.name = nombre
        return archivo

    def test_junta_los_pagos_de_todos_los_archivos(self):
        visa = self._bordero("visa.xlsx", PAGOS_MIXTOS[:1])
        resto = self._bordero("resto.xlsx", PAGOS_MIXTOS[1:])
        pagos, periodo, repetidos, pagos_repetidos = logica_clp.leer_borderos([visa, resto])
        solo, periodo_solo = logica_clp.leer_bordero(self._bordero("todo.xlsx", PAGOS_MIXTOS))
        self.assertEqual(sorted(p["monto"] for p in pagos), sorted(p["monto"] for p in solo))
        self.assertEqual({p["archivo"] for p in pagos}, {"visa.xlsx", "resto.xlsx"})
        self.assertEqual((periodo, repetidos, pagos_repetidos), (periodo_solo, [], 0))

    def test_archivo_y_pagos_repetidos_se_cuentan_una_vez(self):
        todo = self._bordero("todo.xlsx", PAGOS_MIXTOS)
        copia = self._bordero("copia.xlsx", PAGOS_MIXTOS)
        parte = self._bordero("parte.xlsx", PAGOS_MIXTOS[:1])
        base, _ = logica_clp.leer_bordero(self._bordero("base.xlsx", PAGOS_MIXTOS))
        pagos, _, repetidos, pagos_repetidos = logica_clp.leer_borderos([todo, copia, parte])
        self.assertEqual(len(pagos), len(base))
        self.assertEqual(repetidos, ["copia.xlsx"])
        self.assertEqual(pagos_repetidos, 1)

    def test_un_bordero_sin_pagos_no_bloquea_a_los_demas(self):
        vacio = self._bordero("vacio.xlsx", [])
        con_pagos = self._bordero("visa.xlsx", PAGOS_MIXTOS)
        pagos, _, _, _ = logica_clp.leer_borderos([vacio, con_pagos])
        self.assertTrue(pagos)
        with self.assertRaises(logica_clp.ArchivoInvalido):
            logica_clp.leer_borderos([self._bordero("vacio2.xlsx", [])])


def xls_antiguo(filas):
    """Excel antiguo (BIFF4) como el que exporta el FrontOffice: una fila de texto por cada elemento."""
    registros = [struct.pack("<HHHHH", 0x0409, 6, 0, 0x10, 0)]
    for numero_fila, celdas in enumerate(filas):
        for columna, valor in enumerate(celdas):
            datos = str(valor).encode("latin-1")
            registros.append(struct.pack("<HHHHHH", 0x0204, 8 + len(datos), numero_fila, columna, 0, len(datos)) + datos)
    registros.append(struct.pack("<HH", 0x000A, 0))
    return b"".join(registros)


class ExcelAntiguoLargoTests(SimpleTestCase):
    def test_lee_mas_filas_que_el_tope_de_xlrd(self):
        archivo = SimpleUploadedFile("largo.XLS", xls_antiguo([["fila", i] for i in range(20000)]))
        _, tabla = lectura.leer_hojas(archivo)[0]
        self.assertEqual(len(tabla), 20000)
        self.assertEqual(str(tabla.iat[19999, 1]), "19999")

    def test_archivo_danado_explica_el_motivo(self):
        archivo = SimpleUploadedFile("malo.xls", xls_antiguo([["a"]])[:-20] + b"\xff" * 30)
        with mock.patch("pandas.read_excel", side_effect=AssertionError()):
            with self.assertRaisesRegex(lectura.FormatoNoSoportado, "dañado"):
                lectura.leer_hojas(archivo)


class VariosErpTests(SimpleTestCase):
    """En dólares, el ERP puede ser el BORDERO completo o uno por tarjeta."""

    def _erp(self, nombre, *filas):
        return xlsx(nombre, {"ERP": [[None] * 11, *filas]})

    MC = fila(11, c3=5001, c5="Pago Master Card US$", c8=-100, c9="AUTH123", c10="01-09-2026")
    VISA = fila(11, c3=7001, c5="Pago Visa US$", c8=-50, c9="AUTH777", c10="02-09-2026")

    def test_dos_erp_dan_lo_mismo_que_uno_con_todo(self):
        archivos = archivos_usd()
        archivos["archivo1"] = self._erp("completo.xlsx", self.MC, self.VISA)
        completo = logica.procesar(archivos)[0]

        archivos = archivos_usd()
        archivos["archivo1"] = [self._erp("mc.xlsx", self.MC), self._erp("visa.xlsx", self.VISA)]
        separados = logica.procesar(archivos)[0]

        self.assertEqual(separados["data"], completo["data"])
        self.assertEqual(separados["data_dolar"], completo["data_dolar"])
        self.assertEqual(separados["resumen"]["ubicadas"], 1)
        self.assertEqual((separados["resumen"]["erp_repetidos"], separados["resumen"]["filas_erp_repetidas"]), ([], 0))

    def test_completo_mas_por_tarjeta_no_cuenta_doble(self):
        archivos = archivos_usd()
        archivos["archivo1"] = self._erp("solo.xlsx", self.MC, self.VISA)
        base = logica.procesar(archivos)[0]

        archivos = archivos_usd()
        archivos["archivo1"] = [self._erp("todo.xlsx", self.MC, self.VISA), self._erp("mc.xlsx", self.MC)]
        resultado = logica.procesar(archivos)[0]
        self.assertEqual(resultado["data"], base["data"])
        self.assertEqual(resultado["resumen"]["filas_erp_repetidas"], 1)

    def test_mismo_numero_como_entero_o_decimal_es_la_misma_fila(self):
        archivos = archivos_usd()
        archivos["archivo1"] = [self._erp("a.xlsx", fila(11, c3=7001, c5="Pago Visa US$", c6=107093, c8=-50, c9="AUTH777")),
                                self._erp("b.xlsx", fila(11, c3=7001, c5="Pago Visa US$", c6=107093.0, c8=-50, c9="AUTH777"),
                                          fila(11, c3=7002, c5="Pago Visa US$", c6=1.5, c8=-60, c9="AUTH778"))]
        self.assertEqual(logica.procesar(archivos)[0]["resumen"]["filas_erp_repetidas"], 1)

    def test_encabezados_de_pagina_no_cuentan_como_repetidos(self):
        encabezado = fila(11, c4="Cod. Deb.", c5="Descripción", c8="Valor", c9="Documento", c10="Fecha")
        mc = fila(11, c3=5001, c4="MCUS$", c5="Master Card US$", c8=-100, c9="AUTH123", c10="01-09-2026")
        visa = fila(11, c3=7001, c4="VUS$", c5="Visa US$", c8=-50, c9="AUTH777", c10="02-09-2026")
        archivos = archivos_usd()
        archivos["archivo1"] = [self._erp("mc.xlsx", encabezado, mc), self._erp("visa.xlsx", encabezado, visa)]
        self.assertEqual(logica.procesar(archivos)[0]["resumen"]["filas_erp_repetidas"], 0)

    def test_el_codigo_en_otra_fila_del_bordero_no_es_el_pago(self):
        # Caso real: «Venta:303742» en un consumo del bar, antes del pago Visa US$ con ese código.
        pago = fila(11, c3=5001, c4="MCUS$", c5="Master Card US$", c8=-100, c9="AUTH123", c10="01-09-2026")
        bar = fila(11, c3=9999, c4="BAR", c5="BAR BRISTOL", c8=12101, c9="Venta:AUTH123", c10="20-08-2026")
        archivos = archivos_usd()
        archivos["archivo1"] = self._erp("completo.xlsx", bar, pago)
        resultado = logica.procesar(archivos)[0]
        self.assertEqual(logica.informacion_proceso[0]["documento"], 5001)
        self.assertEqual(resultado["data_dolar"][-1]["diferencia"], 0)

    def test_archivo_subido_dos_veces_se_lee_una(self):
        archivos = archivos_usd()
        datos = self._erp("uno.xlsx", self.MC).read()
        archivos["archivo1"] = [SimpleUploadedFile("uno.xlsx", datos), SimpleUploadedFile("copia.xlsx", datos)]
        self.assertEqual(logica.procesar(archivos)[0]["resumen"]["erp_repetidos"], ["copia.xlsx"])


class CruceConFechaTests(SimpleTestCase):
    """El cruce no se queda con el primer código: también mira el monto y la fecha."""

    def _venta(self, codigo, monto, fecha):
        return {"codigo": codigo, "codigo_flex": codigo, "monto": monto, "fecha": fecha}

    def _pago(self, codigo, monto, fecha):
        return {"codigo": codigo, "codigo_flex": codigo, "documento": codigo, "monto": monto, "fecha": fecha,
                "cod": "RCO", "cuenta": "1"}

    def _cruzar(self, venta, pagos):
        pendientes = logica_clp._cruzar([venta], pagos, (date(2026, 1, 1), date(2026, 11, 4)))
        return venta, pendientes

    def test_mismo_monto_y_fecha_gana_a_un_codigo_igual_de_otro_mes(self):
        # Caso real: venta 003538 del 29-10; el pago correcto quedó digitado como 3568.
        correcto = self._pago("3568", 67650, date(2026, 10, 29))
        venta, _ = self._cruzar(self._venta("3538", 67650, date(2026, 10, 29)), [
            self._pago("3538", 16560, date(2026, 6, 5)),
            self._pago("3538", 11331, date(2026, 1, 8)),
            self._pago("3538", 10199, date(2026, 4, 1)),
            correcto,
        ])
        self.assertEqual(venta["estado"], "conciliado")
        self.assertEqual(venta["documento_bordero"], "3568")
        self.assertIn("revisar código", venta["nota"])

    def test_con_varios_iguales_elige_el_de_la_fecha_de_la_venta(self):
        venta, _ = self._cruzar(self._venta("3538", 5000, date(2026, 10, 29)), [
            self._pago("3538", 5000, date(2026, 6, 5)),
            self._pago("3538", 5000, date(2026, 10, 29)),
        ])
        self.assertEqual((venta["estado"], venta["fecha_bordero"], venta["nota"]), ("conciliado", date(2026, 10, 29), ""))

    def test_codigo_igual_con_otro_monto_lejano_no_es_diferencia(self):
        venta, pendientes = self._cruzar(self._venta("3538", 67650, date(2026, 10, 29)),
                                         [self._pago("3538", 16560, date(2026, 6, 5))])
        self.assertEqual(venta["estado"], "sin_registro")
        self.assertEqual(len(pendientes), 1)

    def test_codigo_igual_con_otro_monto_en_fecha_es_diferencia(self):
        venta, _ = self._cruzar(self._venta("3538", 67650, date(2026, 10, 29)),
                                [self._pago("3538", 16560, date(2026, 10, 28))])
        self.assertEqual(venta["estado"], "diferencia")

    def test_codigo_y_monto_iguales_en_otra_fecha_queda_con_observacion(self):
        venta, _ = self._cruzar(self._venta("3538", 5000, date(2026, 10, 29)),
                                [self._pago("3538", 5000, date(2026, 6, 5))])
        self.assertEqual(venta["estado"], "conciliado")
        self.assertIn("otra fecha", venta["nota"])


class AtajosTests(TestCase):
    """Botones «Conciliar con archivos de ejemplo» y «Borrar historial» de las páginas previas."""

    def setUp(self):
        self.usuario = User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026")
        self.client.force_login(self.usuario)

    def _carpeta_ejemplos(self, archivos_por_carpeta):
        import tempfile
        from pathlib import Path
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        raiz = Path(temporal.name)
        for carpeta, archivos in archivos_por_carpeta.items():
            (raiz / carpeta).mkdir()
            for archivo in archivos:
                (raiz / carpeta / archivo.name).write_bytes(archivo.read())
        return mock.patch("apps.conciliacion.views.EJEMPLOS", raiz)

    def test_ejemplo_en_pesos_concilia_y_guarda(self):
        with self._carpeta_ejemplos({"pesos": [bordero_clp(PAGOS_MIXTOS), transbank("tbk.xlsx", VENTAS_MIXTAS)]}):
            respuesta = self.client.post("/conciliacion/pesos/ejemplo/")
        self.assertEqual(respuesta.status_code, 302)
        self.assertContains(self.client.get(respuesta["Location"]), "38.000")

    @mock.patch("apps.conciliacion.dolar.obtener_serie_dolar", return_value=[])  # sin internet
    def test_ejemplo_en_dolares_concilia_y_guarda(self, _dolar):
        usd = [a for a in archivos_usd(formato_tarjeta="xlsx").values() if a]
        with self._carpeta_ejemplos({"dolares": usd}):
            respuesta = self.client.post("/conciliacion/ejemplo/")
        self.assertEqual(respuesta.status_code, 302)
        self.assertContains(self.client.get(respuesta["Location"]), "Abono encontrado en el banco")

    @mock.patch("apps.conciliacion.dolar.obtener_serie_dolar", return_value=[])  # sin internet
    def test_varios_erp_en_la_pantalla_de_dolares(self, _dolar):
        usd = {campo: a for campo, a in archivos_usd().items() if a}
        visa = xlsx("visa.xlsx", {"ERP": [[None] * 11, fila(11, c3=7001, c5="Pago Visa US$", c8=-50, c9="AUTH777", c10="02-09-2026")]})
        usd["archivo1"] = [usd["archivo1"], visa]
        respuesta = self.client.post("/conciliacion/", usd)
        self.assertEqual(respuesta.status_code, 302)
        detalle = self.client.get(respuesta["Location"])
        self.assertContains(detalle, "erp.xlsx")
        self.assertContains(detalle, "visa.xlsx")

    def test_ejemplo_sin_archivos_avisa(self):
        with self._carpeta_ejemplos({}):
            respuesta = self.client.post("/conciliacion/pesos/ejemplo/")
        self.assertContains(respuesta, "No hay archivos de ejemplo en el servidor")

    def test_borrar_historial_borra_pesos_y_dolares(self):
        from .models import Conciliacion
        Conciliacion.objects.create(moneda=Conciliacion.PESOS)
        Conciliacion.objects.create(moneda=Conciliacion.PESOS)
        Conciliacion.objects.create(moneda=Conciliacion.DOLARES)
        self.assertContains(self.client.get("/conciliacion/historial/"), "Borrar historial (3)")
        self.assertNotContains(self.client.get("/conciliacion/pesos/"), "Borrar historial")
        respuesta = self.client.post("/conciliacion/historial/borrar/", follow=True)
        self.assertContains(respuesta, "Se borraron 3 conciliaciones del historial.")
        self.assertFalse(Conciliacion.objects.exists())

    def test_borrar_historial_no_acepta_get(self):
        self.assertEqual(self.client.get("/conciliacion/historial/borrar/").status_code, 405)
