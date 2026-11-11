"""Web search through DeepSeek's Search API, offered to the model as a tool.

Only on when DeepSeek is the provider (it uses the same API key). Results are
limited to a list of Path of Exile sites, because much of what the open web
says about the game is from older leagues. Each result becomes a numbered
source, so the model cites it as [n] and the app shows where it came from.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 128  # the API's limit
MAX_TITLE_CHARS = 120
TOOL_NAME = "web_search"
# jp.pathofexile.com, es.pathofexile.com, ...: translations of the English pages.
TRANSLATED_HOST_RE = re.compile(r"^[a-z]{2}\.pathofexile\.com$")

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Search Path of Exile sites on the web (official site and patch notes, "
            "the wiki, guide sites, r/pathofexile). Use it only for what the wiki "
            "sources don't cover: the current league, recent patch notes and balance "
            "changes, or what players currently use. Results come back as numbered "
            "sources to cite like the wiki sources."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A short English query, e.g. 'PoE 3.29 patch notes'.",
                }
            },
            "required": ["query"],
        },
    },
}


class WebSearchError(RuntimeError):
    """The search failed; the message is shown to the model."""


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    site: str
    date: str  # YYYY-MM-DD or ""
    summary: str


def enabled() -> bool:
    return bool(settings.WEB_SEARCH_ENABLED and settings.LLM_API_KEY)


def allowed(url: str, sites: list[str]) -> bool:
    """True if the URL's host is one of the sites or a subdomain of one (empty = all)."""
    if not sites:
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(host == site or host.endswith(f".{site}") for site in sites)


def clean_url(url: str) -> str:
    """https, no tracking query string or fragment: one URL per page."""
    parts = urlparse(url)
    return f"https://{(parts.hostname or '').lower()}{parts.path.rstrip('/')}"


def search(query: str, question: str = "", skip_urls: set[str] | None = None) -> list[WebResult]:
    """Results from the allowed sites, without translations or pages in `skip_urls`."""
    query = " ".join(query.split())[:MAX_QUERY_CHARS]
    if not query:
        raise WebSearchError("The search query is empty.")
    payload = {"query": query, "count": settings.WEB_SEARCH_CANDIDATES}
    if question:
        payload["ori_question"] = " ".join(question.split())[:MAX_QUERY_CHARS]
    try:
        response = requests.post(
            settings.WEB_SEARCH_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            timeout=settings.WEB_SEARCH_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("Web search failed: %s", exc)
        raise WebSearchError("The web search didn't respond. Answer without it.") from exc
    if response.status_code != 200:
        logger.warning("Web search returned %s: %s", response.status_code, response.text[:300])
        raise WebSearchError(f"The web search failed ({response.status_code}). Answer without it.")
    try:
        items = response.json().get("results", [])
    except (ValueError, AttributeError) as exc:
        raise WebSearchError("The web search returned something unreadable.") from exc

    seen = set(skip_urls or ())
    results: list[WebResult] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("url", ""))
        if not raw.startswith(("https://", "http://")):
            continue
        url = clean_url(raw)
        host = urlparse(url).hostname or ""
        if url in seen or TRANSLATED_HOST_RE.match(host):
            continue
        if not allowed(url, settings.WEB_SEARCH_SITES):
            continue
        seen.add(url)
        title = " ".join(str(item.get("title") or url).split())
        if len(title) > MAX_TITLE_CHARS:
            title = title[: MAX_TITLE_CHARS - 1] + "…"
        results.append(
            WebResult(
                title=title,
                url=url,
                site=str(item.get("site_name") or urlparse(url).hostname or "")[:80],
                date=str(item.get("date") or "")[:10],
                summary=str(item.get("summary") or item.get("snippet") or "")[:1200],
            )
        )
        if len(results) == settings.WEB_SEARCH_RESULTS:
            break
    return results
