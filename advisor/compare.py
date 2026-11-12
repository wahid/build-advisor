"""Compare two Path of Building builds: load both and diff their key stats.

The user's build (A) is the one the conversation is about; B is the one to
compare with. After the comparison A is loaded again, from its exported share
code, so follow-up tool calls work on A without fetching it again.
"""

from __future__ import annotations

from typing import Any

from .pob import PobToolbox, PobToolError, validate_build_source
from .progress import Progress, Steps, drain

# Key stats, in the order shown, with labels and whether higher is better.
STATS: list[tuple[str, str, bool]] = [
    ("CombinedDPS", "DPS (main skill, with ailments)", True),
    ("FullDPS", "Full DPS (all skills counted)", True),
    ("TotalEHP", "Effective HP", True),
    ("Life", "Life", True),
    ("EnergyShield", "Energy shield", True),
    ("PhysicalMaximumHitTaken", "Max physical hit", True),
    ("Armour", "Armour", True),
    ("Evasion", "Evasion", True),
    ("SpellSuppressionChance", "Spell suppression %", True),
    ("BlockChance", "Block %", True),
    ("FireResist", "Fire resistance", True),
    ("ColdResist", "Cold resistance", True),
    ("LightningResist", "Lightning resistance", True),
    ("ChaosResist", "Chaos resistance", True),
    ("Speed", "Attacks/casts per second", True),
    ("CritChance", "Crit chance %", True),
    ("EffectiveMovementSpeedMod", "Movement speed (x)", True),
]
SUMMARY_KEYS = ("className", "ascendancy", "level", "mainSkill")


def _summary(toolbox: PobToolbox) -> dict[str, Any]:
    data = toolbox.call_internal("get_build_summary", {}).data
    data = data if isinstance(data, dict) else {}
    return {key: data.get(key) for key in SUMMARY_KEYS}


def _stats(toolbox: PobToolbox) -> dict[str, float]:
    result = toolbox.call_internal("get_stats", {"keys": [key for key, _, _ in STATS]})
    if not result.ok or not isinstance(result.data, dict):
        raise PobToolError(f"Couldn't read stats: {result.text[:200]}")
    values = result.data.get("stats", result.data)
    return {k: float(v) for k, v in values.items() if isinstance(v, int | float)}


def _load(toolbox: PobToolbox, source: str) -> None:
    result = toolbox.call_internal("load_build", {"source": validate_build_source(source)})
    if not result.ok:
        raise PobToolError(result.text[:300])


def rows(stats_a: dict[str, float], stats_b: dict[str, float]) -> list[dict[str, Any]]:
    out = []
    for key, label, higher_is_better in STATS:
        a, b = stats_a.get(key), stats_b.get(key)
        if a is None or b is None or (a == 0 and b == 0):
            continue
        change = None if a == 0 else round((b - a) / abs(a) * 100, 1)
        out.append(
            {
                "stat": key,
                "label": label,
                "a": a,
                "b": b,
                "change_pct": change,
                "higher_is_better": higher_is_better,
            }
        )
    return out


def compare(toolbox: PobToolbox, build_a: str, build_b: str) -> dict[str, Any]:
    return drain(compare_steps(toolbox, build_a, build_b))


def compare_steps(toolbox: PobToolbox, build_a: str, build_b: str) -> Steps[dict[str, Any]]:
    """Diff B against A, the build currently loaded in `toolbox`; A is loaded again after."""
    yield Progress(0, 3, "reading your build")
    summary_a, stats_a = _summary(toolbox), _stats(toolbox)
    exported = toolbox.call_internal("export_build", {}).data
    code_a = exported.get("code") if isinstance(exported, dict) else None
    if not code_a:
        raise PobToolError("Couldn't keep your build while loading the other one.")
    yield Progress(1, 3, "loading the other build")
    _load(toolbox, build_b)
    summary_b, stats_b = _summary(toolbox), _stats(toolbox)
    yield Progress(2, 3, "loading your build again")
    _load(toolbox, code_a)
    toolbox.mark_loaded(build_a)  # it holds exactly A again
    return {"a": summary_a, "b": summary_b, "rows": rows(stats_a, stats_b)}
