"""Django settings for build-advisor.

All configuration comes from environment variables (see `.env.example`).
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()


def read_proxy_file(path: Path) -> list[str]:
    """Proxy URLs from a text file, one per line; blank lines and # comments are skipped."""
    if not path.is_file():
        return []
    lines = (line.split("#", 1)[0].strip() for line in path.read_text("utf-8").splitlines())
    return [line for line in lines if line]


environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "wiki",
    "advisor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://build_advisor:build_advisor@localhost:5432/build_advisor",
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# The React app (frontend/) is built with Vite into frontend/dist, using
# /static/ as its base, and served by Django + WhiteNoise in production.
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_RATES": {"ask": env("ASK_RATE_LIMIT", default="60/hour")},
}

# --- Celery -----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

# --- Path of Exile wiki ingestion -------------------------------------------
WIKI_NAME = "poewiki"
WIKI_API_URL = env("WIKI_API_URL", default="https://www.poewiki.net/w/api.php")
WIKI_PAGE_URL = env("WIKI_PAGE_URL", default="https://www.poewiki.net/wiki/")
# The wiki asks bots to identify themselves with a contact address.
WIKI_USER_AGENT = env(
    "WIKI_USER_AGENT",
    default="build-advisor/0.1 (non-commercial portfolio project; set WIKI_USER_AGENT)",
)
WIKI_REQUEST_INTERVAL = env.float("WIKI_REQUEST_INTERVAL", default=2.5)  # seconds
# On rate limiting the interval grows (up to this) and slowly shrinks again.
WIKI_MAX_REQUEST_INTERVAL = env.float("WIKI_MAX_REQUEST_INTERVAL", default=30.0)
WIKI_MAX_RETRIES = env.int("WIKI_MAX_RETRIES", default=6)
# Optional comma-separated proxy URLs, e.g. http://user:pass@host:port,socks5://host:1080.
# Each download worker uses its own proxy and moves to another one only when its proxy fails.
# Proxies can also be listed in a text file, one per line (blank lines and # comments
# are ignored). Both sources are combined.
WIKI_PROXY_FILE = BASE_DIR / env("WIKI_PROXY_FILE", default="proxies.txt")
WIKI_PROXIES = list(
    dict.fromkeys(env.list("WIKI_PROXIES", default=[]) + read_proxy_file(WIKI_PROXY_FILE))
)
WIKI_PROXY_COOLDOWN = env.float("WIKI_PROXY_COOLDOWN", default=300.0)  # seconds
# Parallel download threads, each with its own home proxy (the rest are spares for
# failover). Every worker keeps its own request interval, so the wiki sees roughly
# WIKI_WORKERS requests per WIKI_REQUEST_INTERVAL; keep this small. Capped at 16.
WIKI_MAX_WORKERS = 16
WIKI_WORKERS = min(
    env.int("WIKI_WORKERS", default=min(len(WIKI_PROXIES), 4) or 1), WIKI_MAX_WORKERS
)
WIKI_CACHE_DIR = Path(env("WIKI_CACHE_DIR", default=str(BASE_DIR / "data" / "raw")))
# Leave empty to use the latest released version from the wiki's version table.
POE_PATCH = env("POE_PATCH", default="")

# --- Embeddings ---------------------------------------------------------------
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="BAAI/bge-m3")
# Changing this needs a migration and re-embedding everything.
EMBEDDING_DIMENSIONS = 1024
EMBEDDING_DEVICE = env("EMBEDDING_DEVICE", default="auto")  # auto | cuda | cpu
EMBEDDING_BATCH_SIZE = env.int("EMBEDDING_BATCH_SIZE", default=32)
CHUNK_MAX_CHARS = env.int("CHUNK_MAX_CHARS", default=1500)

# --- Retrieval -----------------------------------------------------------------
SEARCH_TOP_K = env.int("SEARCH_TOP_K", default=8)
SEARCH_CANDIDATES = env.int("SEARCH_CANDIDATES", default=40)  # per ranked list
SEARCH_MAX_PER_DOCUMENT = env.int("SEARCH_MAX_PER_DOCUMENT", default=3)


# --- LLM ------------------------------------------------------------------------
# deepseek | openai | anthropic (all via their OpenAI-compatible APIs).
LLM_PROVIDER = env("LLM_PROVIDER", default="deepseek")
LLM_MODEL = env("LLM_MODEL", default="")  # required; providers rename models often
LLM_API_KEY = env("LLM_API_KEY", default="")
LLM_BASE_URL = env("LLM_BASE_URL", default="")  # empty: the provider's default
LLM_TEMPERATURE = env.float("LLM_TEMPERATURE", default=0.2)
LLM_MAX_TOKENS = env.int("LLM_MAX_TOKENS", default=1500)
LLM_TIMEOUT = env.float("LLM_TIMEOUT", default=60.0)
# Provider-specific request options as JSON, e.g. to turn off thinking mode.
LLM_EXTRA_BODY = env.json("LLM_EXTRA_BODY", default={})

# Ask the LLM for wiki terms before searching: one extra short call per question (~2-4 s),
# finds pages the question describes without naming ("something that casts for me" -> Totem).
# On by default when an LLM is configured.
SEARCH_QUERY_REWRITE = env.bool("SEARCH_QUERY_REWRITE", default=bool(LLM_API_KEY))

# --- Path of Building (pob-mcp tools for the LLM) --------------------------------
# Path to a PathOfBuilding checkout (only src/ and runtime/lua/ are needed).
POB_PATH = env("POB_PATH", default="")
POB_ENABLED = env.bool("POB_ENABLED", default=bool(POB_PATH) and Path(POB_PATH).exists())
POB_POOL_SIZE = env.int("POB_POOL_SIZE", default=1)  # PoB processes per web/worker process
POB_TOOL_TIMEOUT = env.float("POB_TOOL_TIMEOUT", default=90.0)
POB_MAX_TOOL_ROUNDS = env.int("POB_MAX_TOOL_ROUNDS", default=8)
POB_DEBUG = env.bool("POB_DEBUG", default=False)  # show PoB's console output
# Override the allowlist of pob-mcp tools (comma-separated); empty = advisor.pob.DEFAULT_TOOLS.
POB_TOOLS = env.list("POB_TOOLS", default=[])

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
