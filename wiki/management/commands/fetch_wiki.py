from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from wiki.client import WikiBlockedError
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
            "--direct",
            action="store_true",
            help="Skip the proxies: one worker on this machine's own connection, throttled "
            "and backing off on rate limits. Handy for retrying pages that failed via proxies.",
        )
        parser.add_argument(
            "--async", dest="run_async", action="store_true", help="Queue as a Celery task."
        )
        parser.add_argument(
            "--list-only",
            action="store_true",
            help="Only show how many pages each type has; download nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        kwargs = {
            "doc_types": options["doc_types"],
            "limit": options["limit"],
            "refresh": options["refresh"],
            "direct": options["direct"],
        }
        if options["list_only"]:
            self._list(options["doc_types"] or DocumentType.values)
            return
        if options["run_async"]:
            task = ingest_wiki.delay(**kwargs)
            self.stdout.write(f"Queued ingest task {task.id}")
            return

        try:
            result = ingest(**kwargs)
        except WikiBlockedError as exc:
            raise CommandError(
                f"{exc}\nPages saved so far are kept; rerunning later continues where it stopped."
            ) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Patch {result.patch}: {result.created} created, {result.updated} updated, "
                f"{result.unchanged} unchanged, {len(result.failed)} failed"
            )
        )
        for title in result.failed:
            self.stdout.write(self.style.WARNING(f"  failed: {title}"))

    def _list(self, doc_types: list[str]) -> None:
        from wiki.client import WikiClient
        from wiki.models import Source

        client = WikiClient.from_settings()
        saved = set(Source.objects.values_list("page_title", flat=True))
        for doc_type in doc_types:
            titles = client.list_titles(doc_type)
            new = [t for t in titles if t not in saved]
            self.stdout.write(f"{doc_type}: {len(titles)} pages, {len(new)} not saved yet")
            for title in new[:15]:
                self.stdout.write(f"  + {title}")
            if len(new) > 15:
                self.stdout.write(f"  ... and {len(new) - 15} more")
