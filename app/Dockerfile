FROM python:3.12-slim

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/

EXPOSE 8080

# Healthcheck uses Python instead of curl/wget so we don't need apt-get layers.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD python3 -c "import urllib.request,sys; \
        urllib.request.urlopen('http://localhost:8080/healthz').read()" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
