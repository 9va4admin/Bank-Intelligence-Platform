FROM python:3.11-slim

WORKDIR /app

# System deps for Pillow + ultralytics (libGL needed by OpenCV under the hood)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Pre-download the model weights at build time so container starts instantly.
# Override with --build-arg MODEL=<other-hf-id-or-local-path> if needed.
ARG MODEL=keremberke/yolov8s-signature-detection
ENV SIG_DETECTOR_MODEL=${MODEL}

# Bake weights into the image (removes startup download latency in prod)
RUN python -c "from ultralytics import YOLO; YOLO('${MODEL}')" 2>&1 || \
    echo "WARNING: model pre-download failed — will retry at container startup."

RUN useradd -m -u 1000 astra
USER astra

EXPOSE 8020
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8020/health/live')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8020", "--workers", "1"]
