FROM python:3.11-slim

WORKDIR /app

# libgl1 + libglib2.0-0 required by ultralytics/OpenCV if SIG_DETECTOR_LOCAL_PATH is set.
# Not needed for pixel-analysis mode (the default), but costs nothing to ship.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Optional: set to a local .pt weights file path (bind-mounted at runtime)
# to enable YOLOv8 mode.  Default is pixel-analysis mode — no download needed.
ENV SIG_DETECTOR_LOCAL_PATH=""

RUN useradd -m -u 1000 astra
USER astra

EXPOSE 8020
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8020/health/live')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8020", "--workers", "1"]
