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
