# syntax=docker/dockerfile:1
# --- Frontend: build the React app -----------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Path of Building: only the parts the headless engine needs ---------------
FROM python:3.12-slim AS pob
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# Pin a tag or commit with --build-arg POB_REF=... ; rebuild when PoB updates for a league.
# Only src/ and runtime/lua/ are checked out, and tree/item images are deleted
# (~400 MB, only needed for drawing): the headless engine runs without them.
ARG POB_REF=
RUN git clone --depth 1 --filter=blob:none --sparse ${POB_REF:+--branch "$POB_REF"} \
        https://github.com/PathOfBuildingCommunity/PathOfBuilding /opt/PathOfBuilding \
    && cd /opt/PathOfBuilding \
    && git sparse-checkout set src runtime/lua \
    && git log -1 --format="Path of Building %h (%cd)" > /opt/PathOfBuilding/VERSION \
    && rm -rf .git \
    && find src \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.webp' \) -delete

# --- Backend -----------------------------------------------------------------
FROM python:3.12-slim

COPY --from=pob /opt/PathOfBuilding /opt/PathOfBuilding

ENV POB_PATH=/opt/PathOfBuilding \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/root/.cache/uv \
    PATH="/opt/venv/bin:$PATH"

RUN --mount=type=cache,target=/root/.cache/pip pip install uv==0.13.4

WORKDIR /app

# Install dependencies first so they're cached between code changes.
# EMBEDDINGS: cpu (default, e.g. Railway) | cuda (local GPU) | none (no torch)
ARG INSTALL_DEV=false
ARG EMBEDDINGS=cpu
COPY pyproject.toml uv.lock .python-version ./
# The cache mount keeps downloaded wheels between builds: adding one small package
# no longer re-downloads PyTorch (several GB for the CUDA build).
RUN --mount=type=cache,target=/root/.cache/uv \
    set -e; \
    flags="--frozen --no-install-project"; \
    [ "$INSTALL_DEV" = "true" ] || flags="$flags --no-dev"; \
    [ "$EMBEDDINGS" = "none" ] || flags="$flags --extra $EMBEDDINGS"; \
    uv sync $flags

COPY . .
COPY --from=frontend /frontend/dist /app/frontend/dist
RUN DJANGO_SECRET_KEY=collectstatic python manage.py collectstatic --noinput

EXPOSE 8000
# Railway (and most PaaS hosts) inject $PORT.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2"]
