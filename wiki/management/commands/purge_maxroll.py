from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from wiki.maxroll import purge


class Command(BaseCommand):
    help = (
        "Delete all stored Maxroll content: pages, documents, chunks and embeddings. "
        "The licence requires this within 60 days after it ends."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--yes", action="store_true", help="Don't ask for confirmation.")

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["yes"]:
            answer = input("Delete all Maxroll pages, chunks and embeddings? [y/N] ")
            if answer.strip().lower() != "y":
                self.stdout.write("Nothing deleted.")
                return
        deleted = purge()
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted} Maxroll rows (with their chunks).")
        )
