"""Fetch wiki pages and store them as `Source` + `Document` rows."""

from __future__ import annotations

import hashlib
import logging
import queue
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .client import WikiBlockedError, WikiClient, WikiError, WikiPage
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
    workers: int | None = None,
) -> IngestResult:
    """Import pages for the given document types.

    Pages whose wiki revision hasn't changed since the last run are skipped
    unless `refresh` is set. Downloads run on `workers` threads (default
    `WIKI_WORKERS`), each with its own client and home proxy; database writes
    all happen on the calling thread.
    """
    client = client or WikiClient.from_settings()
    workers = max(workers or settings.WIKI_WORKERS, 1)
    clients = [client] if workers == 1 else [client.for_worker(i, workers) for i in range(workers)]
    types = list(doc_types or DocumentType.values)
    result = IngestResult(patch=settings.POE_PATCH or client.current_patch())
    logger.info(
        "Ingesting %s for patch %s with %d worker(s)", ", ".join(types), result.patch, workers
    )

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
        downloads: list[str] = []
        for title in titles:
            if _skip_unchanged(title, revisions.get(title), refresh, result):
                progress.step()
            else:
                downloads.append(title)
        try:
            _download_and_store(clients, downloads, doc_type, revisions, result, progress)
        except WikiBlockedError:
            logger.error("%s: stopped after %d/%d pages", doc_type, progress.done, len(titles))
            raise
    return result


def _download_and_store(
    clients: list[WikiClient],
    titles: list[str],
    doc_type: str,
    revisions: dict[str, int],
    result: IngestResult,
    progress: Progress,
) -> None:
    """Fetch pages on one thread per client and store each one as it arrives."""
    idle: queue.Queue[WikiClient] = queue.Queue()
    for c in clients:
        idle.put(c)

    def fetch(title: str) -> WikiPage:
        worker = idle.get()
        try:
            return worker.fetch_page(title, revisions.get(title))
        finally:
            idle.put(worker)

    with ThreadPoolExecutor(max_workers=len(clients), thread_name_prefix="wiki") as pool:
        pending: dict[Future[WikiPage], str] = {pool.submit(fetch, t): t for t in titles}
        try:
            blocked: WikiBlockedError | None = None
            while pending and blocked is None:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    title = pending.pop(future)
                    try:
                        page = future.result()
                        _store_page(clients[0], title, doc_type, page, result)
                    except WikiBlockedError as exc:
                        # Still store the other pages that finished; then stop.
                        blocked = exc
                    except (WikiError, KeyError) as exc:
                        logger.error("Failed to ingest %r: %s", title, exc)
                        result.failed.append(title)
                        progress.step(failed=True)
                    else:
                        progress.step(fetched=True)
            if blocked is not None:
                raise blocked
        except BaseException:
            # Blocked or interrupted: don't start any more downloads.
            pool.shutdown(wait=True, cancel_futures=True)
            raise


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


def _skip_unchanged(
    title: str, revision_id: int | None, refresh: bool, result: IngestResult
) -> bool:
    """True if the stored page is still current (and marks it for this patch)."""
    if refresh or revision_id is None:
        return False
    existing = (
        Source.objects.select_related("document")
        .filter(wiki=settings.WIKI_NAME, page_title=title)
        .first()
    )
    if existing is None or existing.revision_id != revision_id or not hasattr(existing, "document"):
        return False
    if existing.document.patch != result.patch:
        # Page wasn't edited since the patch changed: still current.
        Document.objects.filter(pk=existing.document.pk).update(patch=result.patch)
        Chunk.objects.filter(document_id=existing.document.pk).update(patch=result.patch)
    result.unchanged += 1
    return True


def _store_page(
    client: WikiClient, title: str, doc_type: str, page: WikiPage, result: IngestResult
) -> None:
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
