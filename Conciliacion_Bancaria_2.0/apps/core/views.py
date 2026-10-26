from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.conciliacion.dolar import obtener_serie_dolar
from apps.conciliacion.models import Conciliacion


def _saludo():
    hora = timezone.localtime().hour
    if hora < 12:
        return "Buenos días"
    if hora < 20:
        return "Buenas tardes"
    return "Buenas noches"


@login_required
def inicio(request):
    serie = obtener_serie_dolar()
    return render(request, "core/inicio.html", {
        "saludo": _saludo(),
        "dolar_hoy": serie[0] if serie else None,
        "ultimas": Conciliacion.objects.select_related("usuario").defer("resultado")[:5],
    })
