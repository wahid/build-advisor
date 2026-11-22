"""The best timeless jewel seed and socket for the loaded build (pob-mcp 0.5.3).

pob-mcp's find_timeless_jewel scans every seed of a timeless jewel in every jewel
socket near the tree, then has Path of Building calculate the best candidates.
Here it runs without its tree rebuild (rebuild=0): the rebuild re-optimises the
whole tree around the jewel and takes minutes, longer than a chat answer may
take. Without it, points the jewel needs beyond the current tree are charged at
the value of a typical point, and the model is told the gain is an estimate.

The trade links pob-mcp returns are the trade site's compressed form, which the
site rejects (see advisor.trade). They are turned into the ?q= form here, and the
app shows them: the model gets the seeds, not the links.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import json
import re
from typing import Any
from urllib.parse import quote, unquote

from .pob import PobToolError

TOOL_NAME = "find_timeless_jewel"
# The jewels pob-mcp supports, with the conquerors each can have.
JEWELS: dict[str, tuple[str, ...]] = {
    "Lethal Pride": ("Kaom", "Rakiata", "Akoya"),
    "Brutal Restraint": ("Asenath", "Nasima", "Balbala"),
    "Militant Faith": ("Avarius", "Dominus", "Maxarius"),
    "Elegant Hubris": ("Cadiro", "Victario", "Caspiro"),
    "Heroic Tragedy": ("Vorana", "Uhtred", "Medved"),
}
MODES = ("balanced", "dps", "defence")
MAX_PATH = 8  # points from the tree a socket may be
# How many points away an unallocated notable in radius may be and still count when a
# seed makes it worth taking: further when the build already has a timeless jewel, so
# the search looks for seeds with good transformed notables around it, not only on it.
MAX_PICK = 8
PICK = 3
PICK_WITH_JEWEL = 5
MAX_SECONDS = 60  # pob-mcp's own limit; a chat tool call may take 90
ALTERNATIVES = 4
TRADE_ROOT = "https://www.pathofexile.com/trade/search/"
_COMPRESSED_RE = re.compile(r"/trade/search/(?P<league>[^/?#]+)/(?P<code>[A-Za-z0-9_\-=]+)$")

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Find the best seed and socket for a timeless jewel on the loaded build. Every "
            "seed is tried in every jewel socket that is allocated or close to the tree, the "
            "best are calculated in Path of Building, and you get the seed, the socket, the "
            "notables it creates and what it changes in damage and toughness. Use it for "
            "'which Lethal Pride should I buy', 'is Elegant Hubris worth it' and similar. "
            "Conquerors: "
            + "; ".join(f"{jewel}: {', '.join(names)}" for jewel, names in JEWELS.items())
            + ". The conqueror only decides what a keystone in radius becomes, so the app "
            "also shows a trade search for the same seed with any conqueror (often cheaper). "
            "With a timeless jewel already socketed, jewel and conqueror default to it, its "
            "socket is searched too, and every result is compared with it: better seeds or "
            "sockets, or a verdict to keep it. "
            "Glorious Vanity isn't supported. The gain is on the current tree, with extra "
            "points the jewel needs charged at a typical point's value: an estimate, not a "
            "rebuilt tree. The app shows the trade links."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "jewel": {
                    "type": "string",
                    "enum": list(JEWELS),
                    "description": "Default: the timeless jewel the build has socketed.",
                },
                "conqueror": {
                    "type": "string",
                    "description": "The jewel's conqueror. Default: the socketed jewel's.",
                },
                "mode": {
                    "type": "string",
                    "enum": list(MODES),
                    "description": "What to score: balanced (default), dps or defence.",
                },
                "max_path": {
                    "type": "integer",
                    "description": (
                        f"Sockets up to this many points from the tree (0-{MAX_PATH}, default 8)."
                    ),
                },
                "max_pick": {
                    "type": "integer",
                    "description": (
                        "Also count unallocated notables in radius up to this many points away "
                        f"that a seed makes worth taking (0-{MAX_PICK}; default {PICK}, "
                        f"{PICK_WITH_JEWEL} when a timeless jewel is socketed)."
                    ),
                },
                "apply": {
                    "type": "boolean",
                    "description": (
                        "Put the best result in the build (default false). Only when the user "
                        "asks for it; the app then exports the changed build."
                    ),
                },
            },
        },
    },
}


class TimelessError(ValueError):
    """Arguments pob-mcp would reject, explained for the model."""


def arguments_for_pob(
    arguments: dict[str, Any], current: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The model's arguments -> pob-mcp's, with the run kept within a chat answer.

    current: the timeless jewel the build has socketed (socketed()), the default."""
    asked = str(arguments.get("jewel") or "")
    if not asked and current:
        asked = current["jewel"]
    jewel = _match(asked, JEWELS)
    if jewel is None and not asked:
        raise TimelessError(
            "The build has no timeless jewel socketed: say which jewel to search "
            f"({', '.join(JEWELS)})."
        )
    if jewel is None:
        raise TimelessError(
            f"Unknown timeless jewel {arguments.get('jewel')!r}; one of: {', '.join(JEWELS)}. "
            "Glorious Vanity isn't supported."
        )
    asked_conqueror = str(arguments.get("conqueror") or "")
    if not asked_conqueror and current and current["jewel"] == jewel:
        asked_conqueror = current.get("conqueror") or ""
    conqueror = _match(asked_conqueror, JEWELS[jewel])
    if conqueror is None:
        raise TimelessError(
            f"{jewel}'s conqueror is one of: {', '.join(JEWELS[jewel])} "
            f"(not {arguments.get('conqueror')!r})."
        )
    mode = str(arguments.get("mode") or "balanced").lower()
    try:
        max_path = int(arguments.get("max_path", MAX_PATH))
    except (TypeError, ValueError):
        max_path = MAX_PATH
    try:
        max_pick = int(arguments.get("max_pick", PICK_WITH_JEWEL if current else PICK))
    except (TypeError, ValueError):
        max_pick = PICK
    return {
        "jewel": jewel,
        "conqueror": conqueror,
        "mode": mode if mode in MODES else "balanced",
        "max_path": max(0, min(max_path, MAX_PATH)),
        "max_pick": max(0, min(max_pick, MAX_PICK)),
        "apply": arguments.get("apply") is True,
        "rebuild": 0,
        "max_seconds": MAX_SECONDS,
        "jobs": 1,
    }


def socketed(items: Any) -> dict[str, Any] | None:
    """The timeless jewel in the build's items (pob-mcp get_items), if any:
    {"jewel", "seed", "conqueror", "socket"}. Glorious Vanity counts too (it is
    replaced by a supported jewel), with no default search."""
    rows = items.get("items") if isinstance(items, dict) else items
    for item in rows or []:
        if not isinstance(item, dict) or item.get("base") != "Timeless Jewel":
            continue
        name = str(item.get("name") or "").split(",")[0].strip()
        conquerors = JEWELS.get(name, ())
        seed = conqueror = None
        for line in str(item.get("raw") or "").splitlines():
            number = re.search(r"\b(\d+)\b", line)
            who = next((c for c in conquerors if c in line), None)
            if (
                number
                and (who or not conquerors)
                and not line.startswith(("Limited to", "Implicits", "Item Level"))
            ):
                seed, conqueror = int(number.group(1)), who
                break
        socket = re.search(r"(\d+)$", str(item.get("slot") or ""))
        return {
            "jewel": name,
            "seed": seed,
            "conqueror": conqueror,
            "socket": int(socket.group(1)) if socket else None,
        }
    return None


def _match(value: str, names: Any) -> str | None:
    wanted = value.strip().lower()
    return next((name for name in names if name.lower() == wanted), None)


def plain_trade_link(url: str) -> str:
    """pob-mcp's compressed trade link -> the ?q= link the trade site takes ('' if unreadable)."""
    match = _COMPRESSED_RE.search(url or "")
    if not match:
        return ""
    code = match.group("code").replace("-", "+").replace("_", "/")
    try:
        query = json.loads(gzip.decompress(base64.b64decode(code + "=" * (-len(code) % 4))))
    except (binascii.Error, OSError, ValueError):
        return ""
    league = quote(unquote(match.group("league")), safe="")
    payload = json.dumps(query, separators=(",", ":"))
    return f"{TRADE_ROOT}{league}?q={quote(payload, safe='')}"


def _text(value: Any) -> str | None:
    """What a seed makes of a notable: pob-mcp gives a name or a list of mods."""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value if v) or None
    return str(value) if value else None


def _row(result: dict[str, Any]) -> dict[str, Any]:
    """One seed and socket, as the app shows it and the model reads it."""
    notables = [
        {
            "node": n.get("node"),
            "becomes": _text(n.get("becomes") or n.get("adds")),
            "allocated": bool(n.get("allocated")),
            "points_to_reach": n.get("pointsToReach"),
            "value_pct": n.get("valuePct"),
        }
        for n in result.get("notables") or []
    ]
    row = {
        "seed": result.get("seed"),
        "socket": result.get("socket"),
        "socket_near": result.get("socketNear"),
        "socket_allocated": bool(result.get("socketAllocated")),
        "socket_path_cost": result.get("socketPathCost"),
        "extra_points": result.get("extraPoints"),
        "score_gain_pct": result.get("scoreGainPct"),
        "change_pct": result.get("changePct") or {},
        "notables": notables,
        "pick_up": result.get("pickUp") or [],
        "trade_url": plain_trade_link(str(result.get("trade") or "")),
        "trade_any_url": plain_trade_link(str(result.get("tradeAnyConqueror") or "")),
    }
    if (result.get("seedsTiedWithBest") or 0) > 1:
        # pob-mcp 0.5.4: this many seeds give the socket the same result; any will do.
        row["seeds_tied"] = result["seedsTiedWithBest"]
    for key, name in (
        ("breaks", "breaks"),
        ("keystonesInRadius", "keystones_in_radius"),
        ("note", "note"),
    ):
        if result.get(key):
            row[name] = result[key]
    return row


def summarise(raw: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    """pob-mcp's result -> what the app shows (links included).

    current: the socketed timeless jewel (socketed()); results in its socket say so."""
    best = raw.get("best")
    if current is None and isinstance(raw.get("currentTimeless"), dict):
        found = raw["currentTimeless"]
        current = {
            "jewel": found.get("name"),
            "seed": found.get("seed"),
            "conqueror": found.get("conqueror"),
            "socket": found.get("socket"),
        }
    rows = [_row(best)] if isinstance(best, dict) else []
    rows += [_row(r) for r in (raw.get("alternatives") or [])[:ALTERNATIVES]]
    for row in rows:
        row["replaces_current"] = bool(current) and row.get("socket") == current.get("socket")
    return {
        "jewel": raw.get("jewel"),
        "conqueror": raw.get("conqueror"),
        "mode": raw.get("mode"),
        "verdict": raw.get("verdict") or "",
        "current": current,
        "best": rows[0] if isinstance(best, dict) else None,
        "alternatives": rows[1:] if isinstance(best, dict) else rows,
        "applied": raw.get("applied"),
        "sockets_scanned": raw.get("socketsScanned"),
        "seeds_per_socket": raw.get("seedsPerSocket"),
        "point_value_pct": raw.get("pointValuePct"),
        "top_seeds_url": plain_trade_link(str(raw.get("tradeTopSeeds") or "")),
        "seconds": raw.get("seconds"),
        "note": (
            "score_gain_pct is on the current tree: extra points the jewel needs are charged "
            "at point_value_pct each (a typical point). The tree isn't rebuilt around the "
            "jewel here, so call it an estimate."
            + (
                " The build already has a timeless jewel (current): every result is compared "
                "with the build as it is, jewel included, and one in the same socket "
                "(replaces_current) is a straight swap."
                if current
                else ""
            )
            + (
                " Militant Faith's devotion mods are random and not scored."
                if raw.get("jewel") == "Militant Faith"
                else ""
            )
        ),
    }


def for_model(result: dict[str, Any]) -> str:
    """The summary without links (the app shows those), as JSON."""

    def strip(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {k: v for k, v in row.items() if not k.endswith("_url")}

    shown = {k: v for k, v in result.items() if k not in ("top_seeds_url", "best", "alternatives")}
    shown["best"] = strip(result.get("best"))
    shown["alternatives"] = [strip(r) for r in result.get("alternatives") or []]
    shown["trade_links"] = "The app shows trade searches for these seeds below your answer."
    return json.dumps(shown, ensure_ascii=False)


def find(call: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run the search on the loaded build; `call` runs a pob-mcp tool (call_internal)."""
    items = call("get_items", {})
    current = socketed(items.data) if items.ok else None
    result = call(TOOL_NAME, arguments_for_pob(arguments, current))
    if not result.ok:
        raise PobToolError(result.text)
    if not isinstance(result.data, dict):
        raise PobToolError("find_timeless_jewel returned nothing readable.")
    return summarise(result.data, current)
