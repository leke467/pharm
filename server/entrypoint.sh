#!/bin/sh
set -e

cd /app/server

case "$*" in
  *makemigrations*|*migrate*)
    echo "[Entrypoint] Running database migrations and production bootstrap..."
    python manage.py migrate --noinput
    python bootstrap_railway.py
    exit 0
    ;;
  *)
    echo "[Entrypoint] Ensuring migrations and bootstrap are applied..."
    python manage.py migrate --noinput
    python bootstrap_railway.py
    echo "[Entrypoint] Starting Gunicorn on 0.0.0.0:8000 and 0.0.0.0:8080..."
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --bind 0.0.0.0:8080 --workers 3 --threads 2 --timeout 120
    ;;
esac
