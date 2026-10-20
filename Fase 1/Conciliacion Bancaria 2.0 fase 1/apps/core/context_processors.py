from django.conf import settings


def app(request):
    """Datos comunes a todas las plantillas."""
    return {"APP_VERSION": settings.APP_VERSION}
