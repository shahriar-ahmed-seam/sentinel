# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS deps

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /wheels
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin sentinel

WORKDIR /app
COPY --from=deps /wheels /wheels
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels

# Uncomment to enable OTLP span export in the image:
# RUN pip install -r requirements-optional.txt

COPY sentinel ./sentinel
RUN chown -R sentinel:sentinel /app
USER sentinel

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8000}/health || exit 1

# The span buffer and rate-limit buckets live in the process, so a single
# uvicorn worker per container is intentional. Scale with replicas.
CMD ["sh", "-c", "exec uvicorn sentinel.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
