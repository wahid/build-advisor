from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from wiki.indexing import build_chunks, embed_pending
from wiki.tasks import build_index


class Command(BaseCommand):
    help = "Chunk changed documents and embed chunks that have no embedding yet."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--force", action="store_true", help="Re-chunk every document.")
        parser.add_argument(
            "--no-embed", action="store_true", help="Only build chunks, skip embedding."
        )
        parser.add_argument("--limit", type=int, help="Max chunks to embed (for testing).")
        parser.add_argument(
            "--async", dest="run_async", action="store_true", help="Queue as a Celery task."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        embed = not options["no_embed"]
        if options["run_async"]:
            task = build_index.delay(force=options["force"], embed=embed)
            self.stdout.write(f"Queued index task {task.id}")
            return

        chunks = build_chunks(force=options["force"])
        self.stdout.write(
            f"Chunked {chunks.documents} documents into {chunks.chunks} chunks "
            f"({chunks.reused_embeddings} embeddings reused)"
        )
        if embed:
            embedded = embed_pending(limit=options["limit"])
            self.stdout.write(self.style.SUCCESS(f"Embedded {embedded} chunks"))
