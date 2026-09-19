# syntax=docker/dockerfile:1

# --- build stage -------------------------------------------------------------
# Dependencies are compiled into wheels here so the runtime image never needs a
# toolchain, and a code-only change reuses this cached layer untouched.
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# --- runtime stage -----------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /srv/app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts

USER app

EXPOSE 8000

# Liveness only — readiness (which touches the database) is polled by the load
# balancer, not by the container runtime. See app/api/routes/health.py.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
