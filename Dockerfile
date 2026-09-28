# Root Dockerfile for Django REST Framework Production Server (when build context is repo root)

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
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt

# Copy server and shared modules
COPY server/ /app/server/
COPY shared/ /app/shared/

RUN sed -i 's/\r$//' /app/server/entrypoint.sh && chmod +x /app/server/entrypoint.sh && python manage.py collectstatic --noinput

EXPOSE 8000

ENTRYPOINT ["/bin/sh", "/app/server/entrypoint.sh"]
CMD ["gunicorn"]
