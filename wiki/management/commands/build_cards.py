"""Tooltip cards for pages fetched before cards existed, and moving them between databases.

    build_cards                 parse cards from the local page cache (data/raw)
    build_cards --export FILE   write title -> card as gzipped JSON lines
    build_cards --load FILE     set cards from such a file (pages missing one only)

New and changed pages get their card when they're fetched; this fills the rest.
The server has no page cache, so the cards ship as wiki/fixtures/cards.jsonl.gz,
which a migration loads.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from wiki.cards import parse_card
from wiki.client import WikiClient
from wiki.models import Document, DocumentType

CARD_TYPES = (DocumentType.GEM, DocumentType.UNIQUE, DocumentType.ASCENDANCY)


def load_cards(path: Path) -> int:
    """Set cards from an exported file on pages that don't have one; returns how many."""
    cards = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            cards[row["title"]] = row["card"]
    updated = 0
    for document in Document.objects.filter(card__isnull=True, title__in=list(cards)):
        document.card = cards[document.title]
        document.save(update_fields=["card"])
        updated += 1
    return updated


class Command(BaseCommand):
    help = "Build in-game style tooltip cards from the page cache, or export/load them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--export", type=Path, help="Write cards to this .jsonl.gz file.")
        parser.add_argument("--load", type=Path, help="Load cards from this .jsonl.gz file.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["load"]:
            self.stdout.write(f"Loaded {load_cards(options['load'])} cards")
            return
        if options["export"]:
            documents = Document.objects.filter(card__isnull=False).order_by("title")
            with gzip.open(options["export"], "wt", encoding="utf-8") as handle:
                for document in documents:
                    row = {"title": document.title, "card": document.card}
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.stdout.write(f"Exported {documents.count()} cards to {options['export']}")
            return

        client = WikiClient.from_settings(direct=True)  # only its page cache is used
        built = missing = 0
        documents = Document.objects.filter(card__isnull=True, doc_type__in=CARD_TYPES)
        for document in documents.select_related("source"):
            page = client._read_cache(document.title, document.source.revision_id or 0)
            if page is None:
                missing += 1
                continue
            card = parse_card(page.html)
            if card is not None:
                document.card = card
                document.save(update_fields=["card"])
                built += 1
        self.stdout.write(
            self.style.SUCCESS(f"Built {built} cards ({missing} pages not in the cache)")
        )
