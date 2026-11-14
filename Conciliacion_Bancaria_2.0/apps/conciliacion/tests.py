"""Pruebas de lectura de archivos, motor en dólares, cartolas en pesos y formato chileno.

Usan archivos sintéticos generados en memoria (el repositorio es público: no se
incluyen datos reales del hotel). Ejecutar con:

    python manage.py test apps.conciliacion
"""
import io
import struct
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone, translation
from openpyxl import Workbook, load_workbook

from . import excepciones, graficos, lectura, logica, logica_clp, registro
from .models import Conciliacion, Configuracion, Excepcion
from .parametros import Parametros


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
        self.assertEqual(archivos[1]["detalle"], "ventas de Crédito: 07-09 · Débito y prepago: 07-09")
        self.assertEqual(archivos[2]["detalle"], "del 07-09-2026 al 07-09-2026")

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
        # Los ejemplos son solo para administradores (staff sin perfil asignado = Administrador).
        self.usuario = User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026", is_staff=True)
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

    def test_borrar_historial_no_acepta_get(self):
        self.assertRedirects(self.client.get("/conciliacion/historial/borrar/"), "/conciliacion/historial/")


# ---------------------------------------------------------------------------
# Configuración: tolerancias, ventana de días y palabras clave de la cartola
# ---------------------------------------------------------------------------
class ParametrosMotorTests(SimpleTestCase):
    """Los motores usan los parámetros que reciben; sin parámetros, los valores de siempre."""

    def _cruzar(self, monto_pago, dias_pago=0, **parametros):
        p = Parametros(**parametros)
        venta = {"codigo": "3538", "codigo_flex": "3538", "monto": 10000, "fecha": date(2026, 10, 29)}
        pago = {"codigo": "3538", "codigo_flex": "3538", "documento": "3538", "monto": monto_pago,
                "fecha": date(2026, 10, 29 - dias_pago), "cod": "RCO", "cuenta": "1"}
        logica_clp._cruzar([venta], [pago], (date(2026, 10, 1), date(2026, 10, 31)), p.tolerancia_clp, p.ventana_dias)
        return venta

    def test_por_defecto_una_diferencia_de_300_pesos_es_diferencia(self):
        self.assertEqual(self._cruzar(9700)["estado"], "diferencia")

    def test_con_tolerancia_de_500_la_misma_venta_queda_conciliada(self):
        venta = self._cruzar(9700, tolerancia_clp=500)
        self.assertEqual(venta["estado"], "conciliado")
        self.assertIn("Diferencia dentro de la tolerancia", venta["nota"])

    def test_diferencia_chica_se_sigue_informando_como_redondeo(self):
        self.assertIn("Diferencia de redondeo", self._cruzar(9992, tolerancia_clp=500)["nota"])

    def test_la_tolerancia_no_une_ventas_de_otro_codigo(self):
        # Mismo día, monto parecido pero otro código: con tolerancia amplia no debe darse por conciliada.
        p = Parametros(tolerancia_clp=1000)
        venta = {"codigo": "1111", "codigo_flex": "1111", "monto": 10000, "fecha": date(2026, 10, 29)}
        pago = {"codigo": "9999", "codigo_flex": "9999", "documento": "9999", "monto": 9400,
                "fecha": date(2026, 10, 29), "cod": "RCO", "cuenta": "1"}
        logica_clp._cruzar([venta], [pago], (date(2026, 10, 1), date(2026, 10, 31)), p.tolerancia_clp, p.ventana_dias)
        self.assertEqual(venta["estado"], "sin_registro")

    def test_ventana_de_dias(self):
        self.assertIn("otra fecha", self._cruzar(10000, dias_pago=5)["nota"])
        self.assertEqual(self._cruzar(10000, dias_pago=5, ventana_dias=7)["nota"], "")

    def test_palabras_clave_de_la_cartola(self):
        self.assertEqual(len(logica_clp.leer_cartola(cartola_clp([1000]))), 1)
        self.assertEqual(logica_clp.leer_cartola(cartola_clp([1000]), Parametros(palabras_cartola=("transbank",))), [])
        self.assertEqual(len(logica_clp.leer_cartola(cartola_clp([1000]), Parametros(palabras_cartola=("abono comer",)))), 1)

    def test_la_conciliacion_en_pesos_guarda_los_criterios_usados(self):
        archivos = {"bordero": bordero_clp(PAGOS_MIXTOS), "transbank": [transbank("tbk.xlsx", VENTAS_MIXTAS)]}
        resultado, _ = logica_clp.procesar(archivos, parametros=Parametros(tolerancia_clp=700))
        self.assertEqual(resultado["parametros"]["tolerancia_clp"], 700)

    def test_tolerancia_en_dolares(self):
        self.assertFalse(logica._es_redondeo(0.5))
        self.assertTrue(logica._es_redondeo(0.5, 1.0))
        resultado, _ = logica.procesar(archivos_usd(), parametros=Parametros(tolerancia_usd=1.5))
        self.assertEqual(resultado["resumen"]["tolerancia_redondeo"], 1.5)
        self.assertEqual(resultado["parametros"]["tolerancia_usd"], 1.5)


class ConfiguracionTests(TestCase):
    URL = "/conciliacion/configuracion/"

    def setUp(self):
        self.admin = User.objects.create_user("jefe", "jefe@hotel.cl", "Clave-Prueba-2026", is_staff=True)
        self.usuario = User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026")

    def datos(self, **cambios):
        datos = {"tolerancia_clp": "500", "tolerancia_usd": "0.50", "ventana_dias": "3", "palabras_cartola": "Transbank, TBK"}
        datos.update(cambios)
        return datos

    def test_sin_configuracion_guardada_se_usan_los_valores_por_defecto(self):
        self.assertEqual(Configuracion.actual().parametros(), Parametros())
        self.assertFalse(Configuracion.objects.exists())

    def test_solo_un_administrador_puede_entrar(self):
        self.client.force_login(self.usuario)
        self.assertRedirects(self.client.get(self.URL), "/", fetch_redirect_response=False)
        self.assertRedirects(self.client.post(self.URL, self.datos()), "/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/"), "solo la pueden ver y cambiar los administradores")
        self.assertFalse(Configuracion.objects.exists())
        self.assertNotContains(self.client.get("/conciliacion/pesos/"), self.URL)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.URL), "Tolerancia en pesos")
        self.assertContains(self.client.get("/conciliacion/pesos/"), self.URL)

    def test_guardar_cambios(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.URL, self.datos(), follow=True)
        self.assertRedirects(respuesta, self.URL)
        self.assertContains(respuesta, "Configuración guardada")
        parametros = Configuracion.actual().parametros()
        self.assertEqual((parametros.tolerancia_clp, parametros.tolerancia_usd), (500, 0.5))
        self.assertEqual(parametros.palabras_cartola, ("transbank", "tbk"))
        self.assertEqual(Configuracion.objects.get().actualizada_por, self.admin)
        self.assertContains(self.client.get("/conciliacion/pesos/"), "Tolerancia: $ 500")

    def test_valores_fuera_de_rango_no_se_guardan(self):
        self.client.force_login(self.admin)
        self.client.post(self.URL, self.datos())
        for cambio, mensaje in [
            ({"tolerancia_clp": "-1"}, "no puede ser negativa"),
            ({"tolerancia_clp": "2000"}, "no puede superar $1.000"),
            ({"tolerancia_usd": "9"}, "no puede superar US$ 5"),
            ({"ventana_dias": "40"}, "no puede superar 15 días"),
            ({"palabras_cartola": " , "}, "al menos una palabra clave"),
            ({"palabras_cartola": "transbank, tb"}, "al menos 3 letras"),
        ]:
            respuesta = self.client.post(self.URL, self.datos(**cambio))
            self.assertEqual(respuesta.status_code, 200)
            self.assertContains(respuesta, mensaje)
            self.assertContains(respuesta, "No se guardaron los cambios")
        self.assertEqual(Configuracion.actual().parametros().tolerancia_clp, 500)

    def test_la_conciliacion_usa_la_configuracion_y_la_muestra_en_el_detalle(self):
        self.client.force_login(self.admin)
        self.client.post(self.URL, self.datos(tolerancia_clp="800"))
        respuesta = self.client.post("/conciliacion/pesos/", {
            "bordero": bordero_clp(PAGOS_MIXTOS), "transbank": [transbank("tbk.xlsx", VENTAS_MIXTAS)],
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Conciliacion.objects.get().resultado["parametros"]["tolerancia_clp"], 800)
        self.assertContains(self.client.get(respuesta["Location"]), "Criterios usados: tolerancia de $ 800")

    def test_restablecer_valores_por_defecto(self):
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(self.URL), "Restablecer valores por defecto")
        self.client.post(self.URL, self.datos(tolerancia_clp="900", ventana_dias="7", palabras_cartola="abono comer"))
        pagina = self.client.get(self.URL)
        self.assertContains(pagina, "Restablecer valores por defecto")
        self.assertContains(pagina, "De $0 a $1.000; por defecto $10.")
        respuesta = self.client.post("/conciliacion/configuracion/restablecer/", follow=True)
        self.assertContains(respuesta, "Se restablecieron los valores por defecto.")
        self.assertContains(respuesta, "Se están usando los valores por defecto.")
        self.assertNotContains(respuesta, "Restablecer valores por defecto")
        self.assertEqual(Configuracion.actual().parametros(), Parametros())
        self.assertEqual(Configuracion.objects.get().actualizada_por, self.admin)

    def test_restablecer_solo_administradores_y_por_post(self):
        self.client.force_login(self.usuario)
        self.assertRedirects(self.client.post("/conciliacion/configuracion/restablecer/"), "/")
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get("/conciliacion/configuracion/restablecer/"), self.URL)


# ---------------------------------------------------------------------------
# Ventas en cuotas
# ---------------------------------------------------------------------------
def tbk_cuotas(nombre, dia_abono, filas):
    """Reporte «Abonos por día» de un día, con ventas en cuotas.

    filas: [(fecha de venta, cuota «k/N» o «S/C», monto original, monto de la cuota, código, número único)]
    """
    def f(**valores):
        return fila(32, **valores)
    return xlsx(nombre, {"Hoja1": [
        f(c1="Reporte:", c2="Abonos por día", c8="Periodo de consulta:", c9=dia_abono, c10="Día desde:",
          c11=" ".join(dia_abono.split()[:2]), c12="Día hasta:", c13=" ".join(dia_abono.split()[:2])),
        f(c1="Empresa:", c7="Moneda:", c9="Medio de pago:"),
        f(c1="HOTEL", c7="Pesos", c9="Todos los medios de pago"),
        f(c1="Total abono", c3=sum(x[3] for x in filas)),
        f(c1="Fecha de venta", c5="Medio de pago", c6="Ventas", c24="Identificador", c30="ID transacción (TID)"),
        f(c6="Monto original de venta (+)", c8="Tipo de venta/cuota", c9="N° de cuota",
          c10="Monto venta válido para abono (+)", c11="Comisión Transbank (-)", c13="Total abono (=)",
          c24="N° de tarjeta", c25="Código de autorización de venta", c28="Número único"),
    ] + [f(c1=venta, c2="Venta", c5="Crédito", c6=original, c8="C3C" if "/" in cuota else "Venta $", c9=cuota,
           c10=valor, c11=0, c13=valor, c24="4513 68** **** 6158", c25=codigo, c28=unico, c30="1")
         for venta, cuota, original, valor, codigo, unico in filas]})


class CuotasTests(SimpleTestCase):
    VENTA = "07 septiembre 2026"

    def procesar(self, *reportes):
        archivos = {"bordero": bordero_clp([("V$", 90000, "777")]), "transbank": list(reportes)}
        return logica_clp.procesar(archivos)[0]

    def cuota(self, k, dia, unico):
        return tbk_cuotas(f"tbk_{k}.xlsx", dia, [(self.VENTA, f"{k}/3", 90000, 30000, "000777", unico)])

    def test_las_otras_cuotas_no_quedan_sin_registro(self):
        r = self.procesar(self.cuota(1, "08 septiembre 2026", "1"), self.cuota(2, "08 octubre 2026", "2"),
                          self.cuota(3, "07 noviembre 2026", "3"))
        resumen = r["resumen"]
        self.assertEqual((resumen["conciliadas"], resumen["sin_registro"], resumen["otras_cuotas"]), (1, 0, 2))
        self.assertEqual(resumen["por_revisar"], 0)
        venta = r["cuotas"]["ventas"][0]
        self.assertEqual((venta["encontradas"], venta["faltantes"]), ("1/3, 2/3, 3/3", []))

    def test_cuota_desfasada_queda_como_no_encontrada_dentro_del_periodo(self):
        # Dos cuotas en meses seguidos y la tercera llega dos meses después (en diciembre, no cargado).
        r = self.procesar(self.cuota(1, "08 septiembre 2026", "1"), self.cuota(2, "08 octubre 2026", "2"),
                          tbk_cuotas("noviembre.xlsx", "09 noviembre 2026", [("05 noviembre 2026", "S/C", 5000, 5000, "000888", "9")]))
        cuotas = r["cuotas"]
        self.assertEqual(cuotas["faltantes_en_periodo"], 1)
        self.assertEqual(cuotas["ventas"][0]["faltantes"], [{"cuota": "3/3", "mes": "Noviembre 2026", "en_periodo": True}])
        self.assertEqual(r["resumen"]["cuotas_faltantes"], 1)
        self.assertEqual(r["resumen"]["por_revisar"], 0)  # la cuota faltante es un aviso: no suma

        # Al agregar el reporte de diciembre, la cuota aparece y ya no falta nada.
        r = self.procesar(self.cuota(1, "08 septiembre 2026", "1"), self.cuota(2, "08 octubre 2026", "2"),
                          self.cuota(3, "08 diciembre 2026", "3"))
        self.assertEqual(r["cuotas"]["faltantes"], 0)

    def test_cuotas_de_meses_no_cargados_son_solo_informativas(self):
        r = self.procesar(self.cuota(1, "08 septiembre 2026", "1"))
        cuotas = r["cuotas"]
        self.assertEqual((cuotas["faltantes"], cuotas["faltantes_en_periodo"]), (2, 0))
        self.assertEqual([f["mes"] for f in cuotas["ventas"][0]["faltantes"]], ["Octubre 2026", "Noviembre 2026"])

    def test_cuota_de_una_venta_anterior_al_bordero(self):
        r = self.procesar(tbk_cuotas("oct.xlsx", "22 octubre 2026",
                                     [("20 agosto 2026", "3/3", 428006, 142670, "468617", "5")]))
        observacion = r["cuotas"]["ventas"][0]
        self.assertEqual(observacion["estado_venta"], "Fuera del período del BORDERO")
        self.assertEqual(observacion["faltantes_texto"], "1/3 (Agosto 2026), 2/3 (Septiembre 2026)")

    def test_se_ve_en_el_detalle_y_en_el_excel(self):
        r, reportes = logica_clp.procesar({"bordero": bordero_clp([("V$", 90000, "777")]), "transbank": [
            self.cuota(1, "08 septiembre 2026", "1"), self.cuota(2, "08 octubre 2026", "2"),
            tbk_cuotas("nov.xlsx", "09 noviembre 2026", [("05 noviembre 2026", "S/C", 5000, 5000, "000888", "9")])]})
        html = Template('{% include "conciliacion/_resultado_clp.html" %}').render(Context(r))
        self.assertIn("1 cuota no encontrada: revisar", html)
        self.assertIn("Esperada en noviembre 2026", html)
        completa = load_workbook(io.BytesIO(reportes[0][4]))
        self.assertIn("Cuotas", completa.sheetnames)


# ---------------------------------------------------------------------------
# Pagos del BORDERO sin abono: solo las fechas que traen los reportes de Transbank
# ---------------------------------------------------------------------------
def bordero_dias(pagos):
    """pagos: [(código tarjeta, monto, documento, día de septiembre)] -> BORDERO del 01 al 10-09-2026."""
    encabezado = ["Hab", "Tipo Hab", "Reserva", "Cuenta", "Cod. Deb.", "Descripción", None, "Factura",
                  "Valor", "Documento", "Fecha", "Hora", "Usuario", "Designación"]
    periodo = [None, None, None, None, None, "Periodo de:", None, "01/09/2026", None, "hasta", "10/09/2026"]
    filas = [[None, None, None, i, cod, "Pago", i, None, -monto, doc, f"{dia:02d}/09/2026"]
             for i, (cod, monto, doc, dia) in enumerate(pagos, 1)]
    return xlsx("bordero.xlsx", {"Hoja1": [periodo, encabezado] + filas})


class BorderoSinAbonoTests(SimpleTestCase):
    def procesar(self):
        bordero = bordero_dias([
            ("V$", 10000, "111", 3),    # crédito del 03: viene en el reporte
            ("MC$", 20000, "222", 3),   # crédito del 03 sin abono: se lista
            ("MC$", 25000, "333", 5),   # crédito del 05: el reporte no trae crédito de ese día
            ("RCO", 5000, "444", 5),    # débito del 05: viene en el reporte
            ("RCO", 6000, "555", 5),    # débito del 05 sin abono: se lista
            ("RCO", 7000, "666", 9),    # débito de otro día: se omite
        ])
        reporte = tbk_cuotas("abonos.xlsx", "08 septiembre 2026", [
            ("03 septiembre 2026", "S/C", 10000, 10000, "000111", "1"),
        ])
        # El ayudante solo genera ventas a crédito: se agrega una de débito del 05.
        libro = load_workbook(reporte)
        hoja = libro.active
        hoja.append(fila(32, c1="05 septiembre 2026", c2="Venta", c5="Débito", c6=5000, c8="Normal", c9="S/C",
                         c10=5000, c11=0, c13=5000, c24="4513 68** **** 6158", c25="000444", c28="2", c30="1"))
        salida = io.BytesIO()
        libro.save(salida)
        archivo = SimpleUploadedFile("abonos.xlsx", salida.getvalue())
        return logica_clp.procesar({"bordero": [bordero], "transbank": [archivo]})

    def test_lista_solo_las_fechas_de_cada_tipo_de_pago(self):
        resultado, reportes = self.procesar()
        resumen = resultado["resumen"]
        self.assertEqual(resumen["conciliadas"], 2)
        self.assertEqual(resumen["bordero_pendiente"], 2)
        self.assertEqual(resumen["bordero_sin_cobertura"], 2)
        self.assertEqual(resumen["cobertura"], "Crédito: 03-09 · Débito y prepago: 05-09")
        hoja = load_workbook(io.BytesIO(reportes[2][4])).active
        documentos = [hoja.cell(row=r, column=4).value for r in range(5, hoja.max_row + 1)]
        self.assertEqual(sorted(documentos), ["222", "555"])
        self.assertIn("Se omitieron 2 pagos de otras fechas", hoja["A2"].value)

    def test_aviso_en_pantalla(self):
        resultado, _ = self.procesar()
        html = Template('{% include "conciliacion/_resultado_clp.html" %}').render(Context(resultado))
        self.assertIn("2 pagos del BORDERO de fechas que no traen los reportes de Transbank", html)

    def test_prelectura_de_fechas_al_soltar(self):
        reporte = tbk_cuotas("abonos.xlsx", "08 septiembre 2026", [
            ("03 septiembre 2026", "S/C", 10000, 10000, "000111", "1"),
            ("04 septiembre 2026", "S/C", 20000, 20000, "000222", "2"),
            ("20 agosto 2026", "3/3", 90000, 30000, "000333", "3"),  # cuota antigua: no cuenta
        ])
        self.assertEqual(logica_clp.describir(reporte, "transbank"), "ventas de Crédito: 03-09 al 04-09")
        self.assertEqual(logica_clp.describir(bordero_dias([("V$", 1, "1", 3)]), "bordero"), "del 01-09-2026 al 10-09-2026")


# ---------------------------------------------------------------------------
# Errores: direcciones que no existen, acciones abiertas en el navegador, sesión, base de datos
# ---------------------------------------------------------------------------
class ErroresTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026")
        self.client.force_login(self.usuario)

    def conciliar(self):
        return self.client.post("/conciliacion/pesos/", {
            "bordero": bordero_clp(PAGOS_MIXTOS), "transbank": [transbank("tbk.xlsx", VENTAS_MIXTAS)],
        })

    def test_conciliacion_que_no_existe(self):
        respuesta = self.client.get("/conciliacion/historial/999/", follow=True)
        self.assertRedirects(respuesta, "/conciliacion/historial/")
        self.assertContains(respuesta, "La conciliación N° 999 no existe o fue borrada del historial.")

    def test_descarga_que_no_existe(self):
        detalle = self.conciliar()["Location"]
        pk = Conciliacion.objects.get().pk
        respuesta = self.client.get(f"/conciliacion/historial/{pk}/descargar/otra-cosa/", follow=True)
        self.assertRedirects(respuesta, detalle)
        self.assertContains(respuesta, "Ese reporte no existe para esta conciliación")
        respuesta = self.client.get("/conciliacion/historial/999/descargar/completa/", follow=True)
        self.assertRedirects(respuesta, "/conciliacion/historial/")

    def test_acciones_abiertas_en_el_navegador_vuelven_a_su_pagina(self):
        for url, destino in [
            ("/conciliacion/pesos/ejemplo/", "/conciliacion/pesos/"),
            ("/conciliacion/pesos/identificar/", "/conciliacion/pesos/"),
            ("/conciliacion/ejemplo/", "/conciliacion/"),
            ("/conciliacion/identificar/", "/conciliacion/"),
            ("/conciliacion/historial/borrar/", "/conciliacion/historial/"),
        ]:
            self.assertRedirects(self.client.get(url), destino, fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/usuarios/logout/"), "/")
        self.assertEqual(self.client.get("/").status_code, 200)  # sigue con la sesión iniciada

    def test_sesion_terminada_avisa_en_el_login(self):
        self.client.logout()
        respuesta = self.client.get("/conciliacion/pesos/", follow=True)
        self.assertContains(respuesta, "Inicia sesión para continuar")

    def test_falla_al_guardar_en_la_base(self):
        from django.db import OperationalError
        with mock.patch("apps.conciliacion.registro.guardar", side_effect=OperationalError("database is locked")):
            respuesta = self.conciliar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "no se pudo guardar la conciliación en el historial")
        self.assertFalse(Conciliacion.objects.exists())

    def test_prelectura_de_un_archivo_danado_no_falla(self):
        self.assertEqual(logica_clp.describir(texto("roto.xls", "\x00\x01 basura"), "transbank"), "")


@override_settings(DEBUG=False)
class PaginasDeErrorTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026")

    def test_404(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get("/no-existe/")
        self.assertEqual(respuesta.status_code, 404)
        self.assertContains(respuesta, "No encontramos esta página", status_code=404)
        self.assertContains(respuesta, "Ir al inicio", status_code=404)

    def test_500(self):
        self.client.force_login(self.usuario)
        self.client.raise_request_exception = False
        with mock.patch("apps.conciliacion.views.Paginator", side_effect=RuntimeError("falla")):
            respuesta = self.client.get("/conciliacion/historial/")
        self.assertEqual(respuesta.status_code, 500)
        self.assertContains(respuesta, "Ocurrió un error inesperado", status_code=500)

    def test_formulario_vencido(self):
        cliente = self.client_class(enforce_csrf_checks=True)
        respuesta = cliente.post("/usuarios/login/", {"email": "prueba@hotel.cl", "password": "x"})
        self.assertEqual(respuesta.status_code, 403)
        self.assertContains(respuesta, "No se pudo enviar el formulario", status_code=403)


class BorrarHistorialTests(TestCase):
    def setUp(self):
        # Borrar del historial es solo para administradores (staff sin perfil asignado = Administrador).
        self.usuario = User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026", is_staff=True)
        self.client.force_login(self.usuario)
        self.pesos = [Conciliacion.objects.create(moneda=Conciliacion.PESOS) for _ in range(3)]
        self.dolares = Conciliacion.objects.create(moneda=Conciliacion.DOLARES)

    def test_historial_muestra_casillas_y_botones(self):
        pagina = self.client.get("/conciliacion/historial/")
        self.assertContains(pagina, 'name="ids"', count=4)
        self.assertContains(pagina, "Borrar seleccionadas")
        self.assertContains(pagina, "Borrar todas (4)")
        self.assertContains(self.client.get("/conciliacion/historial/?moneda=CLP"), "Borrar todas las de pesos (3)")

    def test_primer_paso_muestra_lo_seleccionado_sin_borrar(self):
        a, b = self.pesos[0].pk, self.dolares.pk
        respuesta = self.client.post("/conciliacion/historial/borrar/", {"ids": [a, b]})
        self.assertContains(respuesta, "Se borrarán 2 conciliaciones")
        self.assertContains(respuesta, f'value="{b},{a}"')
        self.assertEqual(Conciliacion.objects.count(), 4)

    def test_sin_seleccion_no_avanza(self):
        respuesta = self.client.post("/conciliacion/historial/borrar/", {}, follow=True)
        self.assertContains(respuesta, "Selecciona al menos una conciliación para borrar.")

    def test_sin_marcar_entiendo_no_borra(self):
        respuesta = self.client.post("/conciliacion/historial/borrar/confirmar/", {"ids": str(self.pesos[0].pk)}, follow=True)
        self.assertContains(respuesta, "No se borró nada")
        self.assertEqual(Conciliacion.objects.count(), 4)

    def test_borra_solo_las_confirmadas_y_lo_verifica(self):
        a, b = self.pesos[0].pk, self.pesos[1].pk
        respuesta = self.client.post("/conciliacion/historial/borrar/confirmar/",
                                     {"ids": f"{a},{b},999", "entiendo": "1"}, follow=True)
        self.assertContains(respuesta, f"Se borraron 2 conciliaciones del historial (N° {a}, N° {b}). Se verificó que ya no están.")
        self.assertContains(respuesta, "Ya no estaban en el historial: N° 999.")
        self.assertEqual(set(Conciliacion.objects.values_list("pk", flat=True)), {self.pesos[2].pk, self.dolares.pk})

    def test_borrar_todas_respeta_el_filtro_de_moneda(self):
        respuesta = self.client.post("/conciliacion/historial/borrar/", {"todas": "1", "moneda": "CLP"})
        self.assertContains(respuesta, "todas las de pesos")
        ids = respuesta.context["ids"]
        respuesta = self.client.post("/conciliacion/historial/borrar/confirmar/",
                                     {"ids": ids, "entiendo": "1", "moneda": "CLP"})
        self.assertRedirects(respuesta, "/conciliacion/historial/?moneda=CLP", fetch_redirect_response=False)
        self.assertEqual(list(Conciliacion.objects.values_list("moneda", flat=True)), [Conciliacion.DOLARES])

    def test_una_conciliacion_nueva_no_se_borra_aunque_se_haya_elegido_borrar_todas(self):
        ids = self.client.post("/conciliacion/historial/borrar/", {"todas": "1"}).context["ids"]
        nueva = Conciliacion.objects.create(moneda=Conciliacion.PESOS)
        self.client.post("/conciliacion/historial/borrar/confirmar/", {"ids": ids, "entiendo": "1"})
        self.assertEqual(list(Conciliacion.objects.values_list("pk", flat=True)), [nueva.pk])

    def test_abrir_las_direcciones_en_el_navegador_vuelve_al_historial(self):
        for url in ("/conciliacion/historial/borrar/", "/conciliacion/historial/borrar/confirmar/"):
            self.assertRedirects(self.client.get(url), "/conciliacion/historial/")
        self.assertEqual(Conciliacion.objects.count(), 4)


# ---------------------------------------------------------------------------
# Resumen gráfico de cada conciliación
# ---------------------------------------------------------------------------
class GraficosTests(SimpleTestCase):
    def datos_clp(self, ventas):
        return logica_clp.procesar({"bordero": bordero_clp(PAGOS_MIXTOS), "transbank": [transbank("tbk.xlsx", ventas)]})[0]

    def test_la_conciliacion_guarda_los_totales_para_los_graficos(self):
        r = self.datos_clp(VENTAS_MIXTAS)
        g = r["graficos"]
        self.assertEqual(g["estados"]["conciliado"][0], 4)
        self.assertEqual({m["nombre"] for m in g["medios"]}, {"Crédito", "Débito", "Prepago"})
        self.assertEqual(sum(d["ventas"] for d in g["dias"]), 4)
        self.assertEqual(g["mayores"], [])
        vista = graficos.preparar(r, "CLP")
        self.assertEqual(vista["total_ventas"], 4)
        self.assertEqual(vista["medios"], [])  # nada por revisar: no hay barras
        self.assertIn("No hay montos por revisar", vista["hallazgos"][0])

    def test_frases_y_barras_con_casos_por_revisar(self):
        datos = {
            "version": 1,
            "estados": {"conciliado": [8, 80000], "diferencia": [1, 10000], "sin_registro": [3, 30000]},
            "medios": [
                {"nombre": "Crédito", "ventas": 6, "monto": 60000, "revisar_n": 3, "revisar_monto": 30000},
                {"nombre": "Débito", "ventas": 6, "monto": 60000, "revisar_n": 1, "revisar_monto": 500},
            ],
            "dias": [
                {"fecha": "2026-09-04", "ventas": 6, "monto": 60000, "revisar_n": 0, "revisar_monto": 0},
                {"fecha": "2026-09-05", "ventas": 6, "monto": 60000, "revisar_n": 4, "revisar_monto": 30500},
            ],
            "mayores": [{"fecha": "05-09-2026", "medio": "Crédito", "codigo": "A1", "monto": 10000,
                         "por_revisar": 10000, "estado": "sin_registro"}],
        }
        vista = graficos.preparar({"graficos": datos}, "CLP")
        self.assertEqual([e["clave"] for e in vista["estados"]], ["conciliado", "diferencia", "sin_registro"])
        self.assertEqual(vista["medios"][0]["nombre"], "Crédito")
        self.assertEqual(vista["medios"][0]["ancho"], 100)
        self.assertTrue(vista["dias"][0]["limpio"])
        self.assertTrue(vista["dias"][1]["pico"])
        self.assertEqual(vista["mayores"][0]["revisar_texto"], "$ 10.000")
        frases = " ".join(vista["hallazgos"])
        self.assertIn("«sin registro en el BORDERO» (3)", frases)
        self.assertIn("Crédito concentra el 98% del monto por revisar ($ 30.000)", frases)
        self.assertIn("05-09-2026", frases)

    def test_muchas_ventas_fuera_del_periodo_se_avisan(self):
        datos = {"version": 1, "estados": {"conciliado": [5, 5000], "fuera_periodo": [5, 5000]},
                 "medios": [], "dias": [], "mayores": []}
        vista = graficos.preparar({"graficos": datos}, "CLP")
        self.assertIn("5 ventas (50%) son de fechas que el BORDERO cargado no cubre", " ".join(vista["hallazgos"]))

    def test_conciliacion_antigua_sin_graficos_usa_lo_guardado(self):
        r = self.datos_clp(VENTAS_MIXTAS)
        del r["graficos"]
        vista = graficos.preparar(r, "CLP")
        self.assertTrue(vista["sin_detalle"])
        self.assertEqual(vista["total_ventas"], 4)

    def test_dolares_en_formato_chileno(self):
        datos = {"version": 1, "estados": {"conciliada": [1, 10], "diferencia": [1, 1234.5]},
                 "medios": [{"nombre": "Visa", "ventas": 2, "monto": 1244.5, "revisar_n": 1, "revisar_monto": 1234.5}],
                 "dias": [], "mayores": []}
        vista = graficos.preparar({"graficos": datos}, "USD")
        self.assertEqual(vista["medios"][0]["revisar_texto"], "US$ 1.234,50")
        self.assertEqual(vista["nombre_medio"], "marca")

    def test_sin_ventas_no_hay_graficos(self):
        self.assertIsNone(graficos.preparar({"graficos": {"estados": {}, "medios": [], "dias": [], "mayores": []}}, "CLP"))


class GraficosPantallaTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026"))

    def test_el_detalle_muestra_el_resumen_grafico(self):
        resultado = logica_clp.procesar({"bordero": bordero_clp(PAGOS_MIXTOS), "transbank": [transbank("tbk.xlsx", VENTAS_MIXTAS)]})[0]
        from .registro import _a_json
        c = Conciliacion.objects.create(moneda=Conciliacion.PESOS, resultado=_a_json(resultado))
        pagina = self.client.get(f"/conciliacion/historial/{c.pk}/")
        self.assertContains(pagina, "Dónde mirar primero")
        self.assertContains(pagina, "Cómo quedaron las 4 ventas de Transbank")
        self.assertContains(pagina, "flex-grow: 4")  # sin coma decimal en los estilos
        self.assertContains(pagina, "js/graficos.js")


class ConciliadasConObservacionTests(TestCase):
    """Verde: conciliada con el mismo código (aunque tenga redondeo). Amarillo: código distinto o cruce por monto y fecha."""

    def cruzar(self, codigo_pago, monto_pago=10000):
        venta = {"codigo": "3538", "codigo_flex": "3538", "monto": 10000, "fecha": date(2026, 10, 29)}
        pago = {"codigo": codigo_pago, "codigo_flex": logica_clp._codigo_flexible(codigo_pago), "documento": codigo_pago,
                "monto": monto_pago, "fecha": date(2026, 10, 29), "cod": "RCO", "cuenta": "1"}
        logica_clp._cruzar([venta], [pago], (date(2026, 10, 1), date(2026, 10, 31)), 10, 3)
        return venta

    def test_redondeo_con_el_mismo_codigo_no_es_observacion(self):
        venta = self.cruzar("3538", 9995)
        self.assertEqual(venta["estado"], "conciliado")
        self.assertIn("Diferencia de redondeo", venta["nota"])
        self.assertFalse(logica_clp.con_observacion(venta))

    def test_cruce_por_monto_y_fecha_es_observacion(self):
        venta = self.cruzar("777777")
        self.assertIn("Cruzado por monto y fecha", venta["nota"])
        self.assertTrue(logica_clp.con_observacion(venta))

    def test_colores_en_la_tabla_de_ventas_por_revisar(self):
        self.client.force_login(User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026"))
        base = {"medio": "Débito", "fecha": "04-09-2026", "local": "", "autorizacion": "1", "tarjeta": "", "marca": "Visa",
                "banco": "", "pais": "", "monto": 1000, "monto_bordero": 1000, "diferencia": 0, "documento_bordero": "",
                "documento_distinto": False, "estado": "conciliado", "estado_texto": "Conciliado"}
        resultado = {"resumen": {"conciliadas": 2}, "observaciones": [
            {**base, "nota": "Diferencia de redondeo"},
            {**base, "nota": "Cruzado por monto y fecha: revisar código"},
        ]}
        c = Conciliacion.objects.create(moneda=Conciliacion.PESOS, resultado=resultado)
        pagina = self.client.get(f"/conciliacion/historial/{c.pk}/").content.decode()
        # Guardada antes de la v3.6.3: la de redondeo pasa al desplegable de diferencias aceptadas.
        self.assertIn("1 venta con el mismo código y una diferencia aceptada", pagina)

    def test_con_tolerancia_alta_las_diferencias_chicas_no_quedan_por_revisar(self):
        ventas = [("Crédito", 10000, 200, "000111", "9001"), ("Crédito", 20000, 400, "000222", "9002")]
        pagos = [("V$", 9995, "111"), ("MC$", 19300, "222")]  # $5 y $700 de diferencia
        archivos = {"bordero": bordero_clp(pagos), "transbank": [transbank("tbk.xlsx", ventas)]}
        r = logica_clp.procesar(archivos, parametros=Parametros(tolerancia_clp=1000))[0]
        self.assertEqual(r["observaciones"], [])
        self.assertEqual([f["nota"] for f in r["aceptadas"]], ["Diferencia de redondeo", "Diferencia dentro de la tolerancia"])
        self.assertEqual(r["resumen"]["por_revisar"], 0)


class PantallaDeProgresoTests(TestCase):
    """El envío desde la pantalla de progreso recibe la dirección del resultado en JSON."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("prueba", "prueba@hotel.cl", "Clave-Prueba-2026"))

    def datos(self):
        return {"bordero": bordero_clp(PAGOS_MIXTOS), "transbank": transbank("tbk.xlsx", VENTAS_MIXTAS)}

    def test_con_progreso_responde_la_direccion_del_resultado(self):
        respuesta = self.client.post("/conciliacion/pesos/", self.datos(), headers={"X-Progreso": "1"})
        self.assertEqual(respuesta.status_code, 200)
        url = respuesta.json()["url"]
        c = Conciliacion.objects.get()
        self.assertEqual(url, c.get_absolute_url())
        # El aviso «guardada en el historial» se muestra al abrir el resultado.
        self.assertContains(self.client.get(url), f"Conciliación N° {c.pk} guardada en el historial.")

    def test_sin_progreso_sigue_redirigiendo(self):
        respuesta = self.client.post("/conciliacion/pesos/", self.datos())
        self.assertEqual(respuesta.status_code, 302)

    def test_con_errores_devuelve_la_pagina(self):
        respuesta = self.client.post("/conciliacion/pesos/", {"transbank": transbank("tbk.xlsx", VENTAS_MIXTAS)},
                                     headers={"X-Progreso": "1"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta["Content-Type"].startswith("text/html"))

    def test_las_paginas_cargan_el_script_y_los_pasos(self):
        pagina = self.client.get("/conciliacion/pesos/")
        self.assertContains(pagina, "js/progreso.js")
        self.assertContains(pagina, 'data-progreso-pasos="Leyendo el BORDERO')


class FiltroHistorialTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("jefe", "jefe@hotel.cl", "Clave-Prueba-2026", is_staff=True))
        crear = Conciliacion.objects.create
        self.septiembre = crear(moneda=Conciliacion.PESOS, desde=date(2026, 9, 4), hasta=date(2026, 9, 7),
                                monto_por_revisar=1000)
        self.cruza_mes = crear(moneda=Conciliacion.PESOS, desde=date(2026, 9, 28), hasta=date(2026, 10, 3), cuadrado=True)
        self.octubre = crear(moneda=Conciliacion.DOLARES, desde=date(2026, 10, 10), hasta=date(2026, 10, 12),
                             monto_por_revisar=Decimal("12.5"))
        self.un_dia = crear(moneda=Conciliacion.PESOS, desde=None, hasta=date(2026, 11, 2))
        self.sin_periodo = crear(moneda=Conciliacion.PESOS)
        Conciliacion.objects.filter(pk=self.octubre.pk).update(creada=timezone.make_aware(datetime(2026, 11, 5, 10)))

    def numeros(self, **params):
        respuesta = self.client.get("/conciliacion/historial/", params)
        return sorted(c.pk for c in respuesta.context["pagina"].object_list)

    def test_por_periodo_incluye_las_que_tienen_algun_dia_en_el_rango(self):
        self.assertEqual(self.numeros(desde="2026-09-01", hasta="2026-09-30"), [self.septiembre.pk, self.cruza_mes.pk])
        self.assertEqual(self.numeros(desde="2026-10-01", hasta="2026-10-31"), [self.cruza_mes.pk, self.octubre.pk])
        self.assertEqual(self.numeros(desde="2026-11-01"), [self.un_dia.pk])  # solo con fecha de corte
        self.assertEqual(self.numeros(hasta="2026-09-05"), [self.septiembre.pk])

    def test_por_fecha_en_que_se_hizo(self):
        self.assertEqual(self.numeros(por="creada", desde="2026-11-05", hasta="2026-11-05"), [self.octubre.pk])

    def test_se_combina_con_la_moneda(self):
        self.assertEqual(self.numeros(desde="2026-10-01", hasta="2026-10-31", moneda="CLP"), [self.cruza_mes.pk])

    def test_fechas_invertidas_o_invalidas(self):
        respuesta = self.client.get("/conciliacion/historial/", {"desde": "2026-09-30", "hasta": "2026-09-01"})
        self.assertContains(respuesta, "se invirtieron")
        self.assertEqual(sorted(c.pk for c in respuesta.context["pagina"].object_list), [self.septiembre.pk, self.cruza_mes.pk])
        respuesta = self.client.get("/conciliacion/historial/", {"desde": "31-02-2026"})
        self.assertContains(respuesta, "no es válida")
        self.assertEqual(respuesta.context["total_filtro"], 5)

    def test_resumen_y_enlaces_conservan_el_filtro(self):
        pagina = self.client.get("/conciliacion/historial/", {"desde": "2026-09-01", "hasta": "2026-10-31"})
        self.assertContains(pagina, "3 conciliaciones")
        self.assertContains(pagina, "Pesos: 1 de 2 cuadradas · por revisar $ 1.000.")
        self.assertContains(pagina, "Dólares: 0 de 1 cuadrada · por revisar US$ 12,50.")
        self.assertContains(pagina, "por=periodo&amp;desde=2026-09-01&amp;hasta=2026-10-31&amp;moneda=USD")
        self.assertContains(pagina, "Borrar todas las filtradas (3)")
        self.assertContains(pagina, "Quitar fechas")

    def test_borrar_todas_respeta_las_fechas(self):
        filtro = {"todas": "1", "por": "periodo", "desde": "2026-09-01", "hasta": "2026-09-30"}
        confirmar = self.client.post("/conciliacion/historial/borrar/", filtro)
        self.assertContains(confirmar, "todas las del filtro")
        self.assertEqual(sorted(c.pk for c in confirmar.context["registros"]), [self.septiembre.pk, self.cruza_mes.pk])
        respuesta = self.client.post("/conciliacion/historial/borrar/confirmar/", {
            "ids": confirmar.context["ids"], "entiendo": "1", "por": "periodo", "desde": "2026-09-01", "hasta": "2026-09-30",
        })
        self.assertRedirects(respuesta, "/conciliacion/historial/?por=periodo&desde=2026-09-01&hasta=2026-09-30",
                             fetch_redirect_response=False)
        self.assertEqual(Conciliacion.objects.count(), 3)

    def test_sin_resultados(self):
        self.assertContains(self.client.get("/conciliacion/historial/", {"desde": "2020-01-01", "hasta": "2020-01-31"}),
                            "No hay conciliaciones con período conciliado en esas fechas")



# ---------------------------------------------------------------------------
# Excepciones (CU-04)
# ---------------------------------------------------------------------------
class ClasificarExcepcionesTests(SimpleTestCase):
    def fila(self, **cambios):
        base = {"estado": "sin_registro", "nota": "", "fecha": "04-09-2026", "medio": "Débito", "autorizacion": "425788",
                "documento_bordero": "", "monto": 663663, "monto_bordero": None, "diferencia": None, "tipo": "Venta"}
        base.update(cambios)
        return base

    def categoria(self, **cambios):
        return excepciones.desde_clp([self.fila(**cambios)])[0]

    def test_cada_caso_recibe_su_tipo_y_una_accion_con_sus_datos(self):
        e = self.categoria()
        self.assertEqual(e["categoria"], "sin_registro")
        self.assertEqual(e["sugerencia"], "Registrar la venta en el BORDERO.")

        e = self.categoria(estado="diferencia", monto=115204, monto_bordero=113700, diferencia=1504, nota="Mismo código, distinto monto")
        self.assertEqual(e["categoria"], "monto_distinto")
        self.assertEqual(e["sugerencia"], "Corregir el monto en el BORDERO o registrar el ajuste.")

        e = self.categoria(estado="conciliado", nota="Código digitado distinto en el BORDERO", autorizacion="HCOVGZ",
                           documento_bordero="HC0VGZ")
        self.assertEqual(e["categoria"], "digitacion")
        self.assertEqual(e["sugerencia"], "Corregir el código en el BORDERO: dice HC0VGZ, debe ser HCOVGZ.")

        self.assertEqual(self.categoria(estado="conciliado", nota="Cruzado por monto y fecha: revisar código")["categoria"], "codigo_distinto")
        self.assertEqual(self.categoria(estado="conciliado", nota="Mismo código y monto en otra fecha: revisar")["categoria"], "fecha_distinta")
        self.assertEqual(self.categoria(monto=-5000)["categoria"], "anulacion")
        self.assertEqual(self.categoria(tipo="Anulación")["categoria"], "anulacion")

    def test_diferencia_menor_sugiere_revisar_la_tolerancia(self):
        e = self.categoria(estado="diferencia", monto=10050, monto_bordero=10000, diferencia=50)
        self.assertEqual(e["sugerencia"], "Probable redondeo: evaluar subir la tolerancia.")
        usd = excepciones.desde_usd(
            [{"estado": "diferencia", "nota": "Diferencia de monto", "fecha_venta": "25/11/2025", "tipo_tarjeta": "VI",
              "codigo_autorizacion": "112194", "documento": "7001", "monto_original": 116, "monto_cartola": 116.11,
              "diferencia": -0.11}],
            {"VI": "Visa"}.get, float, logica_clp._fecha)[0]
        self.assertEqual(usd["sugerencia"], "Probable redondeo: evaluar subir la tolerancia.")

    def test_las_diferencias_aceptadas_no_son_excepciones(self):
        filas = [self.fila(estado="conciliado", nota="Diferencia de redondeo")]
        self.assertEqual(excepciones.desde_clp(filas), [])

    def test_cuotas_diferidas(self):
        cuotas = {"ventas": [{"fecha": "03-09-2026", "medio": "Crédito", "autorizacion": "659416", "monto_cuota": 206108,
                              "faltantes": [{"cuota": "2/3", "mes": "Octubre 2026", "en_periodo": False}]}]}
        e = excepciones.desde_clp([], cuotas)[0]
        self.assertEqual(e["categoria"], "cuota_diferida")
        self.assertEqual(e["sugerencia"], "Conciliar de nuevo incluyendo octubre 2026.")

    def test_el_motor_en_pesos_entrega_las_excepciones_y_el_excel_trae_la_accion(self):
        ventas = VENTAS_MIXTAS + [("Débito", 7000, 70, "000999", "9009")]
        r, reportes = logica_clp.procesar({"bordero": bordero_clp(PAGOS_MIXTOS), "transbank": [transbank("tbk.xlsx", ventas)]})
        self.assertEqual([(e["categoria"], e["codigo"]) for e in r["excepciones"]], [("sin_registro", "000999")])
        excel = dict((clave, contenido) for clave, _, _, _, contenido in reportes)["por_revisar"]
        hoja = load_workbook(io.BytesIO(excel)).active
        textos = [c.value for fila in hoja.iter_rows() for c in fila if c.value]
        self.assertIn("Acción sugerida", textos)
        self.assertIn("Registrar la venta en el BORDERO.", textos)


class GestionExcepcionesTests(TestCase):
    def setUp(self):
        from apps.usuarios import perfiles
        self.perfiles = perfiles
        self.analista = User.objects.create_user("ana", "ana@hotel.cl", "Clave-Prueba-2026")
        self.client.force_login(self.analista)
        resultado = logica_clp.procesar({
            "bordero": bordero_clp(PAGOS_MIXTOS),
            "transbank": [transbank("tbk.xlsx", VENTAS_MIXTAS + [("Débito", 7000, 70, "000999", "9009")])],
        })
        self.c = registro.guardar(Conciliacion.PESOS, self.analista, {}, {}, *resultado, False, 7000)
        self.e = self.c.excepciones.get()

    def gestionar(self, **datos):
        return self.client.post(f"/conciliacion/excepciones/{self.e.pk}/gestionar/",
                                {"estado": "pendiente", "categoria": self.e.categoria, "comentario": "", **datos}, follow=True)

    def test_al_guardar_la_conciliacion_se_crean_sus_excepciones(self):
        self.assertEqual(self.e.categoria, "sin_registro")
        self.assertEqual(self.e.estado, "pendiente")
        self.assertNotIn("excepciones", self.c.resultado)  # se guardan aparte, no en el JSON
        detalle = self.client.get(self.c.get_absolute_url())
        self.assertContains(detalle, "Acción sugerida:")
        self.assertContains(detalle, "Por gestionar (1)")

    def test_cambiar_estado_y_comentar(self):
        respuesta = self.gestionar(estado="resuelta", comentario="Registrada en el ERP con el documento 4455")
        self.assertContains(respuesta, "Excepción 000999 guardada: resuelta.")
        self.e.refresh_from_db()
        self.assertEqual(self.e.estado, "resuelta")
        self.assertEqual(self.e.actualizada_por, self.analista)
        self.assertRedirects(respuesta, f"{self.c.get_absolute_url()}#excepcion-{self.e.pk}")

    def test_reclasificar_pide_comentario_y_cambia_la_sugerencia(self):
        respuesta = self.gestionar(categoria="anulacion")
        self.assertContains(respuesta, "explica en el comentario el antecedente")
        self.e.refresh_from_db()
        self.assertEqual(self.e.categoria, "sin_registro")
        self.gestionar(categoria="anulacion", comentario="Es una nota de crédito del 05-09")
        self.e.refresh_from_db()
        self.assertEqual(self.e.categoria, "anulacion")
        self.assertTrue(self.e.reclasificada)
        self.assertEqual(self.e.sugerencia, "Verificar que la venta y su anulación estén en el BORDERO.")

    def test_el_contador_ve_pero_no_gestiona(self):
        contador = User.objects.create_user("conta", "conta@hotel.cl", "Clave-Prueba-2026")
        self.perfiles.asignar_perfil(contador, self.perfiles.CONSULTA)
        self.client.force_login(contador)
        self.assertNotContains(self.client.get(self.c.get_absolute_url()), "Gestionar")
        self.gestionar(estado="resuelta")
        self.e.refresh_from_db()
        self.assertEqual(self.e.estado, "pendiente")

    def test_modulo_general_con_filtros(self):
        pagina = self.client.get("/conciliacion/excepciones/")
        self.assertContains(pagina, 'Por gestionar <span class="filtro__n">1</span>')
        self.assertContains(pagina, 'Venta sin registro contable <span class="filtro__n">1</span>')
        self.assertContains(pagina, "1 excepción</strong> por gestionar")
        self.assertContains(pagina, f"Conciliación N° {self.c.pk}")
        self.gestionar(estado="resuelta")
        self.assertContains(self.client.get("/conciliacion/excepciones/"), "No hay excepciones por gestionar")
        self.assertContains(self.client.get("/conciliacion/excepciones/", {"estado": "resuelta"}), "000999")

    def test_el_menu_muestra_cuantas_hay_por_gestionar(self):
        self.assertContains(self.client.get("/"), 'title="1 por gestionar"')

    def test_al_borrar_la_conciliacion_se_borran_sus_excepciones(self):
        self.c.delete()
        self.assertFalse(Excepcion.objects.exists())


class ExcepcionesAlConciliarDeNuevoTests(TestCase):
    """Conciliar de nuevo el mismo período no duplica las excepciones: la nueva hereda la gestión."""

    def conciliar(self, usuario):
        resultado = logica_clp.procesar({
            "bordero": bordero_clp(PAGOS_MIXTOS),
            "transbank": [transbank("tbk.xlsx", VENTAS_MIXTAS + [("Débito", 7000, 70, "000999", "9009")])],
        })
        return registro.guardar(Conciliacion.PESOS, usuario, {}, {}, *resultado, False, 7000)

    def test_la_nueva_hereda_estado_y_comentario_y_la_anterior_deja_de_contar(self):
        usuario = User.objects.create_user("ana", "ana@hotel.cl", "Clave-Prueba-2026")
        primera = self.conciliar(usuario)
        vieja = primera.excepciones.get()
        vieja.estado, vieja.comentario = Excepcion.EN_REVISION, "Consultado con recepción"
        vieja.save()

        segunda = self.conciliar(usuario)
        nueva = segunda.excepciones.get()
        vieja.refresh_from_db()
        self.assertFalse(vieja.vigente)
        self.assertEqual(vieja.reemplazada_por, segunda)
        self.assertEqual((nueva.estado, nueva.comentario), (Excepcion.EN_REVISION, "Consultado con recepción"))
        self.assertEqual(Excepcion.objects.filter(vigente=True).count(), 1)

        self.client.force_login(usuario)
        self.assertContains(self.client.get("/conciliacion/excepciones/"), 'Por gestionar <span class="filtro__n">1</span>')
        detalle_viejo = self.client.get(primera.get_absolute_url())
        self.assertContains(detalle_viejo, f"Ver en la conciliación N° {segunda.pk}")
        # Gestionar la antigua lleva a la vigente.
        respuesta = self.client.post(f"/conciliacion/excepciones/{vieja.pk}/gestionar/",
                                     {"estado": "resuelta", "categoria": vieja.categoria, "comentario": ""})
        self.assertRedirects(respuesta, segunda.get_absolute_url(), fetch_redirect_response=False)


class ExportarExcepcionesTests(TestCase):
    """CU-05: reporte de excepciones en PDF ejecutivo y Excel multilote."""

    def setUp(self):
        from apps.usuarios import perfiles
        self.contador = User.objects.create_user("conta", "conta@hotel.cl", "Clave-Prueba-2026")
        perfiles.asignar_perfil(self.contador, perfiles.CONSULTA)  # el actor del CU-05 es el Contador
        self.client.force_login(self.contador)
        resultado = logica_clp.procesar({
            "bordero": bordero_clp(PAGOS_MIXTOS),
            "transbank": [transbank("tbk.xlsx", VENTAS_MIXTAS + [("Débito", 7000, 70, "000999", "9009")])],
        })
        self.c = registro.guardar(Conciliacion.PESOS, self.contador, {}, {}, *resultado, False, 7000)

    def exportar(self, **params):
        return self.client.get("/conciliacion/excepciones/exportar/", params)

    def test_pdf_de_una_conciliacion(self):
        respuesta = self.exportar(conciliacion=self.c.pk, estado="todas", formato="pdf")
        self.assertEqual(respuesta["Content-Type"], "application/pdf")
        self.assertIn(f'excepciones_conciliacion_{self.c.pk}.pdf', respuesta["Content-Disposition"])
        self.assertTrue(respuesta.content.startswith(b"%PDF"))

    def test_excel_multilote_con_codigo_monto_y_accion(self):
        respuesta = self.exportar(formato="xlsx")
        libro = load_workbook(io.BytesIO(respuesta.content))
        self.assertEqual(libro.sheetnames, ["Resumen", "Excepciones"])
        hoja = libro["Excepciones"]
        encabezado = [c.value for c in hoja[1]]
        fila = dict(zip(encabezado, [c.value for c in hoja[2]]))
        self.assertEqual(fila["N° conciliación"], self.c.pk)
        self.assertEqual(fila["Código autorización"], "000999")
        self.assertEqual(fila["Monto Transbank"], 7000)
        self.assertEqual(fila["Acción sugerida"], "Registrar la venta en el BORDERO.")

    def test_sin_excepciones_dice_cuadratura_limpia(self):
        respuesta = self.exportar(formato="xlsx", desde="2020-01-01", hasta="2020-01-31")
        resumen = load_workbook(io.BytesIO(respuesta.content))["Resumen"]
        textos = [c.value for fila in resumen.iter_rows() for c in fila if c.value]
        self.assertTrue(any("Cuadratura 100 % limpia" in str(t) for t in textos))
        self.assertTrue(self.exportar(formato="pdf", estado="resuelta").content.startswith(b"%PDF"))

    def test_respeta_los_filtros(self):
        resumen = load_workbook(io.BytesIO(self.exportar(formato="xlsx", estado="resuelta").content))["Excepciones"]
        self.assertEqual(resumen.max_row, 2)  # solo la nota de cuadratura limpia
        self.assertIn("Cuadratura 100 % limpia", resumen.cell(2, 1).value)

    def test_botones_en_el_modulo_y_en_el_detalle(self):
        self.assertContains(self.client.get("/conciliacion/excepciones/"), "formato=pdf")
        self.assertContains(self.client.get(self.c.get_absolute_url()), f"conciliacion={self.c.pk}&amp;estado=todas&amp;formato=xlsx")

    def test_conciliacion_inexistente(self):
        respuesta = self.exportar(conciliacion=9999, formato="pdf", follow=True)
        self.assertRedirects(respuesta, "/conciliacion/historial/")

    def test_filtro_por_fecha_de_venta_en_el_modulo(self):
        self.assertContains(self.client.get("/conciliacion/excepciones/", {"desde": "2026-09-01", "hasta": "2026-09-30"}), "000999")
        self.assertContains(self.client.get("/conciliacion/excepciones/", {"desde": "2020-01-01", "hasta": "2020-01-31"}),
                            "No hay excepciones por gestionar con este filtro")


class DocumentosEnPdfTests(TestCase):
    """Los documentos de cada conciliación también se bajan en PDF (uno o todos juntos)."""

    def setUp(self):
        self.usuario = User.objects.create_user("ana", "ana@hotel.cl", "Clave-Prueba-2026")
        self.client.force_login(self.usuario)
        resultado, reportes = logica_clp.procesar({
            "bordero": bordero_clp(PAGOS_MIXTOS),
            "transbank": [transbank("tbk.xlsx", VENTAS_MIXTAS + [("Débito", 7000, 70, "000999", "9009")])],
        })
        self.c = registro.guardar(Conciliacion.PESOS, self.usuario, {}, {}, resultado, reportes, False, 7000)

    def test_un_documento_en_pdf(self):
        respuesta = self.client.get(f"/conciliacion/historial/{self.c.pk}/descargar/por_revisar/pdf/")
        self.assertEqual(respuesta["Content-Type"], "application/pdf")
        self.assertIn(f"conciliacion_clp_por_revisar_{self.c.pk}.pdf", respuesta["Content-Disposition"])
        self.assertTrue(respuesta.content.startswith(b"%PDF"))

    def test_todos_los_documentos_en_un_pdf(self):
        respuesta = self.client.get(f"/conciliacion/historial/{self.c.pk}/pdf/")
        self.assertIn(f"conciliacion_pesos_{self.c.pk}.pdf", respuesta["Content-Disposition"])
        self.assertTrue(respuesta.content.startswith(b"%PDF"))

    def test_textos_y_sumas_del_excel(self):
        from openpyxl import Workbook as Libro
        from . import pdf_documentos
        libro = Libro()
        ws = libro.active
        ws["A1"] = "Título"
        ws.append([])
        ws.append(["Medio", "monto_original"])
        ws.append(["Débito", 1500])
        ws.append(["Crédito", 2500])
        ws.append(["Total", "=SUM(B4:B5)"])
        ws["B4"].number_format = ws["B5"].number_format = ws["B6"].number_format = '"$"#,##0'
        bloques = pdf_documentos._bloques(ws, "CLP")
        self.assertEqual(bloques[0], ("titulo", "Título"))
        tabla = bloques[1][1][0]
        self.assertEqual(tabla[-1][1], ("$ 4.000", True))
        self.assertEqual(pdf_documentos._encabezado("monto_original"), "Monto Transbank")

    def test_botones_en_el_detalle(self):
        pagina = self.client.get(self.c.get_absolute_url())
        self.assertNotContains(pagina, "Todo en un PDF")
        self.assertContains(pagina, f"/conciliacion/historial/{self.c.pk}/descargar/por_revisar/pdf/")

    def test_sin_reportlab_avisa_en_vez_de_descargar_una_pagina(self):
        import builtins
        importar = builtins.__import__

        def sin_reportlab(nombre, *args, **kwargs):
            if nombre.startswith("reportlab") or nombre.endswith("pdf_documentos") or (args and args[2] and "pdf_documentos" in args[2]):
                raise ImportError(nombre)
            return importar(nombre, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=sin_reportlab):
            respuesta = self.client.get(f"/conciliacion/historial/{self.c.pk}/pdf/")
        self.assertRedirects(respuesta, self.c.get_absolute_url(), fetch_redirect_response=False)
        self.assertContains(self.client.get(self.c.get_absolute_url()), "falta instalar la librería «reportlab»")

    def test_el_aviso_nombra_la_libreria_que_falta(self):
        from .views import _sin_pdf
        self.assertIn("«pillow»", _sin_pdf(ModuleNotFoundError("No module named 'PIL'", name="PIL")))
        self.assertIn("pip install charset-normalizer",
                      _sin_pdf(ModuleNotFoundError("x", name="charset_normalizer")))


class GestionarVariasTests(TestCase):
    """Cambiar el estado de varias excepciones a la vez, con una observación para todas."""

    def setUp(self):
        self.analista = User.objects.create_user("ana", "ana@hotel.cl", "Clave-Prueba-2026")
        self.client.force_login(self.analista)
        ventas = VENTAS_MIXTAS + [("Débito", 7000, 70, "000999", "9009"), ("Débito", 8000, 80, "000888", "9008"),
                                  ("Débito", 9000, 90, "000777", "9007")]
        resultado = logica_clp.procesar({"bordero": bordero_clp(PAGOS_MIXTOS), "transbank": [transbank("tbk.xlsx", ventas)]})
        self.c = registro.guardar(Conciliacion.PESOS, self.analista, {}, {}, *resultado, False, 24000)
        self.e1, self.e2, self.e3 = self.c.excepciones.order_by("orden")
        self.e1.comentario = "Revisado con recepción"
        self.e1.save()

    def enviar(self, ids, **datos):
        return self.client.post("/conciliacion/excepciones/gestionar-varias/",
                                {"ids": [str(i) for i in ids], "next": "/conciliacion/excepciones/", **datos}, follow=True)

    def test_cambia_el_estado_y_agrega_la_observacion_sin_borrar_la_anterior(self):
        respuesta = self.enviar([self.e1.pk, self.e2.pk], estado="resuelta", comentario="Corregidas en el ERP")
        self.assertContains(respuesta, "Se actualizaron 2 excepciones: resuelta, con la observación.")
        self.e1.refresh_from_db(); self.e2.refresh_from_db(); self.e3.refresh_from_db()
        self.assertEqual((self.e1.estado, self.e2.estado, self.e3.estado), ("resuelta", "resuelta", "pendiente"))
        self.assertEqual(self.e1.comentario, "Revisado con recepción\nCorregidas en el ERP")
        self.assertEqual(self.e2.comentario, "Corregidas en el ERP")
        self.assertEqual(self.e2.actualizada_por, self.analista)

    def test_sin_observacion_solo_cambia_el_estado(self):
        self.enviar([self.e3.pk], estado="en_revision")
        self.e3.refresh_from_db()
        self.assertEqual((self.e3.estado, self.e3.comentario), ("en_revision", ""))

    def test_validaciones(self):
        self.assertContains(self.enviar([], estado="resuelta"), "Selecciona al menos una excepción.")
        self.assertContains(self.enviar([self.e1.pk], estado="otra"), "Elige el nuevo estado")
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.estado, "pendiente")

    def test_el_contador_no_puede(self):
        from apps.usuarios import perfiles
        contador = User.objects.create_user("conta", "conta@hotel.cl", "Clave-Prueba-2026")
        perfiles.asignar_perfil(contador, perfiles.CONSULTA)
        self.client.force_login(contador)
        self.assertNotContains(self.client.get("/conciliacion/excepciones/"), "data-seleccion-excepcion")
        self.enviar([self.e1.pk], estado="resuelta")
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.estado, "pendiente")

    def test_casillas_y_ventana_en_el_modulo_y_en_el_detalle(self):
        for url in ("/conciliacion/excepciones/", self.c.get_absolute_url()):
            pagina = self.client.get(url)
            self.assertContains(pagina, 'form="form-masivo"', count=3)
            self.assertContains(pagina, "Cambiar estado…")
