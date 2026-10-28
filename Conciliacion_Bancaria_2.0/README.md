# Conciliación bancaria - Hotel Plaza San Francisco

Aplicación web Django para conciliar las ventas con tarjeta del hotel en pesos (CLP) y en dólares (USD).

## Puesta en marcha (Windows)

Abre una terminal **dentro de esta carpeta** (`Conciliacion_Bancaria_2.0`, la que tiene `manage.py`):

```
python -m venv entorno
entorno\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Abre http://127.0.0.1:8000/ e ingresa con el correo y la contraseña de tu usuario.

En macOS o Linux, activa el entorno con `source entorno/bin/activate`.

## Despliegue en Vercel

La carpeta que contiene este README es el **Root Directory** del proyecto en Vercel.
El archivo `vercel.json` y `api/index.py` ya están preparados para publicar Django
como una función Python.

1. Crea una base de datos PostgreSQL administrada (por ejemplo, Vercel Postgres,
   Neon o Supabase).
2. En Vercel, configura estas variables de entorno para **Production**, **Preview**
   y, si corresponde, **Development**:

   - `DJANGO_SECRET_KEY`: una clave aleatoria larga y privada.
   - `DJANGO_DEBUG=0`.
   - `DATABASE_URL`: la URL de conexión PostgreSQL proporcionada por tu proveedor.
   - `DJANGO_ALLOWED_HOSTS`: dominios adicionales separados por coma, si los tienes.
   - `DJANGO_CSRF_TRUSTED_ORIGINS`: URLs completas con `https://`, separadas por coma,
     para dominios personalizados.

   Vercel agrega automáticamente el dominio `*.vercel.app` a los hosts permitidos.
3. Ejecuta las migraciones contra esa base antes del primer uso:

   ```
   python manage.py migrate
   ```

   En Vercel se puede ejecutar desde el entorno local usando la misma `DATABASE_URL`.
   La migración de BIN tarda un poco más la primera vez.

SQLite se conserva como alternativa para desarrollo local, pero no debe usarse en
Vercel: el sistema de archivos de las funciones es efímero y no conserva usuarios,
historial ni reportes entre ejecuciones.

Los archivos subidos se procesan temporalmente durante la solicitud y no se guardan
como archivos en el servidor; el historial y los Excel generados se almacenan en la
base de datos.

## Usuarios

`db.sqlite3` es la base del proyecto anterior, así que los usuarios existentes siguen
funcionando. El login pide **correo**, por lo que cada usuario debe tener un correo cargado.

Para crear un usuario nuevo: `python manage.py createsuperuser`, o desde
"Usuarios y permisos" en el menú (solo usuarios staff).

## Cómo comprobar que estás viendo esta versión

El pie de página dice **Conciliación bancaria v3.3.0**.

## Al actualizar desde una versión anterior

Detén el servidor, actualiza el código, instala dependencias nuevas y aplica migraciones:

```
pip install -r requirements.txt
python manage.py migrate
```

Tus usuarios y el historial se mantienen.

## Qué hace cada pantalla

- **En dólares**: ERP (el BORDERO, con los pagos US$), Transbank, cuentas por cobrar de
  Amex, Diners, Visa y Mastercard, y banco. Transbank puede ser la liquidación antigua o el
  reporte «Abonos por día» en dólares con todos los medios de pago: la marca de cada venta
  (Visa, Mastercard, Amex, Diners) se obtiene del BIN de la tarjeta.
- Cada pantalla rechaza el reporte de Transbank de la otra moneda (campo «Moneda» del
  encabezado) con un mensaje que indica dónde cargarlo.
- **En pesos**: abonos de Transbank (crédito, débito y prepago) contra los pagos con
  tarjeta del BORDERO, y verificación del abono en la cartola. En la casilla de Transbank
  se cargan uno o varios reportes «Abonos por día»: separados por medio de pago o un solo
  archivo con los tres medios juntos. El medio se toma de la columna «Medio de pago» de
  cada venta; un archivo cargado dos veces, o una venta que aparece en dos archivos, se
  cuenta una sola vez. El abono se busca en la cartola por medio de pago o como abono
  conjunto (por ejemplo, débito + prepago en un solo depósito).
- **Historial**: todas las conciliaciones guardadas, con su resultado y sus Excel.

En pesos, cada venta se identifica por el BIN de la tarjeta (6 primeros dígitos): marca,
tipo, banco emisor y país. Los datos vienen de `apps/conciliacion/datos/bines.csv.gz`
(fuente: https://github.com/venelinkochev/bin-list-data, licencia CC-BY-4.0) y se cargan
en la base con `python manage.py migrate`; la primera vez demora un poco más.
Para actualizar la base: `python apps/conciliacion/datos/preparar_bines.py bin-list-data.csv`
y una migración nueva que la vuelva a cargar.

## Archivos que acepta

El formato se reconoce por el contenido, no por la extensión (ver `apps/conciliacion/lectura.py`):

- Excel `.xls`, `.xlsx` y `.xlsm`, con cualquier cantidad de filas y hojas.
- `.csv` separado por `;`, `,` o tabulador.
- `.xls` que en realidad son páginas HTML (exportaciones de portales web), con `lxml`.
- `.ods` de LibreOffice, con `odfpy`.

Cartolas bancarias reconocidas: **Banco de Chile** (`Abonos (CLP)` o `Abonos (USD)`) y
**BancoEstado** (`Depósitos / Abonos`, movimientos en la hoja «Movimientos»). La tabla se
busca por sus encabezados en todas las hojas, no por posición.

Los montos se muestran con formato chileno: punto para miles y coma para decimales
(`config/formatos/es_CL/formats.py`).

## Pruebas

```
python manage.py test apps.conciliacion
```

Usan archivos sintéticos generados en memoria; no se guardan datos reales del hotel en el repositorio.

## Estructura

```
config/                 configuración de Django (formatos/es_CL: miles con punto)
apps/core/              inicio
apps/usuarios/          login y cierre de sesión
apps/conciliacion/
    logica.py           conciliación en dólares y sus Excel
    logica_clp.py       conciliación en pesos contra el BORDERO y sus Excel
    models.py           historial (Conciliacion, Reporte) y BIN de tarjetas (BinTarjeta)
    registro.py         guarda cada conciliación en el historial
    dolar.py            dólar observado (mindicador.cl)
    bines.py            identificación de tarjetas por BIN
    lectura.py          lectura de planillas en cualquier formato (xls, xlsx, csv, html, ods)
    tests.py            pruebas automatizadas
    datos/              bines.csv.gz (base de BIN) y preparar_bines.py
    views.py            pantallas, historial y descargas
templates/              HTML
static/css/app.css      única hoja de estilos
static/js/              app.js (menú) y conciliacion.js (carga de archivos)
```
