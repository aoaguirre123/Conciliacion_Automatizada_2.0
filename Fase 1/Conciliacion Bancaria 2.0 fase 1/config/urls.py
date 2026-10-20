from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("usuarios/", include("apps.usuarios.urls")),
    path("conciliacion/", include("apps.conciliacion.urls")),
]
