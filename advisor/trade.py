"""Trade links: searches on pathofexile.com/trade for a better item in a slot.

pob-mcp's trade_search asks Path of Building what every mod that can roll on the
slot's item type is worth to the loaded build. Here the most valuable of those
mods become a trade-site search with real minimum rolls: a rare item for the slot
with at least a few of them (a "Count" group), optionally capped at a price. The
app shows the link; the model gets the mods and minimums, not the URL.

pob-mcp's own query is one "Weighted Sum" group (a weight per mod). That is hard
to read and to adjust on the site, so only its item filters (category, rarity,
online sellers) are kept.

The link is the trade site's ?q=<query> form. The site lists matches cheapest
first and doesn't take a sort order from a link. The compressed link pob-mcp also
returns holds the query in a shape the site rejects ("search is no longer
valid"), so it isn't used.

Nothing is fetched from the trade site: the link is only opened by the user, in
their browser.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any
from urllib.parse import quote

TOOL_NAME = "trade_search"
TRADE_ROOT = "https://www.pathofexile.com/trade/search/"
CURRENCIES = ("chaos", "divine")
MAX_STATS = 5  # mods in the search, most valuable for the build first
NEED = 2  # how many of them an item must have
# The minimum asked of each mod, as a share of its best tier's lowest roll: a good
# roll, not only the top tier (which few listings have, fewer within a budget).
ROLL_SHARE = 0.7
_RANGE_RE = re.compile(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
RARE_SEARCHES = 3  # slots that get a search with budget_upgrades
# What the model may set: the rest of pob-mcp's arguments (league, stat count,
# offline sellers) stay at their defaults.
ARGUMENTS = ("slot", "weights", "base")
PRICE_PROPERTIES = {
    "max_price": {
        "type": "number",
        "description": "Only listings at or under this price (in `currency`).",
    },
    "currency": {
        "type": "string",
        "enum": list(CURRENCIES),
        "description": "The currency of max_price (default chaos).",
    },
}


class TradeError(ValueError):
    pass


def price_cap(arguments: dict[str, Any]) -> tuple[float | None, str]:
    """(max price or None, currency) from a tool call's arguments."""
    currency = arguments.get("currency")
    currency = currency if currency in CURRENCIES else "chaos"
    try:
        price = float(arguments.get("max_price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    return (price if price > 0 else None), currency


def trade_url(league: str, query: dict[str, Any]) -> str:
    """A link that opens the trade site with this search filled in and run."""
    payload = json.dumps(query, separators=(",", ":"))
    return f"{TRADE_ROOT}{quote(league, safe='')}?q={quote(payload, safe='')}"


def minimum_roll(text: str) -> float | None:
    """The minimum to ask for a mod, from its text ("+(351-480) to Accuracy Rating").

    A mod with two numbers ("Adds (6-9) to (13-15) ...") is searched by their average,
    as the trade site does.
    """
    lows = [float(low) for low, _high in _RANGE_RE.findall(text)]
    if not lows:
        lows = [float(n) for n in _NUMBER_RE.findall(text)]
    if not lows:
        return None
    value = sum(lows) / len(lows) * ROLL_SHARE
    return float(round(value)) if value >= 10 else round(value, 1)


def _label(text: str, minimum: float | None) -> str:
    """ "+# to Accuracy Rating: 246+" """
    generic = _RANGE_RE.sub("#", text)
    return generic if minimum is None else f"{generic}: {minimum:g}+"


def search(data: Any, max_price: float | None = None, currency: str = "chaos") -> dict[str, Any]:
    """A trade_search result as the app shows it: the link and the mods it asks for."""
    if not isinstance(data, dict):
        raise TradeError("The trade search came back empty.")
    league, query = data.get("league"), data.get("query")
    if not isinstance(query, dict) or not isinstance(query.get("query"), dict):
        raise TradeError("The trade search came back without a query.")
    if not isinstance(league, str) or not league:
        raise TradeError("The trade search came back without a league.")
    mods = [
        s
        for s in data.get("statWeights") or []
        if isinstance(s, dict) and s.get("text") and s.get("tradeId")
    ]
    if not mods:
        raise TradeError("No mod on this item type improves the build.")
    mods.sort(key=lambda s: -float(s.get("scoreAtExample") or 0))
    mods = mods[:MAX_STATS]
    minimums = [minimum_roll(str(s["text"])) for s in mods]
    need = min(NEED, len(mods))

    inner = copy.deepcopy(query["query"])
    inner["stats"] = [
        {
            "type": "count",
            "value": {"min": need},
            "filters": [
                {"id": str(s["tradeId"]), **({"value": {"min": low}} if low is not None else {})}
                for s, low in zip(mods, minimums, strict=True)
            ],
        }
    ]
    if max_price:
        inner.setdefault("filters", {})["trade_filters"] = {
            "filters": {"price": {"max": round(max_price, 1), "option": currency}}
        }
    return {
        "slot": str(data.get("slot") or ""),
        "league": league,
        "item": str(data.get("currentItem") or ""),
        "max_price": max_price,
        "currency": currency if max_price else None,
        "need": need,
        "stats": [_label(str(s["text"]), low) for s, low in zip(mods, minimums, strict=True)],
        "url": trade_url(league, {"query": inner}),
    }


def for_model(found: dict[str, Any]) -> str:
    """What the model is told: everything but the link, which the app shows."""
    summary = {k: v for k, v in found.items() if k != "url" and v not in (None, "")}
    summary["note"] = (
        "The app shows the link to this search under your answer: don't write a URL. "
        "The search finds rare items for the slot that have at least `need` of the mods "
        "in `stats`, each with the minimum roll shown (e.g. 246+). Those are the mods "
        "Path of Building values most for this build, most valuable first. The trade "
        "site lists the matches cheapest first, and the user can change every minimum "
        "there."
    )
    return json.dumps(summary, ensure_ascii=False)


def rare_searches(
    call: Any, max_price: float, currency: str, slots: list[str] | None = None
) -> list[dict[str, Any]]:
    """Searches for the rare slots where one better mod gains the most, capped at a price.

    `call` runs a pob-mcp tool. Slots it can't search are skipped.
    """
    arguments: dict[str, Any] = {"per_slot": 1}
    if slots:
        arguments["slots"] = slots
    ranked = call("rank_gear_upgrades", arguments)
    if not ranked.ok or not isinstance(ranked.data, dict):
        return []
    upgrades = [u for u in ranked.data.get("upgrades") or [] if isinstance(u, dict)]
    upgrades.sort(key=lambda u: -float(u.get("score") or 0))
    found: list[dict[str, Any]] = []
    for upgrade in upgrades:
        slot = str(upgrade.get("slot") or "")
        if not slot or any(f["slot"] == slot for f in found):
            continue
        result = call(TOOL_NAME, {"slot": slot})
        if not result.ok:
            continue
        try:
            entry = search(result.data, max_price, currency)
        except TradeError:
            continue
        entry["best_mod"] = str(upgrade.get("add") or "")
        found.append(entry)
        if len(found) == RARE_SEARCHES:
            break
    return found
