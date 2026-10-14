FROM python:3.11-slim

WORKDIR /app

# libgl1/libglib2.0-0: required by opencv/paddleocr's image ops.
# tesseract-ocr + the Indic language packs: the CPU fallback backend (and the only backend that
# covers bengali/gurmukhi/gujarati/odia/malayalam — paddleocr 2.7.3 has no models for those, see
# main.py's _SCRIPT_TO_PADDLE_LANG mapping).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    tesseract-ocr-hin \
    tesseract-ocr-ben \
    tesseract-ocr-pan \
    tesseract-ocr-guj \
    tesseract-ocr-ori \
    tesseract-ocr-tam \
    tesseract-ocr-tel \
    tesseract-ocr-kan \
    tesseract-ocr-mal \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Two steps required — see requirements.txt's top comment for why a single install leaves a
# broken cv2 (paddleocr==2.7.3 pins opencv-python/opencv-contrib-python<=4.6.0.66, which predates
# NumPy 2.0 and crashes on import).
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --force-reinstall --no-deps "opencv-contrib-python>=4.9,<5"

COPY main.py .

ENV TESSERACT_CMD=/usr/bin/tesseract
ENV INDIC_OCR_BACKEND=paddle

RUN useradd -m -u 1000 astra
USER astra

EXPOSE 8021
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8021/')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8021", "--workers", "1"]
