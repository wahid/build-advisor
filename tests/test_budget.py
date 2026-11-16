"""Upgrades within a budget: affordable uniques tried on the build."""

import json
from types import SimpleNamespace

import pytest

from advisor.budget import BudgetError, find
from advisor.llm import ToolCall
from advisor.pob import NO_BUILD_ERROR, ToolResult
from advisor.rag import _ToolRunner

UNIQUES = {
    "Belt": [
        {"name": "Ryslatha's Coil", "levelReq": 20},
        {"name": "Headhunter", "levelReq": 40},
        {"name": "Meginord's Girdle", "levelReq": 8},
        {"name": "Too High", "levelReq": 99},
        {"name": "Rare Listing", "levelReq": 1},
    ],
    "Ring": [{"name": "Le Heup of All", "levelReq": 24}],
}
PRICES = [
    {"name": "Ryslatha's Coil", "chaos": 100, "divine": 0.65, "listings": 291, "links": None},
    {"name": "Headhunter", "chaos": 23762, "divine": 154.5, "listings": 6, "links": None},
    {"name": "Meginord's Girdle", "chaos": 2, "divine": 0.01, "listings": 400, "links": None},
    {"name": "Meginord's Girdle", "chaos": 1, "divine": 0.01, "listings": 50, "links": None},
    {"name": "Rare Listing", "chaos": 5, "divine": 0.03, "listings": 1, "links": None},
    {"name": "Le Heup of All", "chaos": 30, "divine": 0.2, "listings": 80, "links": None},
    {"name": "Too High", "chaos": 1, "divine": 0.01, "listings": 80, "links": None},
]
# name -> (dps %, ehp %); the ring is better in Ring 2.
EFFECT = {
    "Ryslatha's Coil": (30.0, 0.0),
    "Meginord's Girdle": (2.0, 12.0),
    "Le Heup of All": (5, 5),
}


class FakePob:
    def __init__(self):
        self.calls = []

    def __call__(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "search_uniques":
            data = {"uniques": UNIQUES.get(arguments["item_type"], [])}
        elif name == "price_check":
            data = {
                "league": "Covens",
                "prices": [p for p in PRICES if p["name"] in arguments["names"]],
            }
        elif name == "get_items":
            data = {"items": [{"slot": "Belt", "name": "Doom Clasp, Leather Belt"}]}
        elif name == "compare_changes":
            edit = arguments["edits"][0]
            dps, ehp = EFFECT.get(edit["name"], (0, 0))
            if edit["slot"] == "Ring 2":
                dps += 10
            data = {
                "changes": {
                    "CombinedDPS": {"pct": dps},
                    "TotalEHP": {"pct": ehp},
                    "FireResist": {"before": 75, "after": 60, "change": -15},
                }
            }
        else:
            raise AssertionError(name)
        return SimpleNamespace(ok=True, data=data, text="")


def test_affordable_uniques_are_tried_and_ranked() -> None:
    pob = FakePob()

    result = find(pob, {"level": 90}, {"budget": 100})

    names = [row["name"] for row in result["rows"]]
    assert names == ["Ryslatha's Coil", "Le Heup of All", "Meginord's Girdle"]
    coil, ring, girdle = result["rows"]
    assert (coil["chaos"], coil["slot"], coil["replaces"]) == (
        100,
        "Belt",
        "Doom Clasp, Leather Belt",
    )
    assert ring["slot"] == "Ring 2" and ring["dps_pct"] == 15.0  # the better ring slot
    assert girdle["chaos"] == 1  # the cheapest listing
    assert coil["resists"] == {"fire": -15}
    assert result["league"] == "Covens" and result["tried"] == 3
    tried = [a["edits"][0]["name"] for n, a in pob.calls if n == "compare_changes"]
    assert "Headhunter" not in tried  # over budget
    assert "Too High" not in tried and "Rare Listing" not in tried  # level, too few listings


def test_a_divine_budget_uses_the_markets_rate_and_focus_changes_the_order() -> None:
    result = find(
        FakePob(), {"level": 90}, {"budget": 0.5, "currency": "divine", "focus": "defence"}
    )

    assert result["budget_chaos"] == pytest.approx(76.9, abs=0.1)  # 23762 / 154.5 per divine
    assert [row["name"] for row in result["rows"]] == ["Meginord's Girdle", "Le Heup of All"]


def test_slots_can_be_limited_and_a_budget_is_required() -> None:
    pob = FakePob()

    result = find(pob, {"level": 90}, {"budget": 50, "slots": ["Ring", "Sword"]})

    assert [row["name"] for row in result["rows"]] == ["Le Heup of All"]
    assert [a["item_type"] for n, a in pob.calls if n == "search_uniques"] == ["Ring"]
    with pytest.raises(BudgetError):
        find(FakePob(), {}, {"budget": 0})


class Toolbox:
    definitions: list = []

    def __init__(self, has_build: bool = True) -> None:
        self.has_build = has_build
        self.pob = FakePob()

    def call_internal(self, name, arguments):
        if name == "get_build_summary":
            return ToolResult(ok=True, text="", data={"level": 90})
        result = self.pob(name, arguments)
        return ToolResult(ok=True, text="", data=result.data)


def test_the_tool_reports_progress_and_sends_the_table() -> None:
    runner = _ToolRunner(Toolbox())
    steps = runner.stream(ToolCall("c1", "budget_upgrades", json.dumps({"budget": 100})))
    seen = []
    while True:
        try:
            seen.append(next(steps))
        except StopIteration as stop:
            rest, text = stop.value
            break

    assert seen[0]["type"] == "tool_call"
    assert [e["label"] for e in seen[1:]][:2] == ["looking up prices", "Ryslatha's Coil"]
    table = next(e for e in rest if e["type"] == "upgrades")
    assert table["rows"][0]["name"] == "Ryslatha's Coil" and '"Covens"' in text


def test_the_tool_needs_a_build() -> None:
    events, text = _ToolRunner(Toolbox(has_build=False)).run(
        ToolCall("c1", "budget_upgrades", '{"budget": 5}')
    )
    assert text == NO_BUILD_ERROR and events[-1]["ok"] is False
