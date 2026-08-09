FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY modules/cts/   modules/cts/
COPY shared/        shared/

ENV PYTHONPATH=/app

CMD ["python", "-m", "modules.cts.worker"]
