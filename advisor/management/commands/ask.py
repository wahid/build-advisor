from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from advisor.rag import answer_stream
from wiki.models import DocumentType
from wiki.search import SearchFilters


class Command(BaseCommand):
    help = "Ask a build question and stream the answer with its sources."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("question")
        parser.add_argument(
            "--type", dest="doc_types", action="append", choices=DocumentType.values
        )
        parser.add_argument("--build", default="", help="PoB share code or pobb.in link.")
        parser.add_argument("--no-tools", action="store_true", help="Wiki only, no PoB.")

    def handle(self, *args: Any, **options: Any) -> None:
        filters = SearchFilters(doc_types=tuple(options["doc_types"] or ()))
        sources: list[dict[str, Any]] = []
        export = ""
        events = answer_stream(
            options["question"],
            filters=filters,
            build=options["build"],
            use_tools=not options["no_tools"],
        )
        for event in events:
            match event["type"]:
                case "sources":
                    sources = event["sources"]
                case "delta":
                    self.stdout.write(event["text"], ending="")
                    self.stdout.flush()
                case "tool_call":
                    args = ", ".join(f"{k}={v!r}" for k, v in event["arguments"].items())
                    self.stderr.write(self.style.NOTICE(f"\n  [PoB] {event['name']}({args[:120]})"))
                case "tool_result" if not event["ok"]:
                    self.stderr.write(self.style.WARNING(f"  [PoB] failed: {event['error'][:200]}"))
                case "pob_export":
                    export = event["code"]
                case "error":
                    self.stderr.write(self.style.ERROR(f"\n{event['message']}"))
                    return
                case "done":
                    self.stdout.write("\n")
                    self._print_sources(sources, set(event["cited"]), event["patch"])
                    if export:
                        self.stdout.write(self.style.MIGRATE_HEADING("\nPath of Building code:"))
                        self.stdout.write(export)

    def _print_sources(self, sources: list[dict[str, Any]], cited: set[int], patch: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nSources (patch {patch or '?'}):"))
        for source in sources:
            mark = "*" if source["number"] in cited else " "
            section = f" > {source['section']}" if source["section"] else ""
            self.stdout.write(
                f" {mark}[{source['number']}] {source['title']}{section}  {source['url']}"
            )
        self.stdout.write("   (* = cited in the answer)")
