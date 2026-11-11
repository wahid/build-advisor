from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from wiki.ingest import ingest
from wiki.models import DocumentType
from wiki.tasks import ingest_wiki


class Command(BaseCommand):
    help = "Fetch gems, uniques, ascendancies and mechanics from the Path of Exile wiki."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--type",
            dest="doc_types",
            action="append",
            choices=DocumentType.values,
            help="Document type to fetch (repeatable). Defaults to all types.",
        )
        parser.add_argument("--limit", type=int, help="Max pages per type (for testing).")
        parser.add_argument(
            "--refresh", action="store_true", help="Re-parse pages even if unchanged."
        )
        parser.add_argument(
            "--async", dest="run_async", action="store_true", help="Queue as a Celery task."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        kwargs = {
            "doc_types": options["doc_types"],
            "limit": options["limit"],
            "refresh": options["refresh"],
        }
        if options["run_async"]:
            task = ingest_wiki.delay(**kwargs)
            self.stdout.write(f"Queued ingest task {task.id}")
            return

        result = ingest(**kwargs)
        self.stdout.write(
            self.style.SUCCESS(
                f"Patch {result.patch}: {result.created} created, {result.updated} updated, "
                f"{result.unchanged} unchanged, {len(result.failed)} failed"
            )
        )
        for title in result.failed:
            self.stdout.write(self.style.WARNING(f"  failed: {title}"))
