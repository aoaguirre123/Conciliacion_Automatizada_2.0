from django.urls import path

from . import views

app_name = "conciliacion"

urlpatterns = [
    path("", views.dolares, name="dolares"),
    path("identificar/", views.identificar_dolares, name="identificar_dolares"),
    path("ejemplo/", views.ejemplo_dolares, name="ejemplo_dolares"),
    path("dolar/", views.dolar, name="dolar"),
    path("pesos/", views.pesos, name="pesos"),
    path("pesos/identificar/", views.identificar_pesos, name="identificar_pesos"),
    path("pesos/ejemplo/", views.ejemplo_pesos, name="ejemplo_pesos"),
    path("historial/", views.historial, name="historial"),
    path("historial/borrar/", views.borrar_historial, name="borrar_historial"),
    path("historial/borrar/confirmar/", views.borrar_confirmado, name="borrar_confirmado"),
    path("historial/<int:pk>/", views.detalle, name="detalle"),
    path("historial/<int:pk>/descargar/<slug:clave>/", views.descargar, name="descargar"),
    path("excepciones/", views.excepciones, name="excepciones"),
    path("excepciones/<int:pk>/gestionar/", views.gestionar_excepcion, name="gestionar_excepcion"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("configuracion/restablecer/", views.restablecer_configuracion, name="restablecer_configuracion"),
]
