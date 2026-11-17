from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .ingest import content_hash
from .models import Document, DocumentType, MaxrollRequest, Source
from .parsing import html_to_text
from .progression import planner_ref, planner_text, profile_url

logger = logging.getLogger(__name__)

WIKI_NAME = "maxroll"
HOST = "maxroll.gg"
PATH_PREFIX = "/poe/"
# Hard limits from the licence: settings may be stricter, never looser.
MIN_REQUEST_INTERVAL = 1.0  # seconds: at most one request per second
MAX_PAGES_PER_MONTH = 50_000
MAX_QUOTE_WORDS = 100
MAX_REDIRECTS = 3
TIMEOUT = 30
# Postgres advisory lock ("MXRL"): one process at a time fetches for the chat.
LOCK_KEY = 0x4D58524C
SLOT_WAIT = 15.0  # seconds a chat question waits for another one's fetch

# Not stored: media, embedded tools, comments, site chrome. The Build Progression Tool is
# the exception: its text is read from the planner's profile (wiki.progression).
_REMOVE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "template",
    "img",
    "picture",
    "figure",
    "video",
    "audio",
    "source",
    "iframe",
    "object",
    "embed",
    "svg",
    "canvas",
    "form",
    "button",
    "nav",
    "footer",
    "aside",
    "[class*=comment]",
    "[id*=comment]",
    "[class*=embed]",
    "[class*=planner]",
    "[class*=video]",
    "[class*=youtube]",
    "[data-embed]",
]
_TITLE_SUFFIX_RE = re.compile(r"\s*\|\s*Maxroll(?:\.gg)?\s*$", re.IGNORECASE)
_PATCH_RE = re.compile(r"\b(?:Path of Exile|PoE|Patch)\s+(\d\.\d{1,2}(?:\.\d+)?[a-z]?)\b")
_UPDATED_RE = re.compile(r"\bUpdated\s*:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
_WORD_RE = re.compile(r"[\w'’-]+")


class MaxrollError(RuntimeError):
    pass


class MaxrollUnavailable(MaxrollError):
    """Pages can't be fetched now: switched off, outside the licence, monthly cap."""


# --- URLs -------------------------------------------------------------------------


def normalise_url(url: str) -> str:
    """The canonical https://maxroll.gg/poe/... URL, or ValueError for anything else."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.scheme not in ("http", "https") or host != HOST:
        raise ValueError(f"Not a maxroll.gg URL: {url}")
    path = parts.path.rstrip("/")
    if not path.startswith(PATH_PREFIX) or path == PATH_PREFIX.rstrip("/"):
        raise ValueError(f"Only Path of Exile pages under {PATH_PREFIX} are fetched: {url}")
    return urlunsplit(("https", HOST, path, "", ""))


# --- parsing ----------------------------------------------------------------------


@dataclass(frozen=True)
class GuidePage:
    url: str
    title: str
    author: str
    updated_on: date | None
    patch: str
    text: str


def parse_guide(
    url: str, html: str, profile: dict | None = None, embed_id: int | None = None
) -> GuidePage:
    """profile: the page's Build Progression Tool data, added after the article's text."""
    soup = BeautifulSoup(html, "html.parser")
    meta = _json_ld(soup)
    title = _title(soup, meta)
    author = _author(soup, meta)
    updated_on = _updated_on(soup, meta)
    patch = _patch(title, soup)

    root = soup.select_one("article") or soup.select_one("main") or soup.body or soup
    for selector in _REMOVE_SELECTORS:
        for element in root.select(selector):
            element.decompose()
    for heading in root.find_all("h1"):
        heading.decompose()  # the title, kept separately
    _drop_byline_block(root)

    text = html_to_text(str(root))
    progression = planner_text(profile, embed_id) if profile else ""
    text = "\n\n".join(part for part in (text.strip(), progression) if part)
    if not text.strip():
        raise MaxrollError(f"No article text found on {url}")
    return GuidePage(url, title, author, updated_on, patch, text)


def _json_ld(soup: BeautifulSoup) -> dict:
    """The page's Article metadata (headline, author, dateModified), if it has any."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and "Article" in str(item.get("@type", "")):
                return item
    return {}


def _title(soup: BeautifulSoup, meta: dict) -> str:
    h1 = soup.find("h1")
    for candidate in (
        h1.get_text(" ", strip=True) if h1 else "",
        str(meta.get("headline") or ""),
        _meta(soup, "og:title"),
        soup.title.get_text(strip=True) if soup.title else "",
    ):
        if candidate:
            return _TITLE_SUFFIX_RE.sub("", candidate).strip()
    return ""


def _author(soup: BeautifulSoup, meta: dict) -> str:
    author = meta.get("author")
    if isinstance(author, list):
        author = author[0] if author else None
    if isinstance(author, dict) and author.get("name"):
        return str(author["name"]).strip()
    if isinstance(author, str) and author.strip():
        return author.strip()
    if name := _meta(soup, "author"):
        return name
    # Visible byline: "Written by" followed by the name.
    label = soup.find(string=re.compile(r"^\s*Written by\s*$"))
    if label is not None:
        following = label.find_next(string=lambda s: bool(s and s.strip()))
        if following:
            return following.strip()
    match = re.search(r"Written by\s+([^\n|]+)", soup.get_text("\n"))
    return match.group(1).strip() if match else ""


def _updated_on(soup: BeautifulSoup, meta: dict) -> date | None:
    for value in (
        meta.get("dateModified"),
        _meta(soup, "article:modified_time"),
        meta.get("datePublished"),
    ):
        if parsed := _parse_iso(str(value or "")):
            return parsed
    time_tag = soup.find("time", attrs={"datetime": True})
    if isinstance(time_tag, Tag) and (parsed := _parse_iso(str(time_tag["datetime"]))):
        return parsed
    match = _UPDATED_RE.search(soup.get_text(" "))
    if match:
        try:
            return datetime.strptime(match.group(1), "%B %d, %Y").date()
        except ValueError:
            return None
    return None


def _patch(title: str, soup: BeautifulSoup) -> str:
    match = _PATCH_RE.search(title) or _PATCH_RE.search(soup.get_text(" ")[:3000])
    return match.group(1) if match else (settings.POE_PATCH or "unknown")


def _meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return str(tag.get("content", "")).strip() if isinstance(tag, Tag) else ""


def _parse_iso(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _drop_byline_block(root: Tag) -> None:
    """Remove the header with the date, byline and author bio before the first section.

    Only when that header has a "Written by" byline, so a guide whose introduction
    comes before its first heading keeps it.
    """
    first_heading = root.find(re.compile(r"^h[2-6]$"))
    if first_heading is None:
        return
    preceding = []
    node: Tag | None = first_heading
    while node is not None and node is not root:
        preceding.extend(node.previous_siblings)
        node = node.parent
    text = " ".join(el.get_text(" ") if isinstance(el, Tag) else str(el) for el in preceding)
    if "Written by" not in text:
        return
    for element in preceding:
        element.extract()


# --- fetching ---------------------------------------------------------------------


class MaxrollClient:
    """Fetches pages one at a time on one connection"""

    def __init__(
        self,
        user_agent: str,
        request_interval: float = MIN_REQUEST_INTERVAL,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.request_interval = max(request_interval, MIN_REQUEST_INTERVAL)
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.clock = clock
        self.sleep = sleep
        self._last_request: float | None = None

    @classmethod
    def from_settings(cls) -> MaxrollClient:
        return cls(
            user_agent=settings.MAXROLL_USER_AGENT,
            request_interval=settings.MAXROLL_REQUEST_INTERVAL,
        )

    def fetch(self, url: str) -> str:
        """The page's HTML. Raises MaxrollError."""
        url = normalise_url(url)
        for _ in range(MAX_REDIRECTS + 1):
            response = self._get(url)
            if response.is_redirect:
                url = normalise_url(urljoin(url, response.headers.get("Location", "")))
                continue
            if response.status_code in (403, 429, 503):
                raise MaxrollError(
                    f"maxroll.gg answered {response.status_code} for {url}. Stopping: don't "
                    "retry around it; ask Maxroll whether this client should be allowlisted."
                )
            if response.status_code != 200:
                raise MaxrollError(f"maxroll.gg answered {response.status_code} for {url}")
            return response.text
        raise MaxrollError(f"Too many redirects for {url}")

    def fetch_profile(self, profile_id: str) -> dict:
        """A Build Progression Tool profile from Maxroll's planner. Raises MaxrollError."""
        url = profile_url(profile_id)
        response = self._get(url)
        if response.status_code != 200:
            raise MaxrollError(f"Maxroll's planner answered {response.status_code} for {url}")
        try:
            profile = response.json()
        except ValueError as exc:
            raise MaxrollError(f"Maxroll's planner sent something unreadable for {url}") from exc
        if not isinstance(profile, dict):
            raise MaxrollError(f"Maxroll's planner sent something unreadable for {url}")
        return profile

    def load_guide(self, url: str) -> GuidePage:
        """The page with its Build Progression Tool, if it has one (a second request)."""
        url = normalise_url(url)
        html = self.fetch(url)
        ref = planner_ref(html)
        if ref is None:
            return parse_guide(url, html)
        try:
            profile = self.fetch_profile(ref[0])
        except (MaxrollError, ValueError) as exc:
            logger.warning("Storing %s without its progression tool: %s", url, exc)
            return parse_guide(url, html)
        return parse_guide(url, html, profile, ref[1])

    def _get(self, url: str) -> requests.Response:
        self._throttle()
        log = MaxrollRequest.objects.create(url=url, requested_at=timezone.now())
        try:
            response = self.session.get(url, timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as exc:
            raise MaxrollError(f"Couldn't fetch {url}: {exc}") from exc
        finally:
            self._last_request = self.clock()
        log.status = response.status_code
        log.save(update_fields=["status"])
        return response

    def _throttle(self) -> None:
        if self._last_request is None:
            return
        wait = self.request_interval - (self.clock() - self._last_request)
        if wait > 0:
            self.sleep(wait)


# --- storing ----------------------------------------------------------------------


@dataclass
class FetchResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: list[str] = field(default_factory=list)


def fetch_guides(urls: Iterable[str], client: MaxrollClient | None = None) -> FetchResult:
    """Fetch and store the given pages. Stops at the first licence or limit problem."""
    client = client or MaxrollClient.from_settings()
    result = FetchResult()
    for url in urls:
        try:
            page = client.load_guide(url)
        except (MaxrollError, ValueError) as exc:
            logger.warning("%s", exc)
            result.failed.append(url)
            continue
        outcome = store_guide(page)
        setattr(result, outcome, getattr(result, outcome) + 1)
    return result


def store_guide(page: GuidePage) -> str:
    """Save the page; returns "created", "updated" or "unchanged"."""
    text_hash = content_hash(page.text)
    with transaction.atomic():
        source, _ = Source.objects.update_or_create(
            wiki=WIKI_NAME,
            page_title=urlsplit(page.url).path.strip("/")[:255],
            defaults={
                "url": page.url,
                "fetched_at": timezone.now(),
                "author": page.author[:255],
                "updated_on": page.updated_on,
            },
        )
        existing = Document.objects.filter(source=source).first()
        if existing is not None and existing.content_hash == text_hash:
            if existing.title != page.title or existing.patch != page.patch:
                existing.title, existing.patch = page.title[:255], page.patch[:20]
                existing.save(update_fields=["title", "patch", "updated_at"])
            return "unchanged"
        Document.objects.update_or_create(
            source=source,
            defaults={
                "title": page.title[:255],
                "doc_type": DocumentType.GUIDE,
                "raw_text": page.text,
                "patch": page.patch[:20],
                "content_hash": text_hash,
            },
        )
    return "created" if existing is None else "updated"


# --- reading for a chat question --------------------------------------------------


def stored_guide(url: str, max_age: timedelta) -> GuidePage | None:
    """The stored copy of the page, if it was fetched within `max_age`."""
    document = (
        Document.objects.select_related("source")
        .filter(
            source__wiki=WIKI_NAME,
            source__url=url,
            source__fetched_at__gte=timezone.now() - max_age,
        )
        .first()
    )
    if document is None:
        return None
    source = document.source
    return GuidePage(
        source.url,
        document.title,
        source.author,
        source.updated_on,
        document.patch,
        document.raw_text,
    )


@contextmanager
def _shared_slot(
    interval: float, sleep: Callable[[float], None] = time.sleep, wait: float = SLOT_WAIT
) -> Iterator[None]:
    """Hold the fetch lock, at least `interval` after the last request by any process.

    The web server answers several questions at once, in several processes; the
    licence's one request per second counts for all of them together.
    """
    deadline = time.monotonic() + wait
    with connection.cursor() as cursor:
        while True:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_KEY])
            if cursor.fetchone()[0]:
                break
            if time.monotonic() >= deadline:
                raise MaxrollError("Another guide is being fetched from Maxroll. Try again.")
            sleep(0.25)
    try:
        latest = MaxrollRequest.objects.values_list("requested_at", flat=True).first()
        if latest is not None:
            remaining = interval - (timezone.now() - latest).total_seconds()
            if remaining > 0:
                sleep(min(remaining, interval))
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])


def read_guide(
    url: str,
    client: MaxrollClient | None = None,
    max_age: timedelta | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> GuidePage:
    """A page for a question in the chat: the stored copy while it is recent,
    otherwise fetched now and stored (indexed by the next build_index).

    Raises ValueError for a URL that isn't a Maxroll PoE page, MaxrollUnavailable
    when the licence or the monthly cap doesn't allow it, MaxrollError otherwise.
    """
    url = normalise_url(url)

    if max_age is None:
        max_age = timedelta(hours=settings.MAXROLL_CHAT_CACHE_HOURS)
    if page := stored_guide(url, max_age):
        return page
    client = client or MaxrollClient.from_settings()
    with _shared_slot(client.request_interval, sleep):
        if page := stored_guide(url, max_age):
            return page  # another question fetched it while this one waited
        page = client.load_guide(url)
    store_guide(page)
    return page


def purge() -> int:
    """Delete every stored Maxroll page with its document, chunks and embeddings."""
    count, _ = Source.objects.filter(wiki=WIKI_NAME).delete()
    return count


# --- quote limit ------------------------------------------------------------------


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def longest_shared_run(answer: str, source: str) -> int:
    """Length in words of the longest word sequence that appears in both texts."""
    a, b = _words(answer), _words(source)
    if not a or not b:
        return 0
    best = 0
    previous = [0] * (len(b) + 1)
    for word in a:
        current = [0] * (len(b) + 1)
        for j, other in enumerate(b, start=1):
            if word == other:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def long_quotes(
    answer: str, sources: dict[int, str], limit: int = MAX_QUOTE_WORDS
) -> dict[int, int]:
    """Source number -> words quoted, for guide sources quoted at more than `limit` words."""
    runs = {n: longest_shared_run(answer, text) for n, text in sources.items()}
    return {n: run for n, run in runs.items() if run > limit}
