"""Turn documents into embedded chunks.

Two steps, both idempotent:

1. `build_chunks` re-chunks only documents whose text changed since the last
   run (`Document.chunked_hash`). Embeddings of chunks whose text is unchanged
   are carried over, so an edit to one section doesn't re-embed the page.
2. `embed_pending` embeds chunks that have no embedding yet, or one made with
   a different model.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from .chunking import chunk_text
from .embeddings import Embedder, get_embedder
from .ingest import content_hash
from .models import Chunk, Document

logger = logging.getLogger(__name__)


@dataclass
class ChunkResult:
    documents: int = 0
    chunks: int = 0
    reused_embeddings: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def documents_needing_chunks(force: bool = False) -> QuerySet[Document]:
    qs = Document.objects.select_related("source")
    return qs if force else qs.exclude(chunked_hash=F("content_hash"))


def build_chunks(documents: Iterable[Document] | None = None, force: bool = False) -> ChunkResult:
    result = ChunkResult()
    docs = documents if documents is not None else documents_needing_chunks(force)
    for document in docs:
        chunks, reused = _rebuild(document)
        result.documents += 1
        result.chunks += chunks
        result.reused_embeddings += reused
    logger.info("Chunked %(documents)d documents into %(chunks)d chunks", result.as_dict())
    return result


@transaction.atomic
def _rebuild(document: Document) -> tuple[int, int]:
    previous: dict[str, list[Chunk]] = defaultdict(list)
    for old in document.chunks.exclude(embedding=None):
        previous[old.text_hash].append(old)

    new_chunks: list[Chunk] = []
    reused = 0
    for data in chunk_text(document.title, document.raw_text, settings.CHUNK_MAX_CHARS):
        text_hash = content_hash(data.text)
        chunk = Chunk(
            document=document,
            position=data.position,
            section=data.section[:255],
            text=data.text,
            text_hash=text_hash,
            doc_type=document.doc_type,
            patch=document.patch,
            url=document.source.url,
        )
        if previous.get(text_hash):
            old = previous[text_hash].pop()
            chunk.embedding = old.embedding
            chunk.embedding_model = old.embedding_model
            chunk.embedded_at = old.embedded_at
            reused += 1
        new_chunks.append(chunk)

    document.chunks.all().delete()
    Chunk.objects.bulk_create(new_chunks)
    Document.objects.filter(pk=document.pk).update(chunked_hash=document.content_hash)
    return len(new_chunks), reused


def chunks_needing_embedding(model_name: str) -> QuerySet[Chunk]:
    return Chunk.objects.filter(Q(embedding=None) | ~Q(embedding_model=model_name))


def embed_pending(
    embedder: Embedder | None = None,
    batch_size: int | None = None,
    limit: int | None = None,
) -> int:
    """Embed chunks without a (current) embedding. Returns the number embedded."""
    embedder = embedder or get_embedder()
    batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE * 8
    pending = chunks_needing_embedding(embedder.model_name).order_by("id")
    total = pending.count() if limit is None else min(limit, pending.count())
    done = 0
    started = time.monotonic()

    while done < total:
        batch = list(pending.only("id", "text")[: min(batch_size, total - done)])
        if not batch:
            break
        vectors = embedder.embed_documents([chunk.text for chunk in batch])
        now = timezone.now()
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = embedder.model_name
            chunk.embedded_at = now
        Chunk.objects.bulk_update(batch, ["embedding", "embedding_model", "embedded_at"])
        done += len(batch)
        rate = done / max(time.monotonic() - started, 1e-6)
        logger.info("Embedded %d/%d chunks (%.1f/s)", done, total, rate)
    return done
