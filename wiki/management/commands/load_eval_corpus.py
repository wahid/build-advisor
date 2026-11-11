from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from wiki.corpus import load_corpus


class Command(BaseCommand):
    help = "Load evals/corpus.jsonl.gz into the database (then run build_index)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "path",
            nargs="?",
            type=Path,
            default=Path(settings.BASE_DIR) / "evals" / "corpus.jsonl.gz",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        count = load_corpus(options["path"])
        self.stdout.write(self.style.SUCCESS(f"Loaded {count} pages. Next: build_index."))
