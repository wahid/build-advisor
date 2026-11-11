"""Load the slow parts before the first visitor asks something.

The embedding model (~20 s to load) and a Path of Building process (~6 s)
are otherwise loaded by the first question. Only web server processes warm
up, not management commands or the Celery worker.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)


def is_web_server() -> bool:
    argv = " ".join(sys.argv)
    if "runserver" in argv:
        return os.environ.get("RUN_MAIN") == "true"  # the reloader's child, not its parent
    return "gunicorn" in argv


def warm_up() -> None:
    from wiki.embeddings import get_embedder

    from .pob import get_pool

    started = time.monotonic()
    try:
        get_embedder().embed_query("warm up")
    except Exception:
        logger.exception("Warm-up of the embedding model failed")
    pool = get_pool()
    if pool is not None:
        try:
            with pool.toolbox():
                pass
        except Exception:
            logger.exception("Warm-up of Path of Building failed")
    logger.info("Warm-up done in %.1fs", time.monotonic() - started)


def warm_up_in_background() -> None:
    threading.Thread(target=warm_up, name="warm-up", daemon=True).start()
