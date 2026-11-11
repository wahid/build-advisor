from pathlib import Path

import pytest

from wiki.client import WikiClient

API_URL = "https://wiki.test/w/api.php"


@pytest.fixture(autouse=True)
def _wiki_settings(settings, tmp_path: Path) -> None:
    settings.WIKI_API_URL = API_URL
    settings.WIKI_PAGE_URL = "https://wiki.test/wiki/"
    settings.WIKI_CACHE_DIR = tmp_path / "cache"
    settings.WIKI_REQUEST_INTERVAL = 0
    settings.WIKI_PROXIES = []
    settings.WIKI_WORKERS = 1
    settings.POE_PATCH = ""


@pytest.fixture
def wiki_client(tmp_path: Path) -> WikiClient:
    return WikiClient(
        api_url=API_URL,
        page_url="https://wiki.test/wiki/",
        user_agent="tests",
        cache_dir=tmp_path / "cache",
        request_interval=0,
        sleep=lambda _seconds: None,
    )


@pytest.fixture(autouse=True)
def _fresh_pob_pool(settings):
    """Path of Building is off in tests unless a test turns it on."""
    from advisor.pob import get_pool

    settings.POB_ENABLED = False
    get_pool.cache_clear()
    yield
    get_pool.cache_clear()


@pytest.fixture(autouse=True)
def _no_query_rewrite(settings):
    """Tests opt in to query rewriting explicitly."""
    settings.SEARCH_QUERY_REWRITE = False
