"""Pruebas de lectura de archivos, motor en dólares, cartolas en pesos y formato chileno.

Usan archivos sintéticos generados en memoria (el repositorio es público: no se
incluyen datos reales del hotel). Ejecutar con:

    python manage.py test apps.conciliacion
"""
import io
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import translation
from openpyxl import Workbook

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
