"""Save the atlas passive tree the atlas_tree tool uses, from GGG's export.

    build_atlastree                          download the current tree from GitHub
    build_atlastree --source data.json       use a local copy of the export
    build_atlastree --tree-version 3.30.0c   set the version (default: from GitHub)

Writes advisor/data/atlastree.json.gz. Run it when a league changes the atlas
tree; the file ships with the app.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import requests
from django.core.management.base import BaseCommand, CommandError

from advisor.atlas import DATA, trim_export

EXPORT_URL = "https://raw.githubusercontent.com/grindinggear/atlastree-export/master/data.json"
COMMITS_URL = "https://api.github.com/repos/grindinggear/atlastree-export/commits/master"
TIMEOUT = 60


class Command(BaseCommand):
    help = "Write the atlas passive tree (nodes, links, mechanics) to the atlas tool's data file."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--source", default="", help="Path to a data.json from the export.")
        parser.add_argument("--tree-version", default="", help="Tree version, e.g. 3.30.0c.")

    def handle(self, *args: Any, **options: Any) -> None:
        source: str = options["source"]
        if source:
            export = json.loads(Path(source).read_text(encoding="utf-8"))
        else:
            response = requests.get(EXPORT_URL, timeout=TIMEOUT)
            response.raise_for_status()
            export = response.json()
        version: str = options["tree_version"] or self._latest_version()
        try:
            tree = trim_export(export, version)
        except (KeyError, TypeError, ValueError) as exc:
            raise CommandError(f"That doesn't look like the atlas tree export: {exc}") from exc
        DATA.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(DATA, "wt", encoding="utf-8") as handle:
            json.dump(tree, handle, ensure_ascii=False, sort_keys=True)
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(tree['nodes'])} atlas nodes and {len(tree['edges'])} links "
                f"(version {tree['version']})"
            )
        )

    @staticmethod
    def _latest_version() -> str:
        """The export's commit messages are the tree version ("3.30.0c")."""
        try:
            response = requests.get(COMMITS_URL, timeout=TIMEOUT)
            response.raise_for_status()
            message = str(response.json()["commit"]["message"]).strip()
        except (requests.RequestException, KeyError, ValueError):
            return "unknown"
        return message.splitlines()[0][:20] or "unknown"
