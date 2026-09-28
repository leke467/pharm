# Dockerfile for Django REST Framework Production Server (Railway Root Directory = server)

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app/server

# Install system dependencies (PostgreSQL client runtime + dev headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt

# Copy server and shared modules
COPY . /app/server/
COPY shared/ /app/shared/

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python bootstrap_railway.py && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3 --threads 2 --timeout 120"]
