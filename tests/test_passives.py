"""Ranking passive notables for damage and toughness together."""

import json
from types import SimpleNamespace

import pytest

from advisor.llm import ToolCall
from advisor.passives import suggest
from advisor.pob import NO_BUILD_ERROR, ToolResult
from advisor.rag import _ToolRunner

DPS = {
    "base": 100.0,
    "results": [
        {
            "id": 1,
            "name": "Bloodletting",
            "type": "Notable",
            "cost": 4,
            "pct": 300.0,
            "stats": ["+15%"],
        },
        {"id": 2, "name": "Resolute Technique", "type": "Keystone", "cost": 6, "pct": 330.0},
        {"id": 3, "name": "Golem's Blood", "type": "Notable", "cost": 3, "pct": 0.0},
    ],
}
EHP = {
    "base": 1000.0,
    "results": [
        {"id": 3, "name": "Golem's Blood", "type": "Notable", "cost": 3, "pct": 14.0},
        {"id": 1, "name": "Bloodletting", "type": "Notable", "cost": 4, "pct": 0.0},
    ],
}


def fake_call(calls: list):
    def call(name, arguments):
        calls.append((name, arguments))
        data = DPS if arguments["metric"] == "CombinedDPS" else EHP
        return SimpleNamespace(ok=True, data=data, text="")

    return call


def test_picks_are_ranked_per_point_on_damage_and_toughness() -> None:
    calls: list = []

    result = suggest(fake_call(calls), {"passivePointsRemaining": 20}, {"focus": "damage"})

    assert result["mode"] == "take" and result["focus"] == "damage"
    names = [row["name"] for row in result["rows"]]
    assert names == ["Bloodletting", "Resolute Technique", "Golem's Blood"]
    blood = result["rows"][2]
    assert (blood["dps_pct"], blood["ehp_pct"], blood["points"]) == (0.0, 14.0, 3)
    assert {a["metric"] for _, a in calls} == {"CombinedDPS", "TotalEHP"}
    assert all(a["mode"] == "add" and a["max_path_cost"] == 8 for _, a in calls)


def test_defence_focus_moves_toughness_up() -> None:
    result = suggest(fake_call([]), {"passivePointsRemaining": 5}, {"focus": "defence"})

    assert result["rows"][0]["name"] == "Bloodletting"  # 300% x 0.25 / 4 = 18.75
    assert result["rows"][1]["name"] == "Resolute Technique"
    # Golem's Blood: (0 + 14) / 3 = 4.7 per point
    assert result["rows"][2]["score"] == pytest.approx(4.67, abs=0.01)


def test_without_points_left_the_least_valuable_come_first() -> None:
    calls: list = []

    result = suggest(fake_call(calls), {"passivePointsRemaining": 0}, {})

    assert result["mode"] == "respec"
    assert all(a["mode"] == "remove" and "max_path_cost" not in a for _, a in calls)
    assert result["rows"][0]["name"] == "Golem's Blood"  # gives the least per point


class PassiveToolbox:
    definitions: list = []

    def __init__(self, has_build: bool) -> None:
        self.has_build = has_build

    def call_internal(self, name, arguments):
        if name == "get_build_summary":
            return ToolResult(ok=True, text="", data={"passivePointsRemaining": 10})
        data = DPS if arguments["metric"] == "CombinedDPS" else EHP
        return ToolResult(ok=True, text="", data=data)


def test_the_tool_sends_the_table_to_the_app_and_the_numbers_to_the_model() -> None:
    runner = _ToolRunner(PassiveToolbox(has_build=True))

    events, text = runner.run(ToolCall("c1", "suggest_passives", json.dumps({"focus": "balanced"})))

    ranking = next(e for e in events if e["type"] == "passive_ranking")
    assert ranking["rows"][0]["name"] == "Bloodletting"
    assert '"Bloodletting"' in text


def test_the_tool_needs_a_build() -> None:
    runner = _ToolRunner(PassiveToolbox(has_build=False))

    events, text = runner.run(ToolCall("c1", "suggest_passives", "{}"))

    assert text == NO_BUILD_ERROR and events[-1]["ok"] is False
