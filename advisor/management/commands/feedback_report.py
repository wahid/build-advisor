"""Report the answers that went wrong, grouped by the most likely cause.

    feedback_report                    the last 7 days, as Markdown
    feedback_report --days 30
    feedback_report --classify         also ask the model about unexplained thumbs-down
    feedback_report --output FILE      write it to a file instead

The server runs it weekly (deploy/server-setup.sh) into backups/feedback-report.md
on the host.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from advisor.feedbackreport import collect, render
from advisor.llm import get_provider


class Command(BaseCommand):
    help = "Report answers that went wrong (rated down, errors, flagged), grouped by cause."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument(
            "--classify",
            action="store_true",
            help="Ask the model to read thumbs-down answers that have no clear cause.",
        )
        parser.add_argument("--output", type=Path, help="Write the report to this file.")

    def handle(self, *args: Any, **options: Any) -> None:
        provider = get_provider() if options["classify"] else None
        text = render(collect(days=options["days"], provider=provider))
        if options["output"]:
            options["output"].parent.mkdir(parents=True, exist_ok=True)
            options["output"].write_text(text, encoding="utf-8")
            self.stdout.write(f"Wrote {options['output']}")
        else:
            self.stdout.write(text)
