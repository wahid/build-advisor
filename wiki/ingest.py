"""Fetch wiki pages and store them as `Source` + `Document` rows."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .client import WikiBlockedError, WikiClient, WikiError
from .models import Chunk, Document, DocumentType, Source
from .parsing import html_to_text

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    patch: str = ""
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class Progress:
    """Logs progress every `every` downloads or `interval` seconds, whichever comes first.

    The time estimate is based on downloads only: skipped pages take no time.
    """

    def __init__(
        self,
        label: str,
        total: int,
        to_fetch: int,
        every: int = 10,
        interval: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.label = label
        self.total = total
        self.to_fetch = to_fetch
        self.every = every
        self.interval = interval
        self.clock = clock
        self.started = clock()
        self.last_report = self.started
        self.done = 0
        self.fetched = 0
        self.failed = 0

    def step(self, fetched: bool = False, failed: bool = False) -> None:
        self.done += 1
        self.fetched += fetched or failed
        self.failed += failed
        now = self.clock()
        due = (fetched or failed) and self.fetched % self.every == 0
        if due or now - self.last_report >= self.interval or self.done == self.total:
            self.last_report = now
            logger.info(self.message(now))

    def message(self, now: float | None = None) -> str:
        now = self.clock() if now is None else now
        percent = 100 * self.done // max(self.total, 1)
        text = (
            f"{self.label}: {self.done}/{self.total} pages ({percent}%), "
            f"downloaded {self.fetched}/{self.to_fetch}"
        )
        if self.failed:
            text += f", {self.failed} failed"
        remaining = self.to_fetch - self.fetched
        if self.fetched and remaining > 0:
            seconds = (now - self.started) / self.fetched * remaining
            text += f", ~{_duration(seconds)} left"
        return text


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "<1 min"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest(
    doc_types: Iterable[str] | None = None,
    limit: int | None = None,
    refresh: bool = False,
    client: WikiClient | None = None,
) -> IngestResult:
    """Import pages for the given document types.

    Pages whose wiki revision hasn't changed since the last run are skipped
    unless `refresh` is set.
    """
    client = client or WikiClient.from_settings()
    types = list(doc_types or DocumentType.values)
    result = IngestResult(patch=settings.POE_PATCH or client.current_patch())
    logger.info("Ingesting %s for patch %s", ", ".join(types), result.patch)

    for doc_type in types:
        titles = client.list_titles(doc_type)
        if limit is not None:
            titles = titles[:limit]
        revisions = client.revision_ids(titles)
        to_fetch = _count_to_fetch(titles, revisions, refresh)
        logger.info(
            "%s: %d pages, %d to download, %d unchanged",
            doc_type,
            len(titles),
            to_fetch,
            len(titles) - to_fetch,
        )

        progress = Progress(doc_type, total=len(titles), to_fetch=to_fetch)
        for title in titles:
            try:
                fetched = _ingest_page(
                    client, title, doc_type, revisions.get(title), refresh, result
                )
            except WikiBlockedError:
                logger.error("%s: stopped after %d/%d pages", doc_type, progress.done, len(titles))
                raise
            except (WikiError, KeyError) as exc:
                logger.error("Failed to ingest %r: %s", title, exc)
                result.failed.append(title)
                progress.step(failed=True)
            else:
                progress.step(fetched=fetched)
    return result


def _count_to_fetch(titles: list[str], revisions: dict[str, int], refresh: bool) -> int:
    if refresh:
        return len(titles)
    saved = dict(
        Source.objects.filter(
            wiki=settings.WIKI_NAME, page_title__in=titles, document__isnull=False
        ).values_list("page_title", "revision_id")
    )
    return sum(
        1
        for title in titles
        if revisions.get(title) is None or saved.get(title) != revisions.get(title)
    )


def _ingest_page(
    client: WikiClient,
    title: str,
    doc_type: str,
    revision_id: int | None,
    refresh: bool,
    result: IngestResult,
) -> bool:
    """Store one page. Returns True if it was downloaded, False if skipped."""
    existing = (
        Source.objects.select_related("document")
        .filter(wiki=settings.WIKI_NAME, page_title=title)
        .first()
    )
    if (
        not refresh
        and existing is not None
        and revision_id is not None
        and existing.revision_id == revision_id
        and hasattr(existing, "document")
    ):
        if existing.document.patch != result.patch:
            # Page wasn't edited since the patch changed: still current.
            Document.objects.filter(pk=existing.document.pk).update(patch=result.patch)
            Chunk.objects.filter(document_id=existing.document.pk).update(patch=result.patch)
        result.unchanged += 1
        return False

    page = client.fetch_page(title, revision_id)
    text = html_to_text(page.html)

    with transaction.atomic():
        source, _ = Source.objects.update_or_create(
            wiki=settings.WIKI_NAME,
            page_title=title,
            defaults={
                "url": client.page_url_for(title),
                "page_id": page.page_id,
                "revision_id": page.revision_id,
                "fetched_at": timezone.now(),
            },
        )
        _, created = Document.objects.update_or_create(
            source=source,
            defaults={
                "title": title,
                "doc_type": doc_type,
                "raw_text": text,
                "patch": result.patch,
                "content_hash": content_hash(text),
            },
        )
    if created:
        result.created += 1
    else:
        result.updated += 1
    return True
