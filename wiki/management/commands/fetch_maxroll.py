from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from wiki.maxroll import MaxrollError, fetch_guides


class Command(BaseCommand):
    help = (
        "Fetch Maxroll build guides (and tier lists, patch-notes summaries, mechanics "
        "articles) under licence LIC-2026-114. Run build_index afterwards."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("urls", nargs="*", help="maxroll.gg/poe/... page URLs.")
        parser.add_argument("--file", type=Path, help="Text file with one URL per line.")

    def handle(self, *args: Any, **options: Any) -> None:
        urls = list(options["urls"])
        if options["file"]:
            lines = options["file"].read_text(encoding="utf-8").splitlines()
            urls += [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        urls = list(dict.fromkeys(urls))
        if not urls:
            raise CommandError("Give one or more maxroll.gg URLs, or --file.")

        try:
            result = fetch_guides(urls)
        except (MaxrollError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Maxroll: {result.created} new, {result.updated} updated, "
                f"{result.unchanged} unchanged, {len(result.failed)} failed"
            )
        )
        for url in result.failed:
            self.stdout.write(f"  failed: {url}")
