# Conciliación bancaria - Hotel Plaza San Francisco

Proyecto Django nuevo e independiente. No reemplaza ni necesita archivos del proyecto anterior.

## Puesta en marcha (Windows)

Abre una terminal **dentro de esta carpeta** (`conciliacion_hsf`, la que tiene `manage.py`):

```
python -m venv entorno
entorno\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Abre http://127.0.0.1:8000/ e ingresa con el correo y la contraseña de tu usuario.

En macOS o Linux, activa el entorno con `source entorno/bin/activate`.

## Usuarios

`db.sqlite3` es la base del proyecto anterior, así que los usuarios existentes siguen
funcionando. El login pide **correo**, por lo que cada usuario debe tener un correo cargado.

Para crear un usuario nuevo: `python manage.py createsuperuser`, o desde
"Usuarios y permisos" en el menú (solo usuarios staff).

## Cómo comprobar que estás viendo esta versión

El pie de página dice **Conciliación bancaria v3.1**.

## Si ya tenías instalada la versión 3.0

Detén el servidor, reemplaza la carpeta completa por esta y corre una vez:

```
python manage.py migrate
```

Eso crea las tablas del historial. Tus usuarios se mantienen.

## Qué hace cada pantalla

- **En dólares**: ERP, Transbank, cartolas de Amex, Diners, Visa y Mastercard, y banco.
- **En pesos**: abonos de Transbank (crédito, débito y prepago) contra los pagos con
  tarjeta del BORDERO, y verificación del abono en la cartola.
- **Historial**: todas las conciliaciones guardadas, con su resultado y sus Excel.

En pesos, cada venta se identifica por el BIN de la tarjeta (6 primeros dígitos): marca,
tipo, banco emisor y país. Los datos vienen de `apps/conciliacion/datos/bines.csv.gz`
(fuente: https://github.com/venelinkochev/bin-list-data, licencia CC-BY-4.0) y se cargan
en la base con `python manage.py migrate`; la primera vez demora un poco más.
Para actualizar la base: `python apps/conciliacion/datos/preparar_bines.py bin-list-data.csv`
y una migración nueva que la vuelva a cargar.

## Estructura

```
config/                 configuración de Django
apps/core/              inicio
apps/usuarios/          login y cierre de sesión
apps/conciliacion/
    logica.py           conciliación en dólares y sus Excel
    logica_clp.py       conciliación en pesos contra el BORDERO y sus Excel
    models.py           historial (Conciliacion, Reporte) y BIN de tarjetas (BinTarjeta)
    registro.py         guarda cada conciliación en el historial
    dolar.py            dólar observado (mindicador.cl)
    bines.py            identificación de tarjetas por BIN
    datos/              bines.csv.gz (base de BIN) y preparar_bines.py
    views.py            pantallas, historial y descargas
templates/              HTML
static/css/app.css      única hoja de estilos
static/js/              app.js (menú) y conciliacion.js (carga de archivos)
```
