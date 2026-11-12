"""Game names in a piece of text (gems, uniques, ascendancies), for hover cards."""

from __future__ import annotations

import re
from typing import Any

from .models import Chunk, DocumentType
from .search import titles_in

CARD_TYPES = (DocumentType.GEM, DocumentType.UNIQUE, DocumentType.ASCENDANCY)
MAX_ENTITIES = 25
SUMMARY_CHARS = 260


def summarize(title: str, intro: str) -> str:
    """The start of a page's intro, without the repeated title, cut at a word."""
    text = intro
    for _ in range(3):  # the title is often repeated (heading, infobox name)
        text = text.strip()
        if text.lower().startswith(title.lower()):
            text = text[len(title) :]
    text = re.sub(r"\s+", " ", text).strip(" -—:")
    if len(text) <= SUMMARY_CHARS:
        return text
    return text[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


def entities_in(text: str) -> list[dict[str, Any]]:
    """Gems, uniques and ascendancies whose page title appears in the text.

    A title inside a longer one that also appears ("Tornado" in "Tornado Shot")
    is left out, like the title search does.
    """
    if not text.strip():
        return []
    candidates = titles_in(text).filter(doc_type__in=CARD_TYPES).select_related("source")
    found = [d for d in candidates if d.title in text]  # exact case: as the answer writes it
    titles = [d.title for d in found]
    found = [
        d for d in found if not any(d.title != other and d.title in other for other in titles)
    ][:MAX_ENTITIES]
    intros = dict(
        Chunk.objects.filter(document__in=found, section="")
        .order_by("document_id", "-position")
        .values_list("document_id", "text")
    )  # dict() keeps the last row per document: the lowest position
    return [
        {
            "name": d.title,
            "doc_type": d.doc_type,
            "url": d.source.url,
            "summary": summarize(d.title, intros.get(d.id, "")),
        }
        for d in found
    ]
