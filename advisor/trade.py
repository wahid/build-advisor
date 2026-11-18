"""Trade links: searches on pathofexile.com/trade for a better item in a slot.

pob-mcp's trade_search asks Path of Building what every mod that can roll on the
slot's item type is worth to the loaded build, and builds a trade-site search that
ranks listings by that weighted value, with the current item as the minimum. Here
its result becomes a link the app shows (the model gets the mods and weights, not
the URL), optionally capped at a price.

Nothing is fetched from the trade site: the link is only opened by the user, in
their browser.
"""

from __future__ import annotations

import base64
import copy
import gzip
import json
from typing import Any
from urllib.parse import quote

TOOL_NAME = "trade_search"
TRADE_ROOT = "https://www.pathofexile.com/trade/search/"
CURRENCIES = ("chaos", "divine")
MAX_STATS = 6  # mods named to the model and the user, heaviest first
RARE_SEARCHES = 3  # slots that get a search with budget_upgrades
# What the model may set: the rest of pob-mcp's arguments (league, stat count,
# offline sellers) stay at their defaults.
ARGUMENTS = ("slot", "weights", "base", "better_than_current")
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
    """The trade site's compressed search link (the form Path of Building makes too)."""
    payload = json.dumps(query, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(gzip.compress(payload, mtime=0)).decode("ascii")
    return f"{TRADE_ROOT}{quote(league, safe='')}/{encoded}"


def search(data: Any, max_price: float | None = None, currency: str = "chaos") -> dict[str, Any]:
    """A trade_search result as the app shows it: the link and what it ranks by."""
    if not isinstance(data, dict):
        raise TradeError("The trade search came back empty.")
    url, league, query = data.get("url"), data.get("league"), data.get("query")
    if max_price and isinstance(query, dict) and isinstance(league, str) and league:
        query = copy.deepcopy(query)
        filters = query.setdefault("query", {}).setdefault("filters", {})
        filters["trade_filters"] = {
            "filters": {"price": {"max": round(max_price, 1), "option": currency}}
        }
        url = trade_url(league, query)
    else:
        max_price = None
    if not isinstance(url, str) or not url.startswith(TRADE_ROOT):
        raise TradeError("The trade search has no link to pathofexile.com.")
    weights = [s for s in data.get("statWeights") or [] if isinstance(s, dict) and s.get("text")]
    weights.sort(key=lambda s: -float(s.get("scoreAtExample") or 0))
    return {
        "slot": str(data.get("slot") or ""),
        "league": str(league or ""),
        "item": str(data.get("currentItem") or ""),
        "better_than_current": bool(data.get("minimumWeightedSum")),
        "max_price": max_price,
        "currency": currency if max_price else None,
        "stats": [str(s["text"]) for s in weights[:MAX_STATS]],
        "url": url,
    }


def for_model(found: dict[str, Any]) -> str:
    """What the model is told: everything but the link, which the app shows."""
    summary = {k: v for k, v in found.items() if k != "url" and v not in (None, "")}
    summary["note"] = (
        "The app shows the link to this search under your answer: don't write a URL. "
        "Listings are ranked by the mods in `stats` (most valuable first), weighted by "
        "what Path of Building says they add to this build."
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
