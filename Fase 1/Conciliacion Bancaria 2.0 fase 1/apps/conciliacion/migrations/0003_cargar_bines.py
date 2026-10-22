"""Carga la base de BIN (datos/bines.csv.gz) en la tabla BinTarjeta.

Fuente: https://github.com/venelinkochev/bin-list-data (licencia CC-BY-4.0).
"""
import csv
import gzip
from pathlib import Path

from django.db import migrations

ARCHIVO = Path(__file__).resolve().parent.parent / "datos" / "bines.csv.gz"
LOTE = 5000


def cargar(apps, schema_editor):
    BinTarjeta = apps.get_model("conciliacion", "BinTarjeta")
    BinTarjeta.objects.all().delete()
    with gzip.open(ARCHIVO, "rt", encoding="utf-8", newline="") as archivo:
        lote = []
        for fila in csv.DictReader(archivo):
            lote.append(BinTarjeta(**fila))
            if len(lote) == LOTE:
                BinTarjeta.objects.bulk_create(lote)
                lote = []
        BinTarjeta.objects.bulk_create(lote)


def vaciar(apps, schema_editor):
    apps.get_model("conciliacion", "BinTarjeta").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("conciliacion", "0002_tabla_bines"),
    ]

    operations = [
        migrations.RunPython(cargar, vaciar),
    ]
