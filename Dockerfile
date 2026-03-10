FROM python:3.13-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY asana_client.py pipeline.py app.py gunicorn.conf.py ./
COPY tests/ tests/

# Test stage — build fails if any test fails
FROM base AS test
RUN python -m pytest tests/ -v && touch /tmp/.tests_passed

# Production image — COPY from test forces it to run first
FROM base AS production
COPY --from=test /tmp/.tests_passed /tmp/.tests_passed

RUN rm -rf tests/ /tmp/.tests_passed

RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --create-home app && \
    mkdir -p /app/asana && chown app:app /app/asana

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["gunicorn", "app:app", "-c", "gunicorn.conf.py"]