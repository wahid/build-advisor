FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.13.4

WORKDIR /app

# Install dependencies first so they're cached between code changes.
ARG INSTALL_DEV=false
COPY pyproject.toml uv.lock .python-version ./
RUN if [ "$INSTALL_DEV" = "true" ]; then uv sync --frozen --no-install-project; \
    else uv sync --frozen --no-install-project --no-dev; fi

COPY . .

EXPOSE 8000
# Railway (and most PaaS hosts) inject $PORT.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2"]
