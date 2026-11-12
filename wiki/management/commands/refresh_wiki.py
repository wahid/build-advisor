"""Bring the wiki data up to date: download changed and new pages, then reindex.

Meant to run weekly (see deploy/server-setup.sh). It asks the wiki for the
current revision of every page in batches and downloads only pages that
changed, so a quiet week costs a few hundred small API requests.

Like fetch_wiki, downloads go through the configured proxies (WIKI_PROXIES /
proxies.txt) when there are any; --direct skips them.
"""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from wiki.client import WikiBlockedError
from wiki.indexing import build_chunks, embed_pending
from wiki.ingest import ingest
from wiki.models import DocumentType


class Command(BaseCommand):
    help = "Download changed and new wiki pages (including recent patch notes) and reindex them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--type",
            dest="doc_types",
            action="append",
            choices=DocumentType.values,
            help="Only these page types (repeatable). Default: all.",
        )
        parser.add_argument(
            "--direct",
            action="store_true",
            help="Skip the proxies: one worker on this machine's own connection, throttled "
            "and backing off on rate limits.",
        )
        parser.add_argument("--no-embed", action="store_true", help="Skip embedding new chunks.")

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        try:
            result = ingest(doc_types=options["doc_types"], direct=options["direct"])
        except WikiBlockedError as exc:
            raise CommandError(
                f"{exc}\nNothing was reindexed; pages saved so far are kept. Try again later."
            ) from exc
        self.stdout.write(
            f"Patch {result.patch}: {result.created} new, {result.updated} changed, "
            f"{result.unchanged} unchanged, {len(result.failed)} failed"
        )
        for title in result.failed:
            self.stdout.write(self.style.WARNING(f"  failed: {title}"))

        chunks = build_chunks()
        embedded = 0 if options["no_embed"] else embed_pending()
        self.stdout.write(
            self.style.SUCCESS(
                f"Reindexed {chunks.documents} documents into {chunks.chunks} chunks, "
                f"embedded {embedded} new chunks in {time.monotonic() - started:.0f}s"
            )
        )
