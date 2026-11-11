"""Small client for the Path of Exile wiki's MediaWiki API.

Respects the wiki's rate limits (a minimum interval between requests,
`maxlag`, and `Retry-After` on 429/503) and caches parsed pages on disk
per revision so that re-runs don't hit the wiki again.

Requests can optionally go through a list of proxies. Each client has a home
proxy (see `WikiClient.for_worker`, used for one client per worker thread) and
sticks to it while it works. When the proxy itself fails (connection error,
timeout, or an error status from the proxy) the request is retried on the next
healthy proxy, and the failed one is skipped for a cooldown period. Each client
keeps its own throttle and backoff for the wiki's rate limiting.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests
import urllib3

from .models import DocumentType

# Requests use verify=False (see WikiClient._get), so silence urllib3's warning.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

CARGO_PAGE_SIZE = 500
BACKOFF_BASE = 5.0  # seconds; doubled per retry
BACKOFF_CAP = 120.0
SLOWDOWN_FACTOR = 2.0  # interval multiplier after a rate-limit response
SPEEDUP_FACTOR = 0.95  # interval multiplier after each successful request
REVISION_BATCH_SIZE = 50  # MediaWiki's limit for titles per query for normal clients.
PROXY_COOLDOWN = 300.0  # seconds a failed proxy is skipped before it's tried again
PROXY_SWITCHES_PER_REQUEST = 100  # other proxies tried before failures count as retries
CONNECT_TIMEOUT = 1.0  # seconds; dead proxies should fail fast
READ_TIMEOUT = 2.0
DIRECT_TIMEOUT = (10.0, 30.0)  # (connect, read) seconds without a proxy
# Statuses that come from a broken proxy rather than from the wiki.
PROXY_ERROR_STATUSES = frozenset({407, 429, 502, 503, 504, 403})


class WikiError(RuntimeError):
    """Raised when the wiki returns an error or can't be reached."""


class WikiBlockedError(WikiError):
    """The wiki's bot protection (Cloudflare) is challenging us; retrying won't help."""


def _socks_supported() -> bool:
    try:
        import socks  # noqa: F401  (PySocks, installed by requests[socks])
    except ImportError:
        return False
    return True


class ProxyPool:
    """A thread-safe list of proxies with a cooldown for ones that failed recently.

    Shared by all worker clients, so a proxy that fails for one worker is
    skipped by the others too.
    """

    def __init__(
        self,
        proxies: Iterable[str],
        cooldown: float = PROXY_COOLDOWN,
        clock: Callable[[], float] = time.monotonic,
        socks_supported: Callable[[], bool] = _socks_supported,
    ) -> None:
        self.proxies = list(dict.fromkeys(p.strip() for p in proxies if p.strip()))
        socks_proxies = [p for p in self.proxies if p.lower().startswith("socks")]
        if socks_proxies and not socks_supported():
            logger.warning(
                "Skipping %d SOCKS proxies: SOCKS support isn't installed (PySocks). "
                "Run `uv sync`, or rebuild the Docker image with `docker compose build`.",
                len(socks_proxies),
            )
            self.proxies = [p for p in self.proxies if p not in set(socks_proxies)]
        self._positions = {proxy: i for i, proxy in enumerate(self.proxies)}
        self.cooldown = cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._failed_until: dict[str, float] = {}

    def __len__(self) -> int:
        return len(self.proxies)

    def pick(self, preferred: int) -> str | None:
        """The first healthy proxy starting at index `preferred` (wrapping around)."""
        if not self.proxies:
            return None
        with self._lock:
            now = self._clock()
            for offset in range(len(self.proxies)):
                proxy = self.proxies[(preferred + offset) % len(self.proxies)]
                if self._failed_until.get(proxy, 0.0) <= now:
                    return proxy
            # Everything failed recently: use the one that comes off cooldown first.
            return min(self.proxies, key=lambda p: self._failed_until[p])

    def index_of(self, proxy: str) -> int:
        return self._positions[proxy]

    def mark_failed(self, proxy: str) -> None:
        with self._lock:
            self._failed_until[proxy] = self._clock() + self.cooldown


def _redact(proxy: str) -> str:
    """Drop credentials from a proxy URL so it can be logged."""
    parts = urlsplit(proxy)
    if parts.username or parts.password:
        return proxy.replace(parts.netloc, parts.netloc.rsplit("@", 1)[-1], 1)
    return proxy


@dataclass(frozen=True)
class WikiPage:
    title: str
    page_id: int
    revision_id: int
    html: str


@dataclass(frozen=True)
class CargoListing:
    """A list of pages selected through the wiki's Cargo tables."""

    tables: str
    where: str
    join_on: str = ""


@dataclass(frozen=True)
class CategoryListing:
    category: str
    depth: int = 0  # how many levels of subcategories to follow


# How each document type maps to pages on the wiki.
LISTINGS: dict[str, CargoListing | CategoryListing] = {
    DocumentType.GEM: CargoListing(
        tables="items",
        where='items.class_id IN ("Active Skill Gem", "Support Skill Gem")',
    ),
    DocumentType.UNIQUE: CargoListing(
        tables="items",
        where='items.rarity_id = "unique" AND items.class_id NOT IN ("Map", "Relic")',
    ),
    DocumentType.ASCENDANCY: CategoryListing("Category:Ascendancy classes"),
    # Core pages like Ignite or Endurance charge sit in subcategories (ailments, charges).
    DocumentType.MECHANIC: CategoryListing("Category:Game mechanics", depth=1),
}


class WikiClient:
    def __init__(
        self,
        api_url: str,
        page_url: str,
        user_agent: str,
        cache_dir: Path,
        request_interval: float = 2.5,
        max_retries: int = 6,
        max_interval: float = 30.0,
        proxies: Iterable[str] | ProxyPool = (),
        proxy_index: int = 0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_url = api_url
        self.page_url = page_url
        self.cache_dir = cache_dir
        self.base_interval = request_interval
        self.request_interval = request_interval
        self.max_interval = max(max_interval, request_interval)
        self.max_retries = max_retries
        self.proxy_pool = proxies if isinstance(proxies, ProxyPool) else ProxyPool(proxies)
        self.proxy_index = proxy_index
        self.user_agent = user_agent
        self._sleep = sleep
        self._last_request = 0.0
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent

    @classmethod
    def from_settings(cls, direct: bool = False) -> WikiClient:
        """Client configured from Django settings; `direct` ignores the proxy list."""
        from django.conf import settings

        return cls(
            api_url=settings.WIKI_API_URL,
            page_url=settings.WIKI_PAGE_URL,
            user_agent=settings.WIKI_USER_AGENT,
            cache_dir=settings.WIKI_CACHE_DIR,
            request_interval=settings.WIKI_REQUEST_INTERVAL,
            max_retries=settings.WIKI_MAX_RETRIES,
            max_interval=settings.WIKI_MAX_REQUEST_INTERVAL,
            proxies=()
            if direct
            else ProxyPool(settings.WIKI_PROXIES, cooldown=settings.WIKI_PROXY_COOLDOWN),
        )

    def for_worker(self, index: int, total: int = 1) -> WikiClient:
        """A client for worker `index` of `total`: own session, throttle and home proxy.

        Home proxies are spread evenly over the list so that workers failing over
        don't all land on the same spare. The proxy pool (and its failure state)
        and the page cache are shared.
        """
        home = index * len(self.proxy_pool) // max(total, 1) if self.proxy_pool else 0
        return WikiClient(
            api_url=self.api_url,
            page_url=self.page_url,
            user_agent=self.user_agent,
            cache_dir=self.cache_dir,
            request_interval=self.base_interval,
            max_retries=self.max_retries,
            max_interval=self.max_interval,
            proxies=self.proxy_pool,
            proxy_index=home,
            sleep=self._sleep,
        )

    # --- public API ---------------------------------------------------------

    def page_url_for(self, title: str) -> str:
        return self.page_url + quote(title.replace(" ", "_"), safe="/:()'!,")

    def list_titles(self, doc_type: str) -> list[str]:
        listing = LISTINGS[doc_type]
        if isinstance(listing, CargoListing):
            titles = self._cargo_titles(listing)
        else:
            titles = self._category_titles(listing.category, listing.depth, set())
        return sorted(set(titles))

    def revision_ids(self, titles: Iterable[str]) -> dict[str, int]:
        """Return the latest revision id per title (missing pages are left out)."""
        result: dict[str, int] = {}
        for batch in _batched(list(titles), REVISION_BATCH_SIZE):
            data = self._get(
                {
                    "action": "query",
                    "prop": "revisions",
                    "rvprop": "ids",
                    "titles": "|".join(batch),
                    "redirects": 1,
                }
            )
            query = data.get("query", {})
            # Map normalised/redirected titles back to the titles we asked for.
            aliases = {
                item["to"]: item["from"]
                for key in ("normalized", "redirects")
                for item in query.get(key, [])
            }
            for page in query.get("pages", []):
                if page.get("missing") or not page.get("revisions"):
                    continue
                title = page["title"]
                while title in aliases and title not in batch:
                    title = aliases[title]
                result[title] = page["revisions"][0]["revid"]
        return result

    def fetch_page(self, title: str, revision_id: int | None = None) -> WikiPage:
        """Fetch rendered HTML for a page, using the on-disk cache when possible."""
        if revision_id is not None:
            cached = self._read_cache(title, revision_id)
            if cached is not None:
                return cached

        data = self._get(
            {
                "action": "parse",
                "page": title,
                "prop": "text|revid",
                "redirects": 1,
                "disableeditsection": 1,
                "disablelimitreport": 1,
                "disabletoc": 1,
            }
        )
        parsed = data["parse"]
        page = WikiPage(
            title=title,
            page_id=parsed["pageid"],
            revision_id=parsed["revid"],
            html=parsed["text"],
        )
        self._write_cache(page)
        return page

    def current_patch(self, today: date | None = None) -> str:
        """Latest game version that has been released, according to the wiki."""
        today = today or date.today()
        rows = self._cargo(
            tables="versions",
            fields="version,release_date",
            where=f'release_date <= "{today.isoformat()}"',
            order_by="release_date DESC",
            limit=1,
        )
        if not rows:
            raise WikiError("The wiki returned no released versions.")
        return rows[0]["version"]

    # --- listings -----------------------------------------------------------

    def _cargo_titles(self, listing: CargoListing) -> Iterator[str]:
        offset = 0
        while True:
            rows = self._cargo(
                tables=listing.tables,
                fields="_pageName=page",
                where=listing.where,
                join_on=listing.join_on,
                group_by="_pageName",
                limit=CARGO_PAGE_SIZE,
                offset=offset,
            )
            for row in rows:
                yield html.unescape(row["page"])
            if len(rows) < CARGO_PAGE_SIZE:
                return
            offset += CARGO_PAGE_SIZE

    def _category_titles(self, category: str, depth: int, seen: set[str]) -> Iterator[str]:
        """Articles in a category, and in its subcategories up to `depth` levels down."""
        if category in seen:
            return
        seen.add(category)
        params: dict[str, Any] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmnamespace": "0|14" if depth > 0 else 0,
            "cmlimit": "max",
        }
        subcategories: list[str] = []
        while True:
            data = self._get(params)
            for member in data["query"]["categorymembers"]:
                if member.get("ns", 0) == 14:
                    subcategories.append(member["title"])
                else:
                    yield member["title"]
            cont = data.get("continue")
            if not cont:
                break
            params = {**params, **cont}
        for subcategory in subcategories:
            yield from self._category_titles(subcategory, depth - 1, seen)

    def _cargo(self, **query: Any) -> list[dict[str, str]]:
        params = {"action": "cargoquery", **{k: v for k, v in query.items() if v != ""}}
        data = self._get(params)
        return [row["title"] for row in data.get("cargoquery", [])]

    # --- HTTP ---------------------------------------------------------------

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send an API request.

        Through a proxy, proxy failures move to another proxy. Without a proxy
        (no proxies configured, or `fetch_wiki --direct`), requests are
        throttled and back off when the wiki asks them to slow down.
        """
        params = {**params, "format": "json", "formatversion": 2, "maxlag": 5}
        # A few proxy failures per request just move to another proxy; after that,
        # failures count as normal retries.
        proxy_switches_left = min(len(self.proxy_pool), PROXY_SWITCHES_PER_REQUEST)
        attempt = 0
        while attempt < self.max_retries:
            attempt += 1
            proxy = self.proxy_pool.pick(self.proxy_index)
            backoff = min(BACKOFF_BASE * 2 ** (attempt - 1), BACKOFF_CAP)
            if proxy is None:
                self._throttle()
            try:
                response = self.session.get(
                    self.api_url,
                    params=params,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT) if proxy else DIRECT_TIMEOUT,
                    proxies={"http": proxy, "https": proxy} if proxy else None,
                    # The wiki's TLS cert is valid but its chain is incomplete.
                    verify=False,
                )
            except requests.RequestException as exc:
                if proxy and proxy_switches_left > 0:
                    proxy_switches_left -= 1
                    attempt -= 1
                    self._proxy_failed(proxy, str(exc))
                    continue
                if attempt == self.max_retries:
                    raise WikiError(f"Request failed: {exc}") from exc
                if proxy:
                    self.proxy_pool.mark_failed(proxy)
                else:
                    self._sleep(backoff)
                continue

            if proxy and response.status_code in PROXY_ERROR_STATUSES:
                if proxy_switches_left > 0:
                    proxy_switches_left -= 1
                    attempt -= 1
                    self._proxy_failed(proxy, f"HTTP {response.status_code}")
                    continue
                raise WikiError(f"All proxies failed (last: HTTP {response.status_code})")

            if proxy is None:
                if response.headers.get("cf-mitigated") == "challenge":
                    raise WikiBlockedError(
                        "Cloudflare is blocking requests from this connection with a bot "
                        "challenge. Stop for a few hours and try again with a lower request rate."
                    )
                if _is_bot_challenge(response):
                    raise WikiBlockedError(
                        "The wiki's bot protection (Anubis) is blocking requests from this "
                        "connection. Stop for a few hours and try again with a lower request rate."
                    )
                if response.status_code in (429, 503):
                    self._slow_down()
                    wait = max(_retry_after(response, default=backoff), backoff)
                    logger.warning(
                        "Wiki asked us to slow down (HTTP %s); waiting %.0fs, "
                        "then 1 request per %.1fs",
                        response.status_code,
                        wait,
                        self.request_interval,
                    )
                    self._sleep(wait)
                    continue

            if response.status_code != 200:
                raise WikiError(f"HTTP {response.status_code} from wiki")

            try:
                data: dict[str, Any] = response.json()
            except ValueError as exc:
                raise WikiError("The wiki returned a web page instead of API data.") from exc
            error = data.get("error")
            if error and error.get("code") in ("maxlag", "ratelimited"):
                if proxy is None:
                    self._slow_down()
                    self._sleep(max(_retry_after(response, default=backoff), backoff))
                continue
            if error:
                raise WikiError(f"{error.get('code')}: {error.get('info')}")
            self._speed_up()
            return data
        raise WikiError("Gave up after repeated rate-limit responses.")

    def _proxy_failed(self, proxy: str, reason: str) -> None:
        self.proxy_pool.mark_failed(proxy)
        replacement = self.proxy_pool.pick(self.proxy_index)
        if replacement is not None:
            # The replacement becomes this client's new home proxy.
            self.proxy_index = self.proxy_pool.index_of(replacement)
        logger.debug(
            "Proxy %s failed; switching to %s",
            _redact(proxy),
            _redact(replacement or "direct connection"),
        )

    def _slow_down(self) -> None:
        self.request_interval = min(
            max(self.request_interval, 0.5) * SLOWDOWN_FACTOR, self.max_interval
        )

    def _speed_up(self) -> None:
        self.request_interval = max(self.base_interval, self.request_interval * SPEEDUP_FACTOR)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.request_interval:
            self._sleep(self.request_interval - elapsed)
        self._last_request = time.monotonic()

    # --- cache --------------------------------------------------------------

    def _cache_path(self, title: str, revision_id: int) -> Path:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:120]
        return self.cache_dir / f"{slug}-{revision_id}.json"

    def _read_cache(self, title: str, revision_id: int) -> WikiPage | None:
        path = self._cache_path(title, revision_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("title") != title:  # slug collision
            return None
        return WikiPage(**data)

    def _write_cache(self, page: WikiPage) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(page.title, page.revision_id)
        path.write_text(json.dumps(page.__dict__, ensure_ascii=False), encoding="utf-8")


def _is_bot_challenge(response: requests.Response) -> bool:
    """An HTML block or challenge page (e.g. Anubis) where the API should return JSON."""
    if "html" not in response.headers.get("Content-Type", ""):
        return False
    return "anubis" in response.text[:20000].lower()


def _retry_after(response: requests.Response, default: float) -> float:
    try:
        return float(response.headers.get("Retry-After", default))
    except ValueError:
        return default


def _batched(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
