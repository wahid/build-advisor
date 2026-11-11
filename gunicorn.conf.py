"""gunicorn settings for production (read automatically from the working directory).

One worker process, so the embedding model (~2.3 GB) is loaded once; threads
serve visitors concurrently. Answers stream for up to a few minutes (Path of
Building builds), so the timeout is long; the threaded worker keeps
heartbeating while a request streams.
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
worker_class = "gthread"
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "*"  # Caddy is the only thing in front of us (same Docker network)
