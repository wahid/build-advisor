"""A small, fixed slice of the wiki for evaluations in CI.

The full import takes hours, so CI evaluates against a committed corpus: the
pages the eval questions expect, "hard" distractors whose titles contain an
expected title (Vaal Righteous Fire next to Righteous Fire), and a seeded
random sample of other pages, roughly in the full set's type proportions.
"""

from __future__ import annotations

import gzip
import json
import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .ingest import content_hash
from .models import Document, Source

FIELDS = ("title", "doc_type", "url", "patch", "page_id", "revision_id", "raw_text")


@dataclass
class ExportResult:
    documents: int
    expected_found: int
    missing: list[str]
    hard_negatives: int


def select_documents(
    expected_titles: Iterable[str], distractors: int, seed: int
) -> tuple[list[Document], list[str], int]:
    wanted = {t.casefold(): t for t in expected_titles}
    all_docs = list(Document.objects.select_related("source").order_by("title"))
    by_title = {d.title.casefold(): d for d in all_docs}

    chosen: dict[int, Document] = {}
    for key in wanted:
        if key in by_title:
            chosen[by_title[key].pk] = by_title[key]
    missing = sorted(t for key, t in wanted.items() if key not in by_title)

    hard = [
        d
        for d in all_docs
        if d.pk not in chosen and any(key in d.title.casefold() for key in wanted)
    ]
    for document in hard:
        chosen[document.pk] = document

    rest = [d for d in all_docs if d.pk not in chosen]
    for document in random.Random(seed).sample(rest, min(distractors, len(rest))):
        chosen[document.pk] = document

    documents = sorted(chosen.values(), key=lambda d: d.title)
    return documents, missing, len(hard)


def write_corpus(documents: list[Document], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the gzip bytes identical for identical content (clean diffs).
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as fh:
        for d in documents:
            row = {
                "title": d.title,
                "doc_type": d.doc_type,
                "url": d.source.url,
                "patch": d.patch,
                "page_id": d.source.page_id,
                "revision_id": d.source.revision_id,
                "raw_text": d.raw_text,
            }
            fh.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))


def read_corpus(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    for row in rows:
        absent = [f for f in FIELDS if f not in row]
        if absent:
            raise ValueError(f"Corpus row {row.get('title')!r} lacks {absent}")
    return rows


@transaction.atomic
def load_corpus(path: Path) -> int:
    rows = read_corpus(path)
    now = timezone.now()
    for row in rows:
        source, _ = Source.objects.update_or_create(
            wiki=settings.WIKI_NAME,
            page_title=row["title"],
            defaults={
                "url": row["url"],
                "page_id": row["page_id"],
                "revision_id": row["revision_id"],
                "fetched_at": now,
            },
        )
        Document.objects.update_or_create(
            source=source,
            defaults={
                "title": row["title"],
                "doc_type": row["doc_type"],
                "raw_text": row["raw_text"],
                "patch": row["patch"],
                "content_hash": content_hash(row["raw_text"]),
            },
        )
    return len(rows)
