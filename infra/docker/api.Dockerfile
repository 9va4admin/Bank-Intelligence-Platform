FROM python:3.11-slim

WORKDIR /app

# System libs needed by asyncpg / cryptography / argon2 / paramiko
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies first so this layer is cached unless requirements change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source
COPY apps/api/         apps/api/
COPY modules/cts/      modules/cts/
COPY modules/msv/      modules/msv/
COPY shared/           shared/

ENV PYTHONPATH=/app

EXPOSE 8010
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "4", "--log-level", "info"]
