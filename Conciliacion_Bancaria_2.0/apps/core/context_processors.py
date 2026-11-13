from django.conf import settings

from apps.usuarios.perfiles import datos_plantilla


def app(request):
    """Datos comunes a todas las plantillas: versión y perfil del usuario."""
    datos = {"APP_VERSION": settings.APP_VERSION}
    datos.update(datos_plantilla(getattr(request, "user", None)))
    return datos
