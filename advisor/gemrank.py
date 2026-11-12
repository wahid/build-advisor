"""Rank skill gems by the damage Path of Building calculates for them.

"What's the strongest skill for a Slayer?" isn't in any wiki page: it takes a
calculation. This tool does it inside one Path of Building process, in one of
two modes:

- reference: a fresh level-90 character of the given ascendancy. Each skill
  gets a plain reference weapon it can use and nothing else (no tree, no gear,
  no supports unless given), so the skills are compared on their own scaling.
- build: the user's loaded build. Its main skill is swapped for each candidate
  with compare_changes, which puts the build back exactly as it was.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TOOL_NAME = "rank_skill_gems"
MAX_CANDIDATES = 150  # all attack skills fit
CALL_TIMEOUT = 60.0
TIME_BUDGET = 100.0  # seconds for one ranking; what is left out is reported
DPS_STAT = "CombinedDPS"  # hits plus damaging ailments, as PoB's sidebar shows
REFERENCE_LEVEL = 90

# A plain, high-level base per weapon type. A skill is measured with the first
# type in this order that it can use, so most melee skills share one weapon.
REFERENCE_WEAPONS: dict[str, str] = {
    "Two Handed Mace": "Coronal Maul",
    "Two Handed Axe": "Vaal Axe",
    "Two Handed Sword": "Reaver Sword",
    "Staff": "Eclipse Staff",
    "Bow": "Thicket Bow",
    "Claw": "Imperial Claw",
    "Dagger": "Ambusher",
    "One Handed Sword": "Jewelled Foil",
    "One Handed Mace": "Behemoth Mace",
    "One Handed Axe": "Runic Hatchet",
    "Sceptre": "Void Sceptre",
    "Wand": "Convoking Wand",
}
MELEE_DEFAULT = "Two Handed Mace"
# A well-rolled endgame weapon, the same on every base: a bare base would make
# skills with their own damage (damage over time, fixed base damage) look far
# better than skills that multiply weapon damage.
REFERENCE_WEAPON_MODS = [
    "170% increased Physical Damage",
    "Adds 35 to 70 Physical Damage",
    "20% increased Attack Speed",
    "30% increased Critical Strike Chance",
]
# Path of Building's default enemy is a pinnacle boss; also measure a map enemy.
MAP_ENEMY = {"op": "set_config", "var": "enemyIsBoss", "value": "None"}
# Words in a gem's "requires a Sword, Axe, Mace, Sceptre, Staff or Unarmed".
REQUIREMENT_WORDS = {
    "sword": ["Two Handed Sword", "One Handed Sword"],
    "axe": ["Two Handed Axe", "One Handed Axe"],
    "mace": ["Two Handed Mace", "One Handed Mace"],
    "sceptre": ["Sceptre"],
    "staff": ["Staff"],
    "claw": ["Claw"],
    "dagger": ["Dagger"],
    "bow": ["Bow"],
    "wand": ["Wand"],
}
REQUIRES_RE = re.compile(r"requires (?:an? )?([^.]+)", re.IGNORECASE)

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Calculate in Path of Building which skill gems deal the most damage, and rank "
            "them. Use it for 'strongest skill', 'best scaling skill gem' or 'which slam / "
            "bow skill is best' questions instead of guessing. Without a loaded build it "
            "uses a level-90 reference character of the given ascendancy with a plain "
            "reference weapon per skill (no tree, gear or supports), so it compares the "
            "skills' own scaling. With the user's build loaded it swaps their main skill "
            "for each candidate and reports their real DPS."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Gem tags all candidates must have, e.g. ['Slam'], "
                    "['Attack', 'Melee'], ['Bow'], ['Spell', 'Fire'].",
                },
                "query": {"type": "string", "description": "Optional text in the gem's name."},
                "ascendancy": {
                    "type": "string",
                    "description": "Reference mode: the ascendancy, e.g. 'Slayer'.",
                },
                "supports": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional support gems linked to every candidate.",
                },
                "use_loaded_build": {
                    "type": "boolean",
                    "description": "True (default when a build is loaded): rank by swapping the "
                    "loaded build's main skill. False: use the reference character.",
                },
                "limit": {"type": "integer", "description": "How many to return (default 10)."},
            },
            "required": ["tags"],
        },
    },
}


MAX_RESULTS = 25


def _limit(arguments: dict[str, Any]) -> int:
    try:
        return max(1, min(int(arguments.get("limit") or 10), MAX_RESULTS))
    except (TypeError, ValueError):
        return 10


def uses_build(arguments: dict[str, Any], build_loaded: bool) -> bool:
    return build_loaded and arguments.get("use_loaded_build", True) is not False


def pob_version() -> str:
    """The Path of Building checkout (the Docker image writes VERSION), or ""."""
    from django.conf import settings

    try:
        return (Path(settings.POB_PATH) / "VERSION").read_text(encoding="utf-8").strip()[:200]
    except OSError:
        return ""


def cache_key(arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """A key for a reference ranking: its arguments, the setup and the PoB version."""

    def names(values: Any) -> list[str]:
        return sorted({str(v).strip().lower() for v in values or [] if str(v).strip()})

    normalised = {
        "tags": names(arguments.get("tags")),
        "query": str(arguments.get("query") or "").strip().lower(),
        "ascendancy": str(arguments.get("ascendancy") or "").strip().lower(),
        "supports": names(arguments.get("supports")),
    }
    setup = {
        "level": REFERENCE_LEVEL,
        "weapons": REFERENCE_WEAPONS,
        "mods": REFERENCE_WEAPON_MODS,
        "dps": DPS_STAT,
        "pob": pob_version(),
    }
    raw = json.dumps({"arguments": normalised, "setup": setup}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest(), normalised


class GemRankError(RuntimeError):
    """The ranking couldn't run; the message is shown to the model."""


@dataclass
class Ranked:
    gem: str
    dps: float  # against PoB's default enemy (a pinnacle boss), or the build's own config
    average_hit: float | None
    attacks_per_second: float | None
    weapon: str  # reference weapon type, or "your build"
    tags: str
    map_dps: float | None = None  # against a normal map enemy (reference mode only)


def weapons_for(description: str, tags: str) -> list[str]:
    """Reference weapon types a skill can be used with, best guess first."""
    tag_set = {t.strip().lower() for t in tags.split(",")}
    match = REQUIRES_RE.search(description or "")
    if match:
        found: list[str] = []
        for word in re.findall(r"[a-z]+", match.group(1).lower()):
            for weapon in REQUIREMENT_WORDS.get(word.rstrip("s"), []):
                if weapon not in found:
                    found.append(weapon)
        if found:
            # Same weapon for as many skills as possible: the comparison is fairer.
            order = list(REFERENCE_WEAPONS)
            return sorted(found, key=order.index)
    if "bow" in tag_set:
        return ["Bow"]
    if "spell" in tag_set and "attack" not in tag_set:
        return []  # spells don't need a weapon
    return [MELEE_DEFAULT]


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _after(changes: dict[str, Any], stat: str, before: float | None) -> float | None:
    """A stat after the change; compare_changes leaves out stats that didn't move."""
    entry = changes.get(stat)
    if isinstance(entry, dict):
        return _number(entry.get("after"))
    return before


class GemRanker:
    """Runs a ranking with a raw Path of Building server (`call(name, args) -> result`)."""

    def __init__(self, call: Any) -> None:
        self._call = call
        self.untested = 0  # candidates skipped because the time budget ran out

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._call(name, arguments)
        if not result.ok:
            raise GemRankError(f"{name} failed: {result.text[:300]}")
        return result.data

    def candidates(self, tags: list[str], query: str) -> list[dict[str, Any]]:
        data = self.call(
            "search_gems",
            {"query": query, "tags": tags, "support": False, "limit": MAX_CANDIDATES},
        )
        gems = data.get("gems", []) if isinstance(data, dict) else []
        return [g for g in gems if isinstance(g, dict) and g.get("name")]

    def _measure(self, edits: list[dict[str, Any]], baseline: dict[str, float | None]) -> dict:
        data = self.call(
            "compare_changes",
            {"edits": edits, "extra_stats": [DPS_STAT, "AverageDamage", "Speed"]},
        )
        changes = data.get("changes", {}) if isinstance(data, dict) else {}
        return {stat: _after(changes, stat, before) for stat, before in baseline.items()}

    def rank_reference(
        self, gems: list[dict[str, Any]], ascendancy: str, supports: list[str]
    ) -> list[Ranked]:
        build_args: dict[str, Any] = {"level": REFERENCE_LEVEL}
        if ascendancy:
            build_args["ascendancy"] = ascendancy
        self.call("new_build", build_args)
        by_weapon: dict[str, list[dict[str, Any]]] = {}
        for gem in gems:
            weapons = weapons_for(str(gem.get("description", "")), str(gem.get("tags", "")))
            by_weapon.setdefault(weapons[0] if weapons else "", []).append(gem)

        started = time.monotonic()
        ranked: list[Ranked] = []
        for weapon, group in by_weapon.items():
            if weapon:
                base = REFERENCE_WEAPONS[weapon]
                edit = {
                    "op": "create_rare",
                    "slot": "Weapon 1",
                    "base": base,
                    "mods": REFERENCE_WEAPON_MODS,
                }
                self.call("apply_changes", {"edits": [edit]})
            baseline = {DPS_STAT: 0.0, "AverageDamage": None, "Speed": None}
            for gem in group:
                if time.monotonic() - started > TIME_BUDGET:
                    self.untested += 1
                    continue
                edits = [
                    {
                        "op": "create_socket_group",
                        "gems": [gem["name"], *supports],
                        "set_main": True,
                    }
                ]
                try:
                    stats = self._measure(edits, baseline)
                    mapping = self._measure([MAP_ENEMY, *edits], baseline)
                except GemRankError as exc:
                    logger.info("rank_skill_gems skipped %s: %s", gem["name"], exc)
                    continue
                dps = stats[DPS_STAT] or 0.0
                if dps > 0 or (mapping[DPS_STAT] or 0) > 0:
                    ranked.append(
                        Ranked(
                            gem["name"],
                            dps,
                            stats["AverageDamage"],
                            stats["Speed"],
                            weapon or "none (spell)",
                            str(gem.get("tags", "")),
                            map_dps=mapping[DPS_STAT],
                        )
                    )
        return ranked

    def rank_in_build(self, gems: list[dict[str, Any]]) -> tuple[list[Ranked], str]:
        skills = self.call("get_skills", {})
        groups = skills.get("groups", []) if isinstance(skills, dict) else []
        main = next((g for g in groups if g.get("isMain")), None)
        active = next((gem for gem in (main or {}).get("gems", []) if not gem.get("support")), None)
        if not main or not active:
            raise GemRankError("The loaded build has no main skill to swap.")
        stats = self.call("get_stats", {"keys": [DPS_STAT, "AverageDamage", "Speed"]})
        values = stats.get("stats", stats) if isinstance(stats, dict) else {}
        baseline = {
            DPS_STAT: _number(values.get(DPS_STAT)),
            "AverageDamage": _number(values.get("AverageDamage")),
            "Speed": _number(values.get("Speed")),
        }
        started = time.monotonic()
        ranked = [
            Ranked(
                active["name"],
                baseline[DPS_STAT] or 0.0,
                baseline["AverageDamage"],
                baseline["Speed"],
                "your build (current main skill)",
                "",
            )
        ]
        for gem in gems:
            if gem["name"] == active["name"]:
                continue
            if time.monotonic() - started > TIME_BUDGET:
                self.untested += 1
                continue
            edit = {
                "op": "replace_gem",
                "group": main["index"],
                "old_gem": active["name"],
                "new_gem": gem["name"],
            }
            try:
                after = self._measure([edit], baseline)
            except GemRankError as exc:
                logger.info("rank_skill_gems skipped %s: %s", gem["name"], exc)
                continue
            dps = after[DPS_STAT] or 0.0
            if dps > 0:
                ranked.append(
                    Ranked(
                        gem["name"],
                        dps,
                        after["AverageDamage"],
                        after["Speed"],
                        "your build",
                        str(gem.get("tags", "")),
                    )
                )
        return ranked, active["name"]

    def run(self, arguments: dict[str, Any], build_loaded: bool) -> dict[str, Any]:
        """Rank, using the cache for reference rankings (they never change per version)."""
        if (
            not any(str(t).strip() for t in arguments.get("tags") or [])
            and not str(arguments.get("query") or "").strip()
        ):
            raise GemRankError("Give at least one tag (e.g. ['Slam']) or a name query.")
        if uses_build(arguments, build_loaded):
            return self.compute(arguments, build_loaded=True)
        key, normalised = cache_key(arguments)
        from .models import GemRanking

        cached = GemRanking.objects.filter(key=key).first()
        if cached is not None:
            result = dict(cached.result)
            result["ranked"] = result["ranked"][: _limit(arguments)]
            result["cached"] = f"calculated {cached.created_at:%Y-%m-%d}"
            return result
        result = self.compute({**arguments, "limit": MAX_RESULTS}, build_loaded=False)
        if self.untested == 0:  # a ranking cut short by the time limit isn't kept
            GemRanking.objects.update_or_create(
                key=key,
                defaults={"arguments": normalised, "result": result, "pob_version": pob_version()},
            )
        result = dict(result)
        result["ranked"] = result["ranked"][: _limit(arguments)]
        return result

    def compute(self, arguments: dict[str, Any], build_loaded: bool) -> dict[str, Any]:
        tags = [str(t) for t in arguments.get("tags") or [] if str(t).strip()][:5]
        query = str(arguments.get("query") or "")[:60]
        if not tags and not query:
            raise GemRankError("Give at least one tag (e.g. ['Slam']) or a name query.")
        supports = [str(s) for s in arguments.get("supports") or []][:5]
        limit = _limit(arguments)
        in_build = uses_build(arguments, build_loaded)

        gems = self.candidates(tags, query)
        if not gems:
            raise GemRankError(f"No skill gems found with tags {tags} and query {query!r}.")
        started = time.monotonic()
        if in_build:
            ranked, current = self.rank_in_build(gems)
            method = (
                f"Swapped the loaded build's main skill ({current}) for each candidate, keeping "
                "its supports, gear and tree; the build was restored after each test."
            )
        else:
            ascendancy = str(arguments.get("ascendancy") or "")[:40]
            ranked = self.rank_reference(gems, ascendancy, supports)
            weapons = ", ".join(sorted({r.weapon for r in ranked}))
            method = (
                f"Reference character: level {REFERENCE_LEVEL} {ascendancy or 'character'}, no "
                "passive tree and no gear except one well-rolled weapon each skill can use "
                f"({weapons}; {', '.join(REFERENCE_WEAPON_MODS)}), gem level 20, "
                + (f"supports: {', '.join(supports)}. " if supports else "no supports. ")
                + "dps is against a pinnacle boss (PoB's default), map_dps against a normal map "
                "enemy. It compares the skills' own scaling, not finished builds; skills with "
                "several parts use Path of Building's default part."
            )
        ranked.sort(key=lambda r: r.dps, reverse=True)
        logger.info(
            "rank_skill_gems %s %r -> %d ranked in %.1fs",
            tags,
            query,
            len(ranked),
            time.monotonic() - started,
        )
        return {
            "method": method,
            "dps_stat": f"{DPS_STAT} (hits plus damaging ailments)",
            "candidates": len(gems),
            "ranked": [asdict(r) for r in ranked[:limit]],
            "not_dealing_damage_here": len(gems) - len(ranked) - self.untested,
            "not_tested_time_limit": self.untested,
            "note": "Gems without damage here are utility skills, or need a weapon or setup "
            "the reference character doesn't have.",
        }
