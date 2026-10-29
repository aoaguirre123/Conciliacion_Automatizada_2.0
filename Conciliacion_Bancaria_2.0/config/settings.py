"""Configuración del sistema de conciliación bancaria - Hotel Plaza San Francisco."""
import os
import shutil
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

ON_VERCEL = os.environ.get("VERCEL", "").lower() == "1"
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if ON_VERCEL else "1") == "1"
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-P(ZyLeDl0tx^UG1ZL_fVypVGoeb7bjh9+cP_8SmlnDKCx9M@j=",
)

configured_hosts = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
if ON_VERCEL:
    vercel_url = os.environ.get("VERCEL_URL", "")
    if vercel_url:
        configured_hosts.append(vercel_url.split(":", 1)[0])
    configured_hosts.append(".vercel.app")
ALLOWED_HOSTS = configured_hosts or ["127.0.0.1", "localhost"]

csrf_origins = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if ON_VERCEL:
    vercel_url = os.environ.get("VERCEL_URL", "")
    if vercel_url:
        csrf_origins.append(f"https://{vercel_url.split(':', 1)[0]}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.usuarios",
    "apps.conciliacion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.app",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if ON_VERCEL and not os.environ.get("DATABASE_URL"):
    # Vercel monta el código como solo lectura; el demo SQLite necesita una
    # copia temporal para poder crear sesiones y guardar conciliaciones.
    bundled_database = BASE_DIR / "db.sqlite3"
    demo_database = Path("/tmp/conciliacion-demo.sqlite3")
    if bundled_database.exists() and not demo_database.exists():
        demo_database.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_database, demo_database)
    database_url = f"sqlite:///{demo_database}"
else:
    database_url = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"

DATABASES = {
    "default": dj_database_url.config(
        default=database_url,
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "usuarios:login"
LOGIN_REDIRECT_URL = "core:inicio"
LOGOUT_REDIRECT_URL = "usuarios:login"

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True
CSRF_TRUSTED_ORIGINS = csrf_origins
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
# Separador de miles con punto y decimales con coma (ver config/formatos/es_CL/formats.py).
FORMAT_MODULE_PATH = ["config.formatos"]

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_USE_FINDERS = True

# Versión visible en el pie de página y usada para refrescar CSS/JS en el navegador.
APP_VERSION = "3.3.0"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Archivos subidos grandes (cartolas) se procesan en disco temporal, no en memoria.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"apps": {"handlers": ["console"], "level": "INFO"}},
}

# Despliegue en Vercel (HTTPS detrás de un proxy)
CSRF_TRUSTED_ORIGINS = [
    "https://*.vercel.app",
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
