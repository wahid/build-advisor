import textwrap
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from wiki.models import DocumentType
from wiki.search import SearchFilters, hybrid_search


class Command(BaseCommand):
    help = "Show which chunks hybrid search retrieves for a question (no LLM involved)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("question")
        parser.add_argument("-k", "--top-k", type=int, default=8)
        parser.add_argument(
            "--type", dest="doc_types", action="append", choices=DocumentType.values
        )
        parser.add_argument("--patch", default="")
        parser.add_argument("--full", action="store_true", help="Print whole chunk texts.")

    def handle(self, *args: Any, **options: Any) -> None:
        filters = SearchFilters(doc_types=tuple(options["doc_types"] or ()), patch=options["patch"])
        hits = hybrid_search(options["question"], top_k=options["top_k"], filters=filters)
        if not hits:
            self.stdout.write("No results.")
            return

        for number, hit in enumerate(hits, start=1):
            chunk = hit.chunk
            ranks = ", ".join(f"{name} #{rank}" for name, rank in hit.ranks.items())
            section = f" > {chunk.section}" if chunk.section else ""
            self.stdout.write(
                self.style.SUCCESS(f"{number}. {hit.title}{section}")
                + f"  [{hit.score:.4f}; {ranks}; {chunk.doc_type}, {chunk.patch}]"
            )
            self.stdout.write(f"   {chunk.url}")
            body = chunk.text.split("\n\n", 1)[-1]
            if not options["full"]:
                body = textwrap.shorten(" ".join(body.split()), width=240, placeholder=" …")
            self.stdout.write(textwrap.indent(body, "   ") + "\n")
