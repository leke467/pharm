# Root Dockerfile for Django REST Framework Production Server (Railway & Docker Compose compatible)

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

# Install system dependencies (PostgreSQL client dev headers, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install (supports both repo-root and server/ build contexts)
COPY requirements.txt* server/requirements.txt* /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy server and shared modules (supports both repo-root and server/ build contexts)
COPY . /tmp/ctx/
RUN mkdir -p /app/server /app/shared && \
    if [ -f /tmp/ctx/server/manage.py ]; then \
        cp -a /tmp/ctx/server/. /app/server/ && \
        cp -a /tmp/ctx/shared/. /app/shared/; \
    else \
        cp -a /tmp/ctx/. /app/server/ && \
        cp -a /tmp/ctx/shared/. /app/shared/; \
    fi && \
    rm -rf /tmp/ctx

WORKDIR /app/server

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python bootstrap_railway.py && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3 --threads 2 --timeout 120"]
