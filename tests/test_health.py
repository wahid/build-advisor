"""The build health check: a checklist from Path of Building's data."""

from types import SimpleNamespace

from advisor.health import check
from advisor.llm import ToolCall
from advisor.pob import ToolResult
from advisor.rag import _ToolRunner

GEAR = [
    "Weapon 1",
    "Helmet",
    "Body Armour",
    "Gloves",
    "Boots",
    "Amulet",
    "Ring 1",
    "Ring 2",
    "Belt",
]
FLASKS = [f"Flask {n}" for n in range(1, 6)]


def pob(stats=None, summary=None, warnings=None, slots=None, audit=None):
    data = {
        "get_build_summary": {
            "level": 95,
            "passivePointsRemaining": 0,
            "ascendancyPointsAvailable": 8,
            "ascendancyPointsUsed": 8,
            **(summary or {}),
        },
        "get_stats": {
            "stats": {
                "Life": 5200,
                "EnergyShield": 300,
                "FireResist": 75,
                "ColdResist": 76,
                "LightningResist": 75,
                "ChaosResist": 45,
                "AccuracyHitChance": 100,
                "FreezeAvoidChance": 100,
                **(stats or {}),
            }
        },
        "get_warnings": {"warnings": warnings or []},
        "get_items": {"items": [{"slot": s} for s in (GEAR + FLASKS if slots is None else slots)]},
        "audit_config": audit or {"conditions": []},
    }

    def call(name, arguments):
        return SimpleNamespace(ok=True, data=data[name], text="")

    return call


def by_id(result):
    return {c["id"]: c for c in result["checks"]}


def test_a_sound_build_passes_everything() -> None:
    result = check(pob())

    assert (result["bad"], result["warn"]) == (0, 0)
    assert by_id(result)["resistances"]["detail"] == "All capped."
    assert "accuracy" not in by_id(result)  # 100%: nothing to say


def test_problems_come_first_with_what_is_wrong() -> None:
    warnings = [
        {"kind": "pob", "message": "You do not meet the Intelligence requirement of X"},
        {"kind": "requirement", "message": "Int requirement not met: need 111, have 102"},
        {"kind": "info", "message": "1 Mirage Archers using Tornado Shot"},
    ]
    audit = {
        "conditions": [
            {"label": "Do you use Frenzy Charges?", "changes": {"FullDPS": {"pct": -42.1}}},
            {"label": "Is the enemy Bleeding?", "changes": {"FullDPS": {"pct": -5.0}}},
        ]
    }
    result = check(
        pob(
            stats={
                "ColdResist": 41,
                "ChaosResist": -60,
                "Life": 2400,
                "EnergyShield": 0,
                "AccuracyHitChance": 80,
                "FreezeAvoidChance": 45,
            },
            summary={"passivePointsRemaining": 3, "ascendancyPointsUsed": 6},
            warnings=warnings,
            slots=["Weapon 1", "Helmet", "Flask 1"],
            audit=audit,
        )
    )

    checks = by_id(result)
    assert [c["status"] for c in result["checks"]][:3] == ["bad", "bad", "bad"]
    assert checks["resistances"]["detail"] == "Under the 75% cap: Cold 41%."
    assert checks["chaos"]["status"] == "bad"
    assert checks["pool"]["status"] == "bad" and "rule of thumb" in checks["pool"]["detail"]
    assert checks["requirements"]["detail"] == "Int requirement not met: need 111, have 102."
    assert checks["points"]["detail"] == "Unspent: 3 passive and 2 ascendancy points."
    assert checks["gear"]["detail"].startswith("Empty: Body Armour, Gloves")
    assert checks["flasks"]["detail"] == "4 of 5 flask slots are empty."
    assert checks["accuracy"]["status"] == "bad"
    assert checks["FreezeAvoidChance"]["status"] == "warn"
    assert "Frenzy Charges? (-42% DPS without it)" in checks["assumptions"]["detail"]
    assert "Bleeding" not in checks["assumptions"]["detail"]
    assert result["bad"] == 7


class Toolbox:
    definitions: list = []
    has_build = True

    def call_internal(self, name, arguments):
        return ToolResult(
            ok=True, text="", data=pob(stats={"FireResist": 10})(name, arguments).data
        )


def test_the_tool_sends_the_checklist_to_the_app() -> None:
    events, text = _ToolRunner(Toolbox()).run(ToolCall("c1", "health_check", "{}"))

    card = next(e for e in events if e["type"] == "health")
    assert card["checks"][0]["id"] == "resistances" and card["bad"] == 1
    assert "Fire 10%" in text
