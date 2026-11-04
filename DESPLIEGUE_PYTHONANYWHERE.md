# Publicar la aplicación en PythonAnywhere

En todos los pasos, reemplaza `TU_USUARIO` por tu nombre de usuario de PythonAnywhere.
La aplicación quedará en `https://TU_USUARIO.pythonanywhere.com`.

## 1. Crear la cuenta

Crea la cuenta en https://www.pythonanywhere.com. El plan gratuito ("Beginner") sirve para empezar.

## 2. Bajar el código

Abre **Consoles → Bash** y ejecuta:

```bash
git clone https://github.com/aoaguirre123/Conciliacion_Automatizada_2.0.git
```

Si el repositorio es privado, Git pide usuario y contraseña. En la contraseña pega un
*Personal Access Token* de GitHub (GitHub → Settings → Developer settings → Tokens), no tu clave.

## 3. Crear el entorno virtual e instalar las dependencias

En la misma consola:

```bash
mkvirtualenv conciliacion --python=python3.13
pip install -r ~/Conciliacion_Automatizada_2.0/Conciliacion_Bancaria_2.0/requirements.txt
```

Usa la versión de Python más nueva que ofrezca PythonAnywhere (3.12 o superior).
La instalación tarda unos minutos por pandas.

## 4. Base de datos fuera del repositorio

La base va en `~/datos`, fuera del repositorio. Así un `git pull` nunca la pisa.

```bash
mkdir -p ~/datos
cp ~/Conciliacion_Automatizada_2.0/Conciliacion_Bancaria_2.0/db.sqlite3 ~/datos/db.sqlite3
echo 'export DATABASE_URL=sqlite:////home/$USER/datos/db.sqlite3' >> $VIRTUAL_ENV/bin/postactivate
workon conciliacion
```

El `cp` es opcional: copia los usuarios y conciliaciones que ya están en la base del repositorio.
Si quieres partir con la base vacía, omítelo.

## 5. Preparar Django

```bash
cd ~/Conciliacion_Automatizada_2.0/Conciliacion_Bancaria_2.0
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

Si copiaste la base y ya tienes usuario, omite `createsuperuser`.

Genera una clave secreta y guárdala para el paso 7:

```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

## 6. Crear la aplicación web

1. Ve a la pestaña **Web** y elige **Add a new web app**.
2. Acepta el dominio `TU_USUARIO.pythonanywhere.com`.
3. Elige **Manual configuration** (no "Django"), con la misma versión de Python del paso 3.
4. En la sección **Virtualenv**, escribe `/home/TU_USUARIO/.virtualenvs/conciliacion`.
5. En **Static files**, agrega:
   - URL: `/static/`
   - Directory: `/home/TU_USUARIO/Conciliacion_Automatizada_2.0/Conciliacion_Bancaria_2.0/staticfiles`
6. En **Security**, activa **Force HTTPS**.

## 7. Archivo WSGI

En la pestaña **Web**, haz clic en el enlace del **WSGI configuration file**.
Borra todo el contenido y pega esto:

```python
import os
import sys

USUARIO = "TU_USUARIO"
RUTA = f"/home/{USUARIO}/Conciliacion_Automatizada_2.0/Conciliacion_Bancaria_2.0"
if RUTA not in sys.path:
    sys.path.insert(0, RUTA)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
os.environ["DJANGO_SECRET_KEY"] = "PEGA_AQUI_LA_CLAVE_DEL_PASO_5"
os.environ["DJANGO_DEBUG"] = "0"
os.environ["DJANGO_ALLOWED_HOSTS"] = f"{USUARIO}.pythonanywhere.com"
os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"] = f"https://{USUARIO}.pythonanywhere.com"
os.environ["DATABASE_URL"] = f"sqlite:////home/{USUARIO}/datos/db.sqlite3"

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
```

Guarda el archivo, vuelve a **Web** y presiona **Reload**.
Luego abre `https://TU_USUARIO.pythonanywhere.com`.

## Actualizar después de cada cambio en `main`

```bash
workon conciliacion
cd ~/Conciliacion_Automatizada_2.0
git pull
cd Conciliacion_Bancaria_2.0
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

Después presiona **Reload** en la pestaña **Web**.

## Si algo falla

- **Errores:** en la pestaña **Web** están los enlaces a **Error log** y **Server log**.
  El error real aparece al final del Error log.
- **Plan gratuito:**
  - Solo permite conexiones a internet hacia una lista de sitios autorizados.
    Si el valor del dólar observado (mindicador.cl o findic.cl) no carga, esa es la causa.
    Se soluciona con un plan pagado.
  - La aplicación se desactiva cada 3 meses si no la renuevas. Para mantenerla activa,
    presiona **Run until 3 months from today** en la pestaña **Web**.
- **Respaldo de la base:** descarga `~/datos/db.sqlite3` desde la pestaña **Files**.
