from django.urls import path

from . import views

app_name = "conciliacion"

urlpatterns = [
    path("", views.dolares, name="dolares"),
    path("pesos/", views.pesos, name="pesos"),
    path("historial/", views.historial, name="historial"),
    path("historial/<int:pk>/", views.detalle, name="detalle"),
    path("historial/<int:pk>/descargar/<slug:clave>/", views.descargar, name="descargar"),
]
