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
from collections.abc import Sequence
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, QuerySet, Value
from django.db.models.functions import Length, Lower, StrIndex
from pgvector.django import CosineDistance

from .embeddings import Embedder, get_embedder
from .models import Chunk, Document
from .rerank import Reranker, get_reranker, passage, reorder

RRF_K = 60  # standard constant; dampens the advantage of the very top ranks
# Words in more than this share of chunks ("support", "gem") carry no signal.
KEYWORD_MAX_SHARE = 0.15
KEYWORD_MIN_TERMS = 2  # always keep at least this many of the rarest words
# One-word titles found in this many chunks are common words, not page names.
GENERIC_TITLE_SHARE = 0.03
GENERIC_TITLE_MIN_CHUNKS = 200
# ts_rank normalisation flag 1: divide by 1 + log(length), so long chunks
# don't win just by containing more words.
RANK_NORMALIZATION = 1
MIN_TITLE_LENGTH = 4  # ignore titles like "Ice" that match inside other words
# Reference sections (lists of items, mods, passives, patch notes) match many
# questions by their words but rarely explain anything, so they count for less
# unless the question asks for that kind of list.
LISTING_SECTION_RE = re.compile(
    r"^(version history|item acquisition|related |unique items|items|legacy variants"
    r"|gem level progression|alternate artwork|design attribution|foulborn modifiers"
    r"|helmet enchantments|base items|skill gems|support gems|changes from default)",
    re.IGNORECASE,
)
LISTING_QUESTION_RE = re.compile(
    r"\b(which|what) (uniques?|items?|gems?|supports?|passives?|notables?|mods?|modifiers?"
    r"|enchant\w*|bases?)\b|\blist\b|\bversion\b|\bhistory\b|\bchanged?\b|\bpatch"
    r"|\bnerf|\bbuff|\bdrops?\b|\bobtain|\bacquir|\bfarm|\brecipe|\bvendor",
    re.IGNORECASE,
)
LISTING_WEIGHT = 0.5
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
    expansion: str = "",
    pinned: Sequence[str] = (),
    rerank: bool | None = None,
    reranker: Reranker | None = None,
) -> list[SearchHit]:
    """Search chunks for a question.

    `expansion` holds extra search terms (e.g. wiki terms an LLM derived from
    the question). They feed the keyword and title lists and a fourth vector
    list; the original question's vector list is kept, so they only add.

    `pinned` holds page titles that must come first (e.g. the skills and items
    of an attached build): the intro of each exactly matching page, in the
    given order, up to half of the results. The search fills the rest.
    """
    top_k = top_k or settings.SEARCH_TOP_K
    candidates = candidates or settings.SEARCH_CANDIDATES
    max_per_document = max_per_document or settings.SEARCH_MAX_PER_DOCUMENT
    filters = filters or SearchFilters()
    embedder = embedder or get_embedder()

    base = filters.apply(Chunk.objects.exclude(embedding=None))
    query_vector = embedder.embed_query(question)

    text = f"{question}\n{expansion}" if expansion else question
    ranked_lists = {
        "vector": _vector_ids(base, query_vector, candidates),
        "keyword": _keyword_ids(base, text, candidates),
        "title": _title_ids(base, text, query_vector, candidates),
    }
    if expansion:
        expanded_vector = embedder.embed_query(text)
        ranked_lists["rewrite"] = _vector_ids(base, expanded_vector, candidates)
    ranked_lists["intro"] = _intro_ids(base, ranked_lists, candidates)
    first = _pinned_ids(base, pinned, top_k // 2 + 1) if pinned else []
    listing_weight = 1.0 if LISTING_QUESTION_RE.search(text) else LISTING_WEIGHT
    if not (settings.SEARCH_RERANK if rerank is None else rerank):
        return _fuse(
            ranked_lists, top_k, max_per_document, first=first, listing_weight=listing_weight
        )
    pool = max(top_k, settings.SEARCH_RERANK_POOL)
    hits = _fuse(ranked_lists, pool, max_per_document, first=first, listing_weight=listing_weight)
    return _rerank(question, hits, set(first), top_k, reranker or get_reranker())


def _rerank(
    question: str, hits: list[SearchHit], pinned: set[int], top_k: int, reranker: Reranker
) -> list[SearchHit]:
    """Reorder the unpinned hits with the cross-encoder; pinned ones stay first."""
    kept = [h for h in hits if h.chunk.id in pinned]
    rest = {h.chunk.id: h for h in hits if h.chunk.id not in pinned}
    passages = {cid: passage(h.title, h.chunk.section, h.chunk.text) for cid, h in rest.items()}
    order = reorder(question, list(rest), passages, reranker, settings.SEARCH_RERANK_MODE)
    for rank, chunk_id in enumerate(order, start=1):
        rest[chunk_id].ranks["rerank"] = rank
    return [*kept, *(rest[cid] for cid in order)][:top_k]


def _pinned_ids(base: QuerySet[Chunk], titles: Sequence[str], limit: int) -> list[int]:
    """Intro chunks of the pages titled exactly (ignoring case) as given, in that order.

    Path of Building names support gems without the wiki's " Support" suffix
    ("Volatility" is the page "Volatility Support"), so that title counts too.
    """
    wanted = list(dict.fromkeys(t.strip().lower() for t in titles if t.strip()))
    variants = {t: (t, f"{t} support") for t in wanted}
    intros: dict[str, int] = {}
    rows = (
        base.filter(section="")
        .annotate(lower_title=Lower("document__title"))
        .filter(lower_title__in=[v for pair in variants.values() for v in pair])
        .order_by("document_id", "-position")
        .values_list("lower_title", "id")
    )
    for title, chunk_id in rows:  # the last row per page is its lowest position
        intros[title] = chunk_id
    found = [next((intros[v] for v in variants[t] if v in intros), None) for t in wanted]
    return [chunk_id for chunk_id in found if chunk_id is not None][:limit]


def _intro_ids(base: QuerySet[Chunk], ranked_lists: dict[str, list[int]], limit: int) -> list[int]:
    """The opening chunk of each page that the other lists found, best page first.

    A page's intro says what the thing is or does ("Freeze prevents ..."), but
    questions often match a later section better, so the intro can be missed.
    """
    best_rank: dict[int, int] = {}
    for ids in ranked_lists.values():
        for rank, chunk_id in enumerate(ids):
            best_rank[chunk_id] = min(rank, best_rank.get(chunk_id, rank))
    documents: dict[int, int] = {}
    for chunk_id, document_id in Chunk.objects.filter(id__in=best_rank).values_list(
        "id", "document_id"
    ):
        documents[document_id] = min(best_rank[chunk_id], documents.get(document_id, limit))
    ordered = sorted(documents, key=lambda d: (documents[d], d))[:limit]
    intros = dict(
        base.filter(document_id__in=ordered, section="")
        .order_by("document_id", "-position")
        .values_list("document_id", "id")
    )  # dict() keeps the last row per document: the lowest position
    return [intros[d] for d in ordered if d in intros]


def _vector_ids(base: QuerySet[Chunk], vector: list[float], limit: int) -> list[int]:
    qs = base.order_by(CosineDistance("embedding", vector)).values_list("id", flat=True)
    return list(qs[:limit])


def question_words(question: str) -> list[str]:
    return [w.replace("'", "") for w in dict.fromkeys(WORD_RE.findall(question.lower()))]


def _term_query(raw: str) -> SearchQuery:
    return SearchQuery(raw, search_type="raw", config="english")


def informative_words(base: QuerySet[Chunk], words: list[str]) -> list[str]:
    """Drop stop words and words that occur in too many chunks.

    Postgres full-text ranking has no notion of how common a word is, so
    without this a question full of "support gems" matches every gem page.
    """
    total = base.count()
    if not total:
        return []
    frequency = {word: base.filter(search_vector=_term_query(word)).count() for word in words}
    present = sorted((n, word) for word, n in frequency.items() if n > 0)
    keep = {word for n, word in present if n / total <= KEYWORD_MAX_SHARE}
    keep |= {word for _, word in present[:KEYWORD_MIN_TERMS]}
    return [word for word in words if word in keep]


def keyword_query(question: str, base: QuerySet[Chunk] | None = None) -> SearchQuery | None:
    """OR-query over the question's informative words (stemmed by Postgres)."""
    words = question_words(question)
    if base is not None:
        words = informative_words(base, words)
    if not words:
        return None
    return _term_query(" | ".join(words))


def _keyword_ids(base: QuerySet[Chunk], question: str, limit: int) -> list[int]:
    query = keyword_query(question, base)
    if query is None:
        return []
    rank = SearchRank(
        F("search_vector"), query, cover_density=True, normalization=Value(RANK_NORMALIZATION)
    )
    qs = (
        base.filter(search_vector=query)
        .annotate(rank=rank)
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


def _generic_title(base: QuerySet[Chunk], title: str) -> bool:
    """A one-word title that is also a common word ("Damage", "Life", "Charge").

    Such a title appearing in a question says nothing about what the question
    is about, so it shouldn't count as naming that page.
    """
    words = question_words(title)
    if len(words) != 1:
        return False
    total = base.count()
    count = base.filter(search_vector=_term_query(words[0])).count()
    return count >= GENERIC_TITLE_MIN_CHUNKS and count / max(total, 1) >= GENERIC_TITLE_SHARE


def _title_ids(base: QuerySet[Chunk], question: str, vector: list[float], limit: int) -> list[int]:
    """Chunks of pages named in the question, interleaved per page.

    Each named page contributes its most similar chunk first, then its second,
    and so on, so a long page can't push a shorter named page out of the list.
    """
    named = [d for d in titles_in(question) if not _generic_title(base, d.title)]
    # "Tornado Shot" also contains the page "Tornado"; only the longer title was meant.
    matching = [
        d.id
        for d in named
        if not any(
            d.title.lower() in o.title.lower() and d.id != o.id and len(o.title) > len(d.title)
            for o in named
        )
    ]
    rows = (
        base.filter(document_id__in=matching)
        .order_by(CosineDistance("embedding", vector))
        .values_list("id", "document_id")
    )
    per_document: dict[int, list[int]] = defaultdict(list)
    for chunk_id, document_id in rows[: limit * 10]:
        per_document[document_id].append(chunk_id)

    interleaved: list[int] = []
    queues = list(per_document.values())  # first-seen order = best chunk first
    while queues and len(interleaved) < limit:
        for queue in queues:
            if queue:
                interleaved.append(queue.pop(0))
        queues = [q for q in queues if q]
    return interleaved[:limit]


def _fuse(
    ranked_lists: dict[str, list[int]],
    top_k: int,
    max_per_document: int,
    first: Sequence[int] = (),
    listing_weight: float = 1.0,
) -> list[SearchHit]:
    scores: dict[int, float] = defaultdict(float)
    ranks: dict[int, dict[str, int]] = defaultdict(dict)
    for name, ids in ranked_lists.items():
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] += 1 / (RRF_K + rank)
            ranks[chunk_id][name] = rank
    for rank, chunk_id in enumerate(first, start=1):
        ranks[chunk_id]["pinned"] = rank

    chunks = Chunk.objects.select_related("document").in_bulk([*scores, *first])
    if listing_weight != 1.0:
        for chunk_id in scores:
            if LISTING_SECTION_RE.match(chunks[chunk_id].section):
                scores[chunk_id] *= listing_weight
    fused = sorted(scores, key=lambda cid: (-scores[cid], cid))
    ordered = list(dict.fromkeys([*first, *fused]))

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
