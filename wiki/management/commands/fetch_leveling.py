"""Download quest rewards, vendor gems and gem levels from the wiki (for leveling plans).

    fetch_leveling              download and store them (through the proxies, if any)
    fetch_leveling --direct     without the proxies
    fetch_leveling --export     also write wiki/fixtures/leveling.json.gz
    fetch_leveling --load       store the shipped file instead of downloading

refresh_wiki runs the download too.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from wiki import leveling
from wiki.client import WikiClient, WikiError, connection_note


class Command(BaseCommand):
    help = "Download quest rewards, vendor gems and gem levels from the wiki."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--direct", action="store_true", help="Skip the proxies.")
        parser.add_argument("--export", action="store_true", help="Also write the fixture.")
        parser.add_argument("--load", action="store_true", help="Store the shipped fixture.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["load"]:
            rewards, gems = leveling.store(leveling.load())
        else:
            self.stdout.write(connection_note(options["direct"]))
            try:
                rewards, gems = leveling.update(WikiClient.from_settings(direct=options["direct"]))
            except (WikiError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Stored {rewards} quest/vendor rows, {gems} gems"))
        if options["export"]:
            leveling.export()
            self.stdout.write(f"Wrote {leveling.FIXTURE}")
