"""Hybrid retrieval over chunks.

Three ranked candidate lists are merged with reciprocal rank fusion (RRF):

1. **Vector** — cosine similarity between the question and chunk embeddings.
   Finds chunks that mean the same thing in other words.
2. **Keyword** — Postgres full-text search (OR over the question's words,
   ranked by cover density). Finds exact names like "Cast when Damage Taken".
3. **Title** — chunks of pages whose title appears literally in the question
   ("Righteous Fire", "Chieftain"), ordered by vector similarity.

RRF only uses ranks, so the lists don't need comparable scores.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, QuerySet, Value
from django.db.models.functions import Length, Lower, StrIndex
from pgvector.django import CosineDistance

from .embeddings import Embedder, get_embedder
from .models import Chunk, Document

RRF_K = 60  # standard constant; dampens the advantage of the very top ranks
MIN_TITLE_LENGTH = 4  # ignore titles like "Ice" that match inside other words
WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


@dataclass
class SearchHit:
    chunk: Chunk
    score: float
    ranks: dict[str, int] = field(default_factory=dict)  # list name -> 1-based rank

    @property
    def title(self) -> str:
        return self.chunk.document.title


@dataclass(frozen=True)
class SearchFilters:
    doc_types: tuple[str, ...] = ()
    patch: str = ""

    def apply(self, qs: QuerySet[Chunk]) -> QuerySet[Chunk]:
        if self.doc_types:
            qs = qs.filter(doc_type__in=self.doc_types)
        if self.patch:
            qs = qs.filter(patch=self.patch)
        return qs


def hybrid_search(
    question: str,
    top_k: int | None = None,
    filters: SearchFilters | None = None,
    embedder: Embedder | None = None,
    candidates: int | None = None,
    max_per_document: int | None = None,
) -> list[SearchHit]:
    top_k = top_k or settings.SEARCH_TOP_K
    candidates = candidates or settings.SEARCH_CANDIDATES
    max_per_document = max_per_document or settings.SEARCH_MAX_PER_DOCUMENT
    filters = filters or SearchFilters()
    embedder = embedder or get_embedder()

    base = filters.apply(Chunk.objects.exclude(embedding=None))
    query_vector = embedder.embed_query(question)

    ranked_lists = {
        "vector": _vector_ids(base, query_vector, candidates),
        "keyword": _keyword_ids(base, question, candidates),
        "title": _title_ids(base, question, query_vector, candidates),
    }
    return _fuse(ranked_lists, top_k, max_per_document)


def _vector_ids(base: QuerySet[Chunk], vector: list[float], limit: int) -> list[int]:
    qs = base.order_by(CosineDistance("embedding", vector)).values_list("id", flat=True)
    return list(qs[:limit])


def keyword_query(question: str) -> SearchQuery | None:
    """OR-query over the question's words; Postgres drops stop words and stems."""
    words = list(dict.fromkeys(WORD_RE.findall(question.lower())))
    if not words:
        return None
    raw = " | ".join(word.replace("'", "") for word in words)
    return SearchQuery(raw, search_type="raw", config="english")


def _keyword_ids(base: QuerySet[Chunk], question: str, limit: int) -> list[int]:
    query = keyword_query(question)
    if query is None:
        return []
    qs = (
        base.filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query, cover_density=True))
        .order_by("-rank", "id")
        .values_list("id", flat=True)
    )
    return list(qs[:limit])


def titles_in(question: str) -> QuerySet[Document]:
    """Documents whose title occurs in the question (case-insensitive)."""
    return (
        Document.objects.annotate(title_length=Length("title"))
        .filter(title_length__gte=MIN_TITLE_LENGTH)
        .annotate(position=StrIndex(Lower(Value(question)), Lower("title")))
        .filter(position__gt=0)
    )


def _title_ids(base: QuerySet[Chunk], question: str, vector: list[float], limit: int) -> list[int]:
    matching = titles_in(question).values("id")
    qs = (
        base.filter(document_id__in=matching)
        .order_by(CosineDistance("embedding", vector))
        .values_list("id", flat=True)
    )
    return list(qs[:limit])


def _fuse(ranked_lists: dict[str, list[int]], top_k: int, max_per_document: int) -> list[SearchHit]:
    scores: dict[int, float] = defaultdict(float)
    ranks: dict[int, dict[str, int]] = defaultdict(dict)
    for name, ids in ranked_lists.items():
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] += 1 / (RRF_K + rank)
            ranks[chunk_id][name] = rank

    ordered = sorted(scores, key=lambda cid: (-scores[cid], cid))
    chunks = Chunk.objects.select_related("document").in_bulk(ordered)

    hits: list[SearchHit] = []
    per_document: dict[int, int] = defaultdict(int)
    for chunk_id in ordered:
        chunk = chunks[chunk_id]
        if per_document[chunk.document_id] >= max_per_document:
            continue
        per_document[chunk.document_id] += 1
        hits.append(SearchHit(chunk=chunk, score=scores[chunk_id], ranks=ranks[chunk_id]))
        if len(hits) == top_k:
            break
    return hits
