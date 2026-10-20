"""Precarga los BIN de liquidaciones de Transbank, a un ritmo que respeta el límite de HandyAPI.

Uso: python manage.py identificar_bines "CREDITOS TBK 08-09.xlsx" "DEBITOS TBK 08-09.xlsx"
"""
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.conciliacion import bines, logica_clp
from apps.conciliacion.models import BinTarjeta


class Command(BaseCommand):
    help = "Consulta y guarda el banco, país y tipo de cada BIN de las liquidaciones de Transbank indicadas."

    def add_arguments(self, parser):
        parser.add_argument("archivos", nargs="+", help="Liquidaciones 'Abonos por día' de Transbank (.xlsx)")
        parser.add_argument("--pausa", type=float, default=7, help="Segundos entre consultas (por defecto 7)")

    def handle(self, *args, archivos, pausa, **opciones):
        encontrados = set()
        for ruta in archivos:
            try:
                with open(ruta, "rb") as archivo:
                    liquidacion = logica_clp.leer_transbank(archivo, Path(ruta).name)
            except (OSError, logica_clp.ArchivoInvalido) as exc:
                raise CommandError(f"{ruta}: {exc}") from exc
            encontrados |= {v["bin"] for v in liquidacion["ventas"] if v["bin"]}

        guardados = set(BinTarjeta.objects.filter(bin__in=encontrados).values_list("bin", flat=True))
        faltantes = sorted(encontrados - guardados)
        self.stdout.write(f"{len(encontrados)} BIN distintos; {len(guardados)} ya guardados, {len(faltantes)} por consultar.")

        for n, bin_ in enumerate(faltantes, start=1):
            datos = bines.identificar({bin_})[bin_]
            if not BinTarjeta.objects.filter(bin=bin_).exists():
                self.stderr.write(f"[{n}/{len(faltantes)}] {bin_}: la API no respondió o se agotó el cupo. Intenta más tarde.")
                return
            self.stdout.write(f"[{n}/{len(faltantes)}] {bin_}: {datos['marca']} {datos['tipo']} {datos['banco']} {datos['pais']}".rstrip())
            if n < len(faltantes):
                time.sleep(pausa)
        self.stdout.write(self.style.SUCCESS("Listo."))
