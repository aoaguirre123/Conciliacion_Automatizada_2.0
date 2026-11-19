# Imagen de la aplicación Conciliación Automatizada 2.0 (Django + gunicorn).
# Se usa con docker-compose.yml, en la raíz del repositorio: docker compose up --build
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn

COPY . .
RUN python manage.py collectstatic --noinput

# La base de datos vive en un volumen, fuera de la imagen.
ENV DATABASE_URL=sqlite:////datos/db.sqlite3 \
    DJANGO_DEBUG=0
VOLUME /datos
EXPOSE 8000

# Al iniciar: crea o actualiza la base (la primera vez carga los BIN de tarjetas, demora un poco),
# crea el primer administrador si se indicó en las variables de entorno y levanta la aplicación.
CMD ["sh", "-c", "python manage.py migrate --noinput && if [ -n \"$DJANGO_SUPERUSER_EMAIL\" ]; then python manage.py createsuperuser --noinput || true; fi && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 180"]
