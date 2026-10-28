from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.conciliacion.dolar import fuente_elegida, fuente_otra
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
    return render(request, "core/inicio.html", {
        "fuente_otra": fuente_otra(fuente_elegida(request)),
        "saludo": _saludo(),
        "ultimas": Conciliacion.objects.select_related("usuario").defer("resultado")[:5],
    })
