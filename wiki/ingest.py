"""Fetch wiki pages and store them as `Source` + `Document` rows."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .client import WikiClient, WikiError
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
        logger.info("%s: %d pages", doc_type, len(titles))

        for title in titles:
            try:
                _ingest_page(client, title, doc_type, revisions.get(title), refresh, result)
            except (WikiError, KeyError) as exc:
                logger.error("Failed to ingest %r: %s", title, exc)
                result.failed.append(title)
    return result


def _ingest_page(
    client: WikiClient,
    title: str,
    doc_type: str,
    revision_id: int | None,
    refresh: bool,
    result: IngestResult,
) -> None:
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
        return

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
