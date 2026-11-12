"""Which passive notables to take next: ranked for damage and toughness together.

pob-mcp's rank_passives scores reachable notables (with the travel nodes on the
way) for one stat at a time. This runs it for damage and for effective HP and
combines the two per node, weighted by what the user cares about, per point
spent. With no points left it ranks respec candidates instead: the allocated
notables that give the least.
"""

from __future__ import annotations

from typing import Any

from .pob import PobToolError
from .progress import Progress, Steps, drain

TOOL_NAME = "suggest_passives"
DPS_STAT = "CombinedDPS"
EHP_STAT = "TotalEHP"
WEIGHTS = {"balanced": (1.0, 1.0), "damage": (1.0, 0.25), "defence": (0.25, 1.0)}
MAX_CANDIDATES = 200  # all reachable notables; the trimming happens here
MAX_ROWS = 10
DEFAULT_PATH_COST = 8

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Rank which passive notables and keystones the loaded build should take next, "
            "calculated in Path of Building for both damage (CombinedDPS) and toughness "
            "(TotalEHP), including the travel nodes on the way, per point spent. Use it for "
            "'which passives / notables should I take', 'where do my next points go' or "
            "'what should I respec' questions. With no unspent points it ranks the allocated "
            "notables that give the least (respec candidates) instead. Keystones are marked: "
            "say what their drawback is before recommending one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "enum": list(WEIGHTS),
                    "description": "What matters most: balanced (default), damage or defence.",
                },
                "max_path_cost": {
                    "type": "integer",
                    "description": "Most points to spend on one pick (default 8).",
                },
            },
        },
    },
}


def _rank(call: Any, metric: str, mode: str, max_path_cost: int) -> tuple[float, list[dict]]:
    arguments: dict[str, Any] = {"metric": metric, "mode": mode, "limit": MAX_CANDIDATES}
    if mode == "add":
        arguments["max_path_cost"] = max_path_cost
    result = call("rank_passives", arguments)
    if not result.ok or not isinstance(result.data, dict):
        raise PobToolError(f"Couldn't rank passives: {result.text[:300]}")
    base = float(result.data.get("base") or 0.0)
    return base, [r for r in result.data.get("results", []) if isinstance(r, dict)]


def _pct(row: dict | None, base: float) -> float:
    if row is None:
        return 0.0
    pct = row.get("pct")
    if isinstance(pct, int | float):
        return float(pct)
    gain = row.get("gain")
    return float(gain) / base * 100 if isinstance(gain, int | float) and base else 0.0


def suggest(call: Any, summary: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    return drain(suggest_steps(call, summary, arguments))


def suggest_steps(
    call: Any, summary: dict[str, Any], arguments: dict[str, Any]
) -> Steps[dict[str, Any]]:
    """Rank picks for the loaded build; `call` runs a pob-mcp tool (call_internal)."""
    focus = arguments.get("focus") if arguments.get("focus") in WEIGHTS else "balanced"
    max_cost = int(arguments.get("max_path_cost") or DEFAULT_PATH_COST)
    max_cost = max(1, min(max_cost, 20))
    remaining = int(summary.get("passivePointsRemaining") or 0)
    mode = "add" if remaining > 0 else "remove"
    yield Progress(0, 2, "damage")
    dps_base, by_dps = _rank(call, DPS_STAT, mode, max_cost)
    yield Progress(1, 2, "toughness")
    ehp_base, by_ehp = _rank(call, EHP_STAT, mode, max_cost)
    ehp_by_id = {row.get("id"): row for row in by_ehp}
    dps_by_id = {row.get("id"): row for row in by_dps}
    w_dps, w_ehp = WEIGHTS[focus]

    rows = []
    for node_id in dict.fromkeys([*dps_by_id, *ehp_by_id]):
        dps_row, ehp_row = dps_by_id.get(node_id), ehp_by_id.get(node_id)
        row = dps_row or ehp_row or {}
        points = row.get("cost") if mode == "add" else row.get("pointsRefunded")
        points = int(points) if isinstance(points, int | float) and points > 0 else 1
        dps, ehp = _pct(dps_row, dps_base), _pct(ehp_row, ehp_base)
        if mode == "remove":
            # A removal's pct is the loss (negative or zero); report what the node gives.
            dps, ehp = abs(dps), abs(ehp)
        score = (w_dps * dps + w_ehp * ehp) / points
        rows.append(
            {
                "name": row.get("name", "?"),
                "type": row.get("type", "Notable"),
                "points": points,
                "dps_pct": round(dps, 1),
                "ehp_pct": round(ehp, 1),
                "score": round(score, 2),
                "stats": [str(s) for s in row.get("stats", [])][:4],
            }
        )
    # Adding: the best value per point first. Removing: the least valuable first.
    rows.sort(key=lambda r: r["score"], reverse=mode == "add")
    return {
        "mode": "take" if mode == "add" else "respec",
        "focus": focus,
        "points_remaining": remaining,
        "max_path_cost": max_cost,
        "rows": rows[:MAX_ROWS],
        "note": (
            "Damage and toughness are % changes of CombinedDPS and TotalEHP from Path of "
            "Building, including travel nodes; points = points the pick costs"
            + (" (or refunds)" if mode == "remove" else "")
            + ". Keystones have drawbacks the numbers don't show."
        ),
    }
