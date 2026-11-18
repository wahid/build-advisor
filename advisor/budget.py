"""Upgrades within a budget: which unique items are affordable and help the build.

For each armour and jewellery slot, every unique that poe.ninja lists at or under
the budget (pob-mcp's price_check, the public economy prices) is equipped on the
loaded build in Path of Building and scored on damage and toughness. The build is
left as it was (compare_changes restores it). Rares aren't priced by poe.ninja, so
they get trade-site searches instead (advisor.trade): for the slots where one better
mod gains the most, a link to listings better than the current item, at most the
budget.
"""

from __future__ import annotations

import time
from typing import Any

from . import trade
from .items import DPS_STATS
from .pob import PobToolError
from .progress import Progress, Steps, drain

TOOL_NAME = "budget_upgrades"
SLOTS: dict[str, tuple[str, ...]] = {
    "Helmet": ("Helmet",),
    "Body Armour": ("Body Armour",),
    "Gloves": ("Gloves",),
    "Boots": ("Boots",),
    "Belt": ("Belt",),
    "Amulet": ("Amulet",),
    "Ring": ("Ring 1", "Ring 2"),
}
WEIGHTS = {"balanced": (1.0, 1.0), "damage": (1.0, 0.25), "defence": (0.25, 1.0)}
RESISTS = ("FireResist", "ColdResist", "LightningResist", "ChaosResist")
TIME_BUDGET = 45.0  # seconds (about 200 items); what wasn't tried is reported
MIN_LISTINGS = 3  # fewer: the price is one seller's wish
PRICE_BATCH = 100
MAX_ROWS = 10

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Find the best unique items the user can afford for the loaded build: every "
            "unique priced at or under the budget on poe.ninja (current league) is equipped "
            "in Path of Building and ranked by what it adds to damage and toughness. Use it "
            "for 'best upgrade for 50 chaos', 'what should I buy with 2 divines' and similar. "
            "Covers armour, belts, amulets and rings (not weapons). Rare items can't be "
            "priced, so it also gives trade-site searches for the rare slots where one "
            "better mod gains the most, capped at the budget: the app shows those links "
            "(matches are listed cheapest first). "
            "Prices are market snapshots: say so, and name the league."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "budget": {"type": "number", "description": "How much to spend on one item."},
                "currency": {
                    "type": "string",
                    "enum": ["chaos", "divine"],
                    "description": "The budget's currency (default chaos).",
                },
                "slots": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(SLOTS)},
                    "description": "Only these slots (default: all).",
                },
                "focus": {
                    "type": "string",
                    "enum": list(WEIGHTS),
                    "description": "What matters most: balanced (default), damage or defence.",
                },
            },
            "required": ["budget"],
        },
    },
}


class BudgetError(ValueError):
    pass


def _data(call: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = call(name, arguments)
    if not result.ok or not isinstance(result.data, dict):
        raise PobToolError(f"{name} failed: {result.text[:300]}")
    return result.data


def _pct(changes: dict[str, Any], stat: str) -> float:
    value = changes.get(stat, {}).get("pct")
    return float(value) if isinstance(value, int | float) else 0.0


def _prices(call: Any, names: list[str]) -> tuple[dict[str, dict[str, Any]], str, float]:
    """Cheapest listed price per name, the league, and chaos per divine."""
    best: dict[str, dict[str, Any]] = {}
    league, rate = "", 0.0
    for start in range(0, len(names), PRICE_BATCH):
        data = _data(call, "price_check", {"names": names[start : start + PRICE_BATCH]})
        league = league or str(data.get("league") or "")
        for row in data.get("prices", []):
            chaos, divine = row.get("chaos"), row.get("divine")
            if not isinstance(chaos, int | float) or row.get("links"):
                continue  # 6-link prices are for body armours with links; compare unlinked
            if isinstance(divine, int | float) and divine > 0.5:
                rate = rate or chaos / divine
            if (row.get("listings") or 0) < MIN_LISTINGS:
                continue
            if row["name"] not in best or chaos < best[row["name"]]["chaos"]:
                best[row["name"]] = row
    return best, league, rate


def find_steps(call: Any, summary: dict[str, Any], arguments: dict[str, Any]) -> Steps[dict]:
    """Rank affordable uniques for the loaded build; `call` runs a pob-mcp tool."""
    try:
        budget = float(arguments.get("budget") or 0)
    except (TypeError, ValueError):
        budget = 0.0
    if budget <= 0:
        raise BudgetError("Give a budget above zero.")
    currency = "divine" if arguments.get("currency") == "divine" else "chaos"
    focus = arguments.get("focus") if arguments.get("focus") in WEIGHTS else "balanced"
    slot_types = [s for s in arguments.get("slots") or [] if s in SLOTS] or list(SLOTS)
    level = int(summary.get("level") or 100)

    yield Progress(0, 1, "looking up prices")
    by_type: dict[str, list[str]] = {}
    for slot_type in slot_types:
        data = _data(
            call,
            "search_uniques",
            {"query": "", "item_type": slot_type, "include_mods": False, "limit": 500},
        )
        by_type[slot_type] = [
            u["name"]
            for u in data.get("uniques", [])
            if isinstance(u, dict) and u.get("name") and (u.get("levelReq") or 0) <= level
        ]
    names = list(dict.fromkeys(n for group in by_type.values() for n in group))
    prices, league, rate = _prices(call, names)
    if currency == "divine":
        if not rate:
            raise BudgetError(
                "Couldn't get the divine price from poe.ninja; give the budget in chaos."
            )
        budget_chaos = budget * rate
    else:
        budget_chaos = budget
    affordable = [
        (slot_type, name)
        for slot_type, group in by_type.items()
        for name in group
        if name in prices and prices[name]["chaos"] <= budget_chaos
    ]
    # Dearest first: with a time limit, the items most likely to matter get tried.
    affordable.sort(key=lambda pair: -prices[pair[1]]["chaos"])

    items = _data(call, "get_items", {}).get("items", [])
    equipped = {i.get("slot", ""): i.get("name", "") for i in items if isinstance(i, dict)}
    w_dps, w_ehp = WEIGHTS[focus]
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    untested = 0
    for done, (slot_type, name) in enumerate(affordable):
        yield Progress(done, len(affordable), name)
        if time.monotonic() - started > TIME_BUDGET:
            untested += 1
            continue
        best: dict[str, Any] | None = None
        for slot in SLOTS[slot_type]:
            if equipped.get(slot, "").startswith(f"{name},"):
                continue  # already wearing it there
            result = call(
                "compare_changes",
                {
                    "edits": [{"op": "equip_unique", "name": name, "slot": slot}],
                    "extra_stats": list(RESISTS),
                },
            )
            if not result.ok or not isinstance(result.data, dict):
                continue
            changes = result.data.get("changes", {})
            dps = next((_pct(changes, s) for s in DPS_STATS if s in changes), 0.0)
            ehp = _pct(changes, "TotalEHP")
            score = w_dps * dps + w_ehp * ehp
            if best is None or score > best["score"]:
                best = {
                    "name": name,
                    "slot": slot,
                    "replaces": equipped.get(slot, ""),
                    "chaos": prices[name]["chaos"],
                    "divine": prices[name].get("divine"),
                    "dps_pct": round(dps, 1),
                    "ehp_pct": round(ehp, 1),
                    "resists": {
                        r.removesuffix("Resist").lower(): changes[r]["change"]
                        for r in RESISTS
                        if isinstance(changes.get(r), dict) and changes[r].get("change")
                    },
                    "score": round(score, 2),
                }
        if best is not None and best["score"] > 0:
            rows.append(best)
    rows.sort(key=lambda r: -r["score"])
    yield Progress(len(affordable), len(affordable), "searches for rare items")
    rare_slots = [slot for slot_type in slot_types for slot in SLOTS[slot_type]]
    try:
        searches = trade.rare_searches(call, budget, currency, rare_slots)
    except PobToolError:
        searches = []
    return {
        "budget": budget,
        "currency": currency,
        "budget_chaos": round(budget_chaos, 1),
        "league": league,
        "focus": focus,
        "tried": len(affordable) - untested,
        "not_tried_time_limit": untested,
        "rows": rows[:MAX_ROWS],
        "rare_searches": searches,
        "note": (
            "Unique items only, at poe.ninja's cheapest listed price for the item (any roll; "
            "body armours unlinked), equipped with average rolls in Path of Building. Damage "
            "and toughness are % changes of DPS and TotalEHP; resists are points gained or "
            "lost: an item that drops a resistance below the cap needs that fixed elsewhere. "
            "rare_searches: trade-site searches for rare items with all the mods in "
            "`stats` (minimum rolls shown), instant buyout, at most the budget; the app "
            "shows their links, so name the slots and the mods, without a URL."
        ),
    }


def find(call: Any, summary: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    return drain(find_steps(call, summary, arguments))
