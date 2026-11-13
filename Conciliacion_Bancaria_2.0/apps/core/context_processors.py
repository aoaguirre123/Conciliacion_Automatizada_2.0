from django.conf import settings
from django.db import DatabaseError

from apps.usuarios.perfiles import datos_plantilla


def app(request):
    """Datos comunes a todas las plantillas: versión, perfil del usuario y excepciones por gestionar."""
    datos = {"APP_VERSION": settings.APP_VERSION}
    usuario = getattr(request, "user", None)
    datos.update(datos_plantilla(usuario))
    datos["excepciones_abiertas"] = 0
    if usuario is not None and usuario.is_authenticated:
        from apps.conciliacion.models import Excepcion
        try:
            datos["excepciones_abiertas"] = Excepcion.objects.filter(
                vigente=True, estado__in=(Excepcion.PENDIENTE, Excepcion.EN_REVISION)
            ).count()
        except DatabaseError:
            pass
    return datos
