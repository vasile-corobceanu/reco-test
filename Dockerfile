FROM python:3.13-slim AS base

RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --create-home app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY asana_client.py pipeline.py app.py gunicorn.conf.py ./

RUN mkdir -p /app/data && chown app:app /app/data
VOLUME /app/data

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["gunicorn", "app:app", "-c", "gunicorn.conf.py"]