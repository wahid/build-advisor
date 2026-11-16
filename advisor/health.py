"""A health check for a loaded build: the usual problems, as a checklist.

Everything comes from Path of Building (stats, its own warnings, the gear and
its configuration audit); no model is involved, so the list is the same every
time. Each check is "bad" (fix this), "warn" (worth a look) or "ok". The
thresholds for life are rules of thumb and say so.
"""

from __future__ import annotations

from typing import Any

from .pob import PobToolError
from .progress import Progress, Steps, drain

TOOL_NAME = "health_check"
RESIST_CAP = 75
ELEMENTS = (("FireResist", "Fire"), ("ColdResist", "Cold"), ("LightningResist", "Lightning"))
GEAR_SLOTS = (
    "Weapon 1",
    "Helmet",
    "Body Armour",
    "Gloves",
    "Boots",
    "Amulet",
    "Ring 1",
    "Ring 2",
    "Belt",
)
FLASK_SLOTS = tuple(f"Flask {n}" for n in range(1, 6))
STATS = (
    "Life",
    "EnergyShield",
    "ChaosResist",
    "AccuracyHitChance",
    "FreezeAvoidChance",
    "StunAvoidChance",
    "TotalEHP",
    *(key for key, _ in ELEMENTS),
)
CONFIG_SWING = 15.0  # % of DPS or EHP that depends on one assumption

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Check the loaded build for the usual problems, from Path of Building: resistances "
            "under the cap, chaos resistance, unmet attribute or level requirements, unspent "
            "passive or ascendancy points, a small life pool, empty gear and flask slots, low "
            "hit chance, no freeze or stun protection, and numbers that lean on configuration "
            "assumptions. Use it for 'check my build', 'what's wrong with my build' or 'why do "
            "I keep dying'. The app shows the checklist; explain the bad and warn items and "
            "how to fix them, most important first."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def _data(call: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = call(name, arguments)
    if not result.ok or not isinstance(result.data, dict):
        raise PobToolError(f"{name} failed: {result.text[:300]}")
    return result.data


def _check(check_id: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "label": label, "status": status, "detail": detail}


def _number(stats: dict[str, Any], key: str) -> float | None:
    value = stats.get(key)
    return float(value) if isinstance(value, int | float) else None


def _resistances(stats: dict[str, Any]) -> list[dict[str, str]]:
    low = [
        f"{name} {value:.0f}%"
        for key, name in ELEMENTS
        if (value := _number(stats, key)) is not None and value < RESIST_CAP
    ]
    known = [key for key, _ in ELEMENTS if _number(stats, key) is not None]
    checks = []
    if known:
        checks.append(
            _check(
                "resistances",
                "Elemental resistances",
                "bad" if low else "ok",
                f"Under the {RESIST_CAP}% cap: {', '.join(low)}." if low else "All capped.",
            )
        )
    chaos = _number(stats, "ChaosResist")
    if chaos is not None:
        status = "bad" if chaos < 0 else "warn" if chaos < 40 else "ok"
        checks.append(_check("chaos", "Chaos resistance", status, f"{chaos:.0f}%."))
    return checks


def _pool(stats: dict[str, Any], level: int) -> list[dict[str, str]]:
    life, shield = _number(stats, "Life"), _number(stats, "EnergyShield") or 0.0
    if life is None:
        return []
    pool = life + shield
    # Rule of thumb for mapping: about 4,500 at level 90, scaled down for lower levels.
    comfortable = 4500 * min(level, 90) / 90
    status = "bad" if pool < comfortable * 0.7 else "warn" if pool < comfortable else "ok"
    detail = f"{pool:,.0f} life and energy shield at level {level}"
    if status != "ok":
        detail += f"; a rule of thumb at this level is {comfortable:,.0f} or more"
    return [_check("pool", "Life pool", status, detail + ".")]


def _points(summary: dict[str, Any]) -> list[dict[str, str]]:
    passive = int(summary.get("passivePointsRemaining") or 0)
    available = int(summary.get("ascendancyPointsAvailable") or 0)
    ascendancy = available - int(summary.get("ascendancyPointsUsed") or 0)
    parts = []
    if passive > 0:
        parts.append(f"{passive} passive")
    if ascendancy > 0:
        parts.append(f"{ascendancy} ascendancy")
    detail = f"Unspent: {' and '.join(parts)} points." if parts else "All spent."
    return [_check("points", "Passive points", "bad" if parts else "ok", detail)]


def _requirements(warnings: list[dict[str, Any]]) -> list[dict[str, str]]:
    unmet = [
        str(w.get("message", ""))
        for w in warnings
        if w.get("kind") == "requirement" or "requirement" in str(w.get("message", "")).lower()
    ]
    # PoB says the same thing twice (its own line and a summary); keep the summaries.
    summaries = [m for m in unmet if "need" in m] or unmet
    detail = "; ".join(summaries[:4]) + "." if summaries else "All met."
    return [_check("requirements", "Requirements", "bad" if summaries else "ok", detail)]


def _gear(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    filled = {str(i.get("slot", "")) for i in items if isinstance(i, dict)}
    # Weapon 2 isn't checked: an empty off-hand is normal with two-handed weapons.
    empty = [slot for slot in GEAR_SLOTS if slot not in filled]
    flasks = [slot for slot in FLASK_SLOTS if slot not in filled]
    checks = [
        _check(
            "gear",
            "Gear slots",
            "bad" if empty else "ok",
            f"Empty: {', '.join(empty)}." if empty else "All filled.",
        ),
        _check(
            "flasks",
            "Flasks",
            "warn" if flasks else "ok",
            f"{len(flasks)} of 5 flask slots are empty." if flasks else "All five slots used.",
        ),
    ]
    return checks


def _protection(stats: dict[str, Any]) -> list[dict[str, str]]:
    checks = []
    hit = _number(stats, "AccuracyHitChance")
    if hit is not None and hit < 100:
        status = "bad" if hit < 85 else "warn" if hit < 95 else "ok"
        checks.append(_check("accuracy", "Chance to hit", status, f"{hit:.0f}%."))
    for key, label in (("FreezeAvoidChance", "Freeze"), ("StunAvoidChance", "Stun")):
        value = _number(stats, key)
        if value is None:
            continue
        status = "ok" if value >= 100 else "warn"
        detail = "Immune." if value >= 100 else f"{value:.0f}% chance to avoid: not immune."
        checks.append(_check(key, f"{label} protection", status, detail))
    return checks


def _assumptions(audit: dict[str, Any]) -> list[dict[str, str]]:
    leaning = []
    for condition in audit.get("conditions", []):
        changes = condition.get("changes", {}) if isinstance(condition, dict) else {}
        swings = [
            (abs(c["pct"]), stat, c["pct"])
            for stat, c in changes.items()
            if stat in ("FullDPS", "CombinedDPS", "TotalEHP")
            and isinstance(c.get("pct"), int | float)
        ]
        if swings and max(swings)[0] >= CONFIG_SWING:
            _, stat, pct = max(swings)
            what = "DPS" if "DPS" in stat else "effective HP"
            leaning.append(f"{condition.get('label', '?')} ({pct:+.0f}% {what} without it)")
    if not leaning:
        return []
    detail = "The numbers assume: " + "; ".join(leaning[:3]) + ". Make sure that's how you play."
    return [_check("assumptions", "Configuration assumptions", "warn", detail)]


def check_steps(call: Any) -> Steps[dict[str, Any]]:
    """Run the checks on the loaded build; `call` runs a pob-mcp tool (call_internal)."""
    yield Progress(0, 4, "stats")
    summary = _data(call, "get_build_summary", {})
    raw = _data(call, "get_stats", {"keys": list(STATS)})
    stats = raw.get("stats", raw)
    yield Progress(1, 4, "requirements")
    warnings = _data(call, "get_warnings", {}).get("warnings", [])
    yield Progress(2, 4, "gear")
    items = _data(call, "get_items", {}).get("items", [])
    yield Progress(3, 4, "configuration")
    audit = call("audit_config", {})
    level = int(summary.get("level") or 1)
    checks = [
        *_resistances(stats),
        *_pool(stats, level),
        *_requirements(warnings),
        *_points(summary),
        *_gear(items),
        *_protection(stats),
        *(_assumptions(audit.data) if audit.ok and isinstance(audit.data, dict) else []),
    ]
    order = {"bad": 0, "warn": 1, "ok": 2}
    checks.sort(key=lambda c: order[c["status"]])
    return {
        "checks": checks,
        "bad": sum(c["status"] == "bad" for c in checks),
        "warn": sum(c["status"] == "warn" for c in checks),
        "ok": sum(c["status"] == "ok" for c in checks),
        "note": "From Path of Building. The life threshold is a rule of thumb, not a rule.",
    }


def check(call: Any) -> dict[str, Any]:
    return drain(check_steps(call))
