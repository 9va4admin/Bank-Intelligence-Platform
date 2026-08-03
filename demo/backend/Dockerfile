FROM python:3.12-slim

RUN groupadd -r astra && useradd -r -g astra astra

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

USER astra
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
