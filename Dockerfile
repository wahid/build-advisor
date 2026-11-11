# --- Frontend: build the React app -----------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Backend -----------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.13.4

WORKDIR /app

# Install dependencies first so they're cached between code changes.
# EMBEDDINGS: cpu (default, e.g. Railway) | cuda (local GPU) | none (no torch)
ARG INSTALL_DEV=false
ARG EMBEDDINGS=cpu
COPY pyproject.toml uv.lock .python-version ./
RUN set -e; \
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
