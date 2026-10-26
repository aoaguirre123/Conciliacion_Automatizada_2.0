"""Genera bines.csv.gz a partir de bin-list-data.csv (solo hace falta para actualizar la base).

Fuente: https://github.com/venelinkochev/bin-list-data (licencia CC-BY-4.0).
Uso:    python apps/conciliacion/datos/preparar_bines.py ruta/a/bin-list-data.csv

Deja solo las columnas que usa el sistema, con nombres y tipos normalizados, y lo
comprime (de ~27 MB a ~2 MB). Después de actualizar el archivo hay que crear una
migración nueva que vuelva a cargarlo (ver 0003_cargar_bines.py).
"""
import csv
import gzip
import sys
from pathlib import Path

DESTINO = Path(__file__).resolve().parent / "bines.csv.gz"
COLUMNAS = ["bin", "marca", "tipo", "nivel", "banco", "pais_codigo", "pais"]

MARCAS = {
    "VISA": "Visa", "MASTERCARD": "Mastercard", "AMERICAN EXPRESS": "Amex",
    "DINERS CLUB INTERNATIONAL": "Diners", "MAESTRO": "Maestro", "DISCOVER": "Discover",
    "CHINA UNION PAY": "UnionPay", "JCB": "JCB",
}
TIPOS = {"CREDIT": "Crédito", "DEBIT": "Débito", "CHARGE CARD": "Crédito"}


def normalizar(fila):
    marca = fila["Brand"].strip().upper()
    nivel = fila["Category"].strip().upper()
    return {
        "bin": fila["BIN"].strip(),
        # Marcas compartidas ("VISA/BANCONTACT", "JCB/RUPAY") cuentan por la principal.
        "marca": MARCAS.get(marca) or MARCAS.get(marca.split("/")[0]) or marca.title(),
        "tipo": "Prepago" if "PREPAID" in nivel else TIPOS.get(fila["Type"].strip().upper(), ""),
        "nivel": nivel.replace("PREPAID", "").strip().title(),
        "banco": fila["Issuer"].strip(),
        "pais_codigo": fila["isoCode2"].strip().upper(),
        "pais": fila["CountryName"].strip().title(),
    }


def main(origen):
    with open(origen, encoding="utf-8", newline="") as entrada, \
            gzip.open(DESTINO, "wt", encoding="utf-8", newline="", compresslevel=9) as salida:
        escritor = csv.DictWriter(salida, fieldnames=COLUMNAS)
        escritor.writeheader()
        filas = 0
        for fila in csv.DictReader(entrada):
            if len(fila["BIN"].strip()) == 6:
                escritor.writerow(normalizar(fila))
                filas += 1
    print(f"{filas} BIN guardados en {DESTINO} ({DESTINO.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
