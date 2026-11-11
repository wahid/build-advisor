from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from advisor.evaluation import load_cases
from wiki.corpus import select_documents, write_corpus

EVALS = Path(settings.BASE_DIR) / "evals"


class Command(BaseCommand):
    help = "Write the fixed wiki slice that CI evaluates against (evals/corpus.jsonl.gz)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--questions", type=Path, default=EVALS / "questions.yaml")
        parser.add_argument("--output", type=Path, default=EVALS / "corpus.jsonl.gz")
        parser.add_argument("--distractors", type=int, default=400, help="Random extra pages.")
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args: Any, **options: Any) -> None:
        expected = {t for case in load_cases(options["questions"]) for t in case.expected_sources}
        documents, missing, hard = select_documents(
            expected, options["distractors"], options["seed"]
        )
        write_corpus(documents, options["output"])

        size = options["output"].stat().st_size / 1024
        found = len(expected) - len(missing)
        self.stdout.write(
            f"Wrote {len(documents)} pages ({found}/{len(expected)} expected, "
            f"{hard} hard distractors) to {options['output']} ({size:.0f} KB)"
        )
        if missing:
            self.stdout.write(self.style.WARNING("Expected pages not in the database:"))
            for title in missing:
                self.stdout.write(f"  - {title}")
