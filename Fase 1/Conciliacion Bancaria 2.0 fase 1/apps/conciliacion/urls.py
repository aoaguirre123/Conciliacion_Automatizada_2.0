from django.urls import path

from . import views



app_name = "conciliacion"

urlpatterns = [
    path("", views.procesamiento, name="conciliacion"),
    # path("logout/", views.cerrar_sesion, name="logout"),
]