"""Retrieval-augmented answering.

`answer_stream` yields events so callers (the SSE endpoint, the CLI) can show
sources first and then the answer as it streams in:

    {"type": "sources", "sources": [...]}
    {"type": "delta", "text": "..."}            (repeated)
    {"type": "done", "cited": [1, 3], "patch": "3.29.3c"}
    {"type": "error", "message": "..."}         (instead of done, on failure)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from wiki.embeddings import Embedder
from wiki.search import SearchFilters, SearchHit, hybrid_search

from .llm import LLMError, LLMProvider, get_provider
from .prompts import NO_SOURCES_ANSWER, build_messages

logger = logging.getLogger(__name__)

CITATION_RE = re.compile(r"\[(\d+)\]")

Event = dict[str, Any]


@dataclass(frozen=True)
class Source:
    number: int
    title: str
    section: str
    url: str
    patch: str
    doc_type: str

    @classmethod
    def from_hit(cls, number: int, hit: SearchHit) -> Source:
        chunk = hit.chunk
        return cls(number, hit.title, chunk.section, chunk.url, chunk.patch, chunk.doc_type)


@dataclass
class Answer:
    text: str = ""
    sources: list[Source] = field(default_factory=list)
    cited: list[int] = field(default_factory=list)
    patch: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def cited_numbers(text: str, source_count: int) -> list[int]:
    return sorted({n for n in map(int, CITATION_RE.findall(text)) if 1 <= n <= source_count})


def answer_stream(
    question: str,
    filters: SearchFilters | None = None,
    provider: LLMProvider | None = None,
    embedder: Embedder | None = None,
    top_k: int | None = None,
) -> Iterator[Event]:
    hits = hybrid_search(question, top_k=top_k, filters=filters, embedder=embedder)
    sources = [Source.from_hit(n, hit) for n, hit in enumerate(hits, start=1)]
    yield {"type": "sources", "sources": [asdict(s) for s in sources]}

    patch = ", ".join(sorted({s.patch for s in sources}))
    if not hits:
        yield {"type": "delta", "text": NO_SOURCES_ANSWER}
        yield {"type": "done", "cited": [], "patch": patch}
        return

    provider = provider or get_provider()
    parts: list[str] = []
    try:
        for text in provider.stream(build_messages(question, hits)):
            parts.append(text)
            yield {"type": "delta", "text": text}
    except LLMError as exc:
        logger.error("LLM failed for %r: %s", question, exc)
        yield {"type": "error", "message": "The language model is unavailable. Try again later."}
        return

    full = "".join(parts)
    logger.debug(
        "Answered %r with %s/%s: %d chars, %d sources",
        question,
        provider.name,
        provider.model,
        len(full),
        len(sources),
    )
    yield {"type": "done", "cited": cited_numbers(full, len(sources)), "patch": patch}


def answer(question: str, **kwargs: Any) -> Answer:
    """Non-streaming convenience wrapper around `answer_stream`."""
    result = Answer()
    for event in answer_stream(question, **kwargs):
        match event["type"]:
            case "sources":
                result.sources = [Source(**s) for s in event["sources"]]
            case "delta":
                result.text += event["text"]
            case "done":
                result.cited = event["cited"]
                result.patch = event["patch"]
            case "error":
                result.error = event["message"]
    return result
