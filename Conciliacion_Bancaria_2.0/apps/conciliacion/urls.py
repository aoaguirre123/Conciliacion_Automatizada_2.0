from django.urls import path

from . import views

app_name = "conciliacion"

urlpatterns = [
    path("", views.dolares, name="dolares"),
    path("identificar/", views.identificar_dolares, name="identificar_dolares"),
    path("dolar/", views.dolar, name="dolar"),
    path("pesos/", views.pesos, name="pesos"),
    path("pesos/identificar/", views.identificar_pesos, name="identificar_pesos"),
    path("historial/", views.historial, name="historial"),
    path("historial/<int:pk>/", views.detalle, name="detalle"),
    path("historial/<int:pk>/descargar/<slug:clave>/", views.descargar, name="descargar"),
]
