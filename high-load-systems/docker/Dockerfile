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

# DevOps Lab5 - build identity. CI passes the git tag and the commit in here, and
# /version reads them back out of the environment. Baking them into the image
# rather than into a ConfigMap is the point: a values file can be edited to claim
# any version, an image cannot, so under GitOps the running pods stay the source
# of truth for what actually landed.
ARG APP_VERSION=0.0.0-dev
ARG GIT_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA}

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

# The same two values as OCI labels, so `docker inspect` and /version cannot disagree.
LABEL org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/ostrrovska/uni_year_4"

USER app

EXPOSE 8000

# Liveness only — readiness (which touches the database) is polled by the load
# balancer, not by the container runtime. See app/api/routes/health.py.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
