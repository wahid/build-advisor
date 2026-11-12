"""Ranking skill gems by Path of Building's numbers (fake PoB calls)."""

from types import SimpleNamespace

import pytest

from advisor.gemrank import GemRanker, GemRankError, weapons_for
from advisor.models import GemRanking

pytestmark = pytest.mark.django_db


def ok(data):
    return SimpleNamespace(ok=True, data=data, text="")


@pytest.mark.parametrize(
    ("description", "tags", "expected"),
    [
        (
            "Requires a Sword, Axe, Mace, Sceptre, Staff or Unarmed.",
            "Attack, Melee, Slam",
            [
                "Two Handed Mace",
                "Two Handed Axe",
                "Two Handed Sword",
                "Staff",
                "One Handed Sword",
                "One Handed Mace",
                "One Handed Axe",
                "Sceptre",
            ],
        ),
        ("Fires an arrow.", "Attack, Bow, Projectile", ["Bow"]),
        ("Hits enemies in front of you.", "Attack, Melee, Strike", ["Two Handed Mace"]),
        ("Casts a fireball.", "Spell, Fire, Projectile", []),
    ],
)
def test_weapons_a_skill_can_use(description, tags, expected) -> None:
    assert weapons_for(description, tags) == expected


class FakePob:
    """Each gem's DPS is fixed; records the calls."""

    DPS = {"Sunder": 120.0, "Ice Crash": 300.0, "Earthquake": 200.0, "Taunt": 0.0}

    def __init__(self, current="Earthquake") -> None:
        self.calls: list[tuple[str, dict]] = []
        self.current = current

    def __call__(self, name, args):
        self.calls.append((name, args))
        if name == "search_gems":
            return ok(
                {
                    "gems": [
                        {"name": n, "tags": "Attack, Melee, Slam", "description": ""}
                        for n in self.DPS
                    ]
                }
            )
        if name == "compare_changes":
            edit = args["edits"][-1]  # a map-enemy test puts set_config first
            gem = edit.get("new_gem") or edit["gems"][0]
            # Like PoB, stats that didn't move are left out.
            before = self.DPS[self.current] if "new_gem" in edit else 0.0
            dps = self.DPS[gem]
            return ok({"changes": {"CombinedDPS": {"after": dps}} if dps != before else {}})
        if name == "get_skills":
            return ok(
                {
                    "groups": [
                        {
                            "index": 2,
                            "isMain": True,
                            "gems": [
                                {"name": self.current, "support": False},
                                {"name": "Brutality", "support": True},
                            ],
                        }
                    ]
                }
            )
        if name == "get_stats":
            return ok(
                {
                    "stats": {
                        "CombinedDPS": self.DPS[self.current],
                        "AverageDamage": 50,
                        "Speed": 1.0,
                    }
                }
            )
        return ok({})


def test_reference_ranking_sorts_by_dps_and_drops_skills_without_damage() -> None:
    pob = FakePob()

    result = GemRanker(pob).run({"tags": ["Slam"], "ascendancy": "Slayer"}, build_loaded=False)

    assert [r["gem"] for r in result["ranked"]] == ["Ice Crash", "Earthquake", "Sunder"]
    assert result["not_dealing_damage_here"] == 1
    assert pob.calls[1] == ("new_build", {"level": 90, "ascendancy": "Slayer"})
    weapon = next(a for n, a in pob.calls if n == "apply_changes")["edits"][0]
    assert weapon["base"] == "Coronal Maul"
    assert "170% increased Physical Damage" in weapon["mods"]
    assert result["ranked"][0]["map_dps"] == 300.0
    map_tests = [
        a["edits"] for n, a in pob.calls if n == "compare_changes" and len(a["edits"]) == 2
    ]
    assert map_tests[0][0] == {"op": "set_config", "var": "enemyIsBoss", "value": "None"}
    assert "level 90 Slayer" in result["method"]


def test_with_a_build_loaded_the_main_skill_is_swapped() -> None:
    pob = FakePob(current="Earthquake")

    result = GemRanker(pob).run({"tags": ["Slam"]}, build_loaded=True)

    assert [r["gem"] for r in result["ranked"]] == ["Ice Crash", "Earthquake", "Sunder"]
    assert result["ranked"][1]["weapon"] == "your build (current main skill)"
    swaps = [a["edits"][0] for n, a in pob.calls if n == "compare_changes"]
    assert swaps[0] == {
        "op": "replace_gem",
        "group": 2,
        "old_gem": "Earthquake",
        "new_gem": "Sunder",
    }
    assert not any(n == "new_build" for n, _ in pob.calls)  # the build is left alone


def test_tags_or_a_query_are_required() -> None:
    with pytest.raises(GemRankError, match="at least one tag"):
        GemRanker(FakePob()).run({"tags": []}, build_loaded=False)


def test_candidates_past_the_time_limit_are_reported(mocker) -> None:
    mocker.patch("advisor.gemrank.TIME_BUDGET", -1)  # out of time from the start

    result = GemRanker(FakePob()).run({"tags": ["Slam"]}, build_loaded=False)

    assert result["ranked"] == []
    assert result["not_tested_time_limit"] == 4
    assert result["not_dealing_damage_here"] == 0


def test_reference_rankings_are_cached() -> None:
    first = FakePob()
    GemRanker(first).run({"tags": ["Slam"], "ascendancy": "Slayer", "limit": 2}, build_loaded=False)
    again = FakePob()

    result = GemRanker(again).run(
        {"tags": ["slam "], "ascendancy": "slayer", "limit": 1}, build_loaded=False
    )

    assert again.calls == []  # nothing recalculated
    assert [r["gem"] for r in result["ranked"]] == ["Ice Crash"]
    assert result["cached"].startswith("calculated ")
    assert GemRanking.objects.count() == 1


def test_rankings_on_a_users_build_are_never_cached() -> None:
    GemRanker(FakePob()).run({"tags": ["Slam"]}, build_loaded=True)

    assert GemRanking.objects.count() == 0


def test_a_ranking_cut_short_by_the_time_limit_isnt_cached(mocker) -> None:
    mocker.patch("advisor.gemrank.TIME_BUDGET", -1)

    GemRanker(FakePob()).run({"tags": ["Slam"]}, build_loaded=False)

    assert GemRanking.objects.count() == 0
