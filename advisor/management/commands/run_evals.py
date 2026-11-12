import argparse
import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from advisor.evalhistory import HISTORY, append, config_from_meta, entry
from advisor.evaluation import CaseResult, load_cases, render_markdown, run, update_readme
from advisor.llm import get_provider
from advisor.pob import get_pool
from wiki.models import Chunk, Document

DEFAULT_QUESTIONS = Path(settings.BASE_DIR) / "evals" / "questions.yaml"
DEFAULT_OUTPUT = Path(settings.BASE_DIR) / "evals" / "results" / "latest"


class Command(BaseCommand):
    help = "Evaluate retrieval (and with --answers, the LLM's answers) on evals/questions.yaml."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
        parser.add_argument("-k", type=int, default=settings.SEARCH_TOP_K, help="Chunks retrieved.")
        parser.add_argument(
            "--answers", action="store_true", help="Also generate and judge answers (uses the LLM)."
        )
        parser.add_argument(
            "--rewrite",
            action=argparse.BooleanOptionalAction,
            default=settings.SEARCH_QUERY_REWRITE,
            help="Rewrite questions into wiki terms with the LLM before searching.",
        )
        parser.add_argument(
            "--web",
            action="store_true",
            help="Also run the cases that need web search (results change from day to day).",
        )
        parser.add_argument("--only", nargs="*", default=[], help="Run only these case ids.")
        parser.add_argument("--category", action="append", help="Run only these categories.")
        parser.add_argument("--limit", type=int, help="Run at most this many cases.")
        parser.add_argument(
            "--output", type=Path, default=DEFAULT_OUTPUT, help="Writes <output>.json and .md."
        )
        parser.add_argument(
            "--update-readme", action="store_true", help="Put the scores into README.md."
        )
        parser.add_argument(
            "--record",
            metavar="LABEL",
            help="Add this run to evals/history.jsonl with a label (what changed).",
        )
        parser.add_argument(
            "--experiment",
            action="store_true",
            help="With --record: mark it as an experiment that wasn't kept.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        cases = load_cases(options["questions"])
        if options["only"]:
            cases = [c for c in cases if c.id in set(options["only"])]
        if options["category"]:
            cases = [c for c in cases if c.category in set(options["category"])]
        if options["limit"]:
            cases = cases[: options["limit"]]
        if not cases:
            raise CommandError("No eval cases selected.")
        if not Chunk.objects.exclude(embedding=None).exists():
            raise CommandError(
                "No embedded chunks. Run fetch_wiki (or load_eval_corpus) and build_index."
            )

        provider = get_provider() if options["answers"] or options["rewrite"] else None
        pob = options["answers"] and get_pool() is not None
        self.stdout.write(
            f"Running {len(cases)} cases (k={options['k']}, answers={options['answers']})"
        )

        report = run(
            cases,
            k=options["k"],
            answer_questions=options["answers"],
            provider=provider,
            pob_available=pob,
            progress=self._progress,
            rewrite=options["rewrite"],
            web=options["web"],
        )

        documents = Document.objects.count()
        patches = ", ".join(sorted(set(Document.objects.values_list("patch", flat=True)))) or "?"
        meta = (
            f"_{timezone.now():%Y-%m-%d}, patch {patches}, {documents} wiki pages, "
            f"{Chunk.objects.count()} chunks"
            + (", query rewriting" if options["rewrite"] else "")
            + (
                f", answers by {provider.name}/{provider.model}"
                if options["answers"] and provider
                else ", retrieval only"
            )
            + (f", {len(report.skipped)} PoB/web cases skipped" if report.skipped else "")
            + "._"
        )
        markdown = render_markdown(report, meta)

        output: Path = options["output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.with_suffix(".json").write_text(
            json.dumps({"meta": meta, **report.as_dict()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        output.with_suffix(".md").write_text(markdown + "\n", encoding="utf-8")

        self.stdout.write("\n" + markdown)
        if options["record"]:
            config = config_from_meta(meta)
            if settings.SEARCH_RERANK:
                config += f", reranker ({settings.SEARCH_RERANK_MODE})"
            summary = report.summary()
            row = entry(summary, options["record"], config, experiment=options["experiment"])
            append(row)
            self.stdout.write(self.style.SUCCESS(f"Recorded in {HISTORY.name}: {row['label']}"))
        if options["update_readme"]:
            if update_readme(Path(settings.BASE_DIR) / "README.md", markdown):
                self.stdout.write(self.style.SUCCESS("\nREADME.md updated."))
            else:
                raise CommandError(
                    "README.md has no <!-- evals:start --> / <!-- evals:end --> markers."
                )

    def _progress(self, result: CaseResult) -> None:
        mark = self.style.SUCCESS("pass") if result.passed else self.style.ERROR("FAIL")
        terms = f"  [{result.rewrite}]" if result.rewrite else ""
        self.stdout.write(f"  {mark}  {result.id}  ({result.seconds}s){terms}")
