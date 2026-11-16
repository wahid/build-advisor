"""Save the game facts the fact check uses, from Path of Building.

    build_gamefacts     write advisor/data/gamefacts.json.gz (weapon bases, gem tags)

Run it after updating Path of Building; the file ships with the app.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from advisor.gamefacts import DATA, ONE_HANDED_TYPES, TWO_HANDED_TYPES
from advisor.pob import get_pool


class Command(BaseCommand):
    help = "Write weapon bases and gem tags from Path of Building to the fact-check data file."

    def handle(self, *args: Any, **options: Any) -> None:
        pool = get_pool()
        if pool is None:
            raise CommandError("Path of Building isn't available (POB_PATH).")
        with pool.toolbox() as toolbox:
            bases = toolbox.call_internal("search_item_bases", {"query": "", "limit": 5000}).data
            gems = toolbox.call_internal(
                "search_gems", {"query": "", "limit": 5000, "include_vaal": True}
            ).data
        weapon_types = ONE_HANDED_TYPES | TWO_HANDED_TYPES
        facts = {
            "weapons": {
                b["name"]: b["type"]
                for b in bases.get("bases", [])
                if b.get("type") in weapon_types
            },
            "gems": {
                g["name"]: {"tags": g.get("tags", ""), "support": bool(g.get("support"))}
                for g in gems.get("gems", [])
            },
        }
        if not facts["weapons"] or not facts["gems"]:
            raise CommandError("Path of Building returned no bases or gems; nothing written.")
        DATA.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(DATA, "wt", encoding="utf-8") as handle:
            json.dump(facts, handle, ensure_ascii=False, sort_keys=True)
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(facts['weapons'])} weapon bases and {len(facts['gems'])} gems"
            )
        )
