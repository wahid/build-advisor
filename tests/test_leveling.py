"""Where gems come from while leveling: quest rewards, vendors, gem levels."""

import gzip
import json
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from advisor import leveling as tool
from advisor.llm import ToolCall
from advisor.pob import ToolResult
from advisor.rag import _ToolRunner
from wiki import leveling
from wiki.models import GemLevel, QuestReward

pytestmark = pytest.mark.django_db

DATA = {
    "rewards": [
        {
            "reward": "Cyclone",
            "kind": "quest",
            "quest": "Sever the Right Hand",
            "act": 3,
            "classes": ["Marauder", "Duelist", "Scion"],
            "npc": "",
        },
        {
            "reward": "Cyclone",
            "kind": "vendor",
            "quest": "Sever the Right Hand",
            "act": 3,
            "classes": ["Duelist", "Marauder", "Ranger", "Scion", "Templar"],
            "npc": "Clarissa",
        },
        {
            "reward": "Cyclone",
            "kind": "vendor",
            "quest": "Fallen from Grace",
            "act": 6,
            "classes": [],
            "npc": "Lilly Roth",
        },
        {
            "reward": "Brutality Support",
            "kind": "quest",
            "quest": "The Eternal Nightmare",
            "act": 4,
            "classes": ["Marauder"],
            "npc": "",
        },
        {
            "reward": "Brutality Support",
            "kind": "vendor",
            "quest": "Fallen from Grace",
            "act": 6,
            "classes": [],
            "npc": "Lilly Roth",
        },
    ],
    "gems": [
        {"name": "Cyclone", "required_level": 28, "support": False},
        {"name": "Brutality Support", "required_level": 38, "support": True},
    ],
}


class FakeClient:
    """Cargo rows as the wiki returns them (spaces in field names, strings)."""

    def __init__(self):
        self.calls = []

    def _cargo(self, **query):
        self.calls.append(query)
        if query["offset"]:
            return []
        if query["tables"] == "quest_rewards":
            return [
                {
                    "reward": "Cyclone",
                    "quest": "Sever the Right Hand",
                    "act": "3",
                    "classes": "Marauder,Duelist,Scion",
                }
            ]
        if query["tables"] == "vendor_rewards":
            return [
                {
                    "reward": "Cyclone",
                    "quest": "A Fixture of Fate",
                    "act": "3",
                    "classes": None,
                    "npc": "Siosa",
                }
            ]
        return [
            {"name": "Cyclone", "required level": "28", "class id": "Active Skill Gem"},
            {"name": "Cyclone", "required level": "28", "class id": "Active Skill Gem"},
        ]


def test_wiki_rows_are_read_and_stored() -> None:
    data = leveling.fetch(FakeClient())

    assert data["rewards"][0] == {
        "reward": "Cyclone",
        "kind": "quest",
        "act": 3,
        "quest": "Sever the Right Hand",
        "npc": "",
        "classes": ["Marauder", "Duelist", "Scion"],
    }
    assert data["rewards"][1]["classes"] == [] and data["rewards"][1]["npc"] == "Siosa"
    assert data["gems"] == [{"name": "Cyclone", "required_level": 28, "support": False}]
    assert leveling.store(data) == (2, 1)
    with pytest.raises(ValueError):
        leveling.store({"rewards": [], "gems": []})  # a failed download keeps what's stored
    assert QuestReward.objects.count() == 2


def test_a_lookup_is_for_the_class_and_sorted_by_when_gems_come() -> None:
    leveling.store(DATA)

    duelist = leveling.lookup(["Brutality", "Cyclone", "Made Up Gem"], "Duelist")

    assert [g["gem"] for g in duelist] == ["Cyclone", "Brutality Support", "Made Up Gem"]
    cyclone, brutality, unknown = duelist
    assert cyclone["required_level"] == 28
    assert cyclone["quest_reward"] == {"act": 3, "quest": "Sever the Right Hand"}
    assert [v["npc"] for v in cyclone["vendors"]] == ["Clarissa", "Lilly Roth"]
    assert brutality["quest_reward"] is None  # a Marauder reward only
    assert brutality["vendors"] == [
        {"act": 6, "npc": "Lilly Roth", "after_quest": "Fallen from Grace"}
    ]
    assert unknown["known"] is False
    witch = leveling.lookup(["Cyclone"], "Witch")[0]
    assert witch["quest_reward"] is None and [v["npc"] for v in witch["vendors"]] == ["Lilly Roth"]


def test_the_data_exports_and_loads(tmp_path) -> None:
    leveling.store(DATA)
    path = tmp_path / "leveling.json.gz"

    leveling.export(path)
    QuestReward.objects.all().delete()
    GemLevel.objects.all().delete()
    leveling.store(leveling.load(path))

    assert QuestReward.objects.count() == 5 and GemLevel.objects.count() == 2
    with gzip.open(path, "rt") as handle:
        assert json.load(handle)["gems"][0]["name"] == "Brutality Support"


def test_the_command_can_store_the_shipped_file(mocker) -> None:
    mocker.patch("wiki.leveling.load", return_value=DATA)

    call_command("fetch_leveling", "--load", stdout=SimpleNamespace(write=lambda *_: None))

    assert QuestReward.objects.count() == 5


class BuildToolbox:
    has_build = True

    def call_internal(self, name, arguments):
        if name == "get_skills":
            data = {
                "groups": [
                    {"isMain": False, "gems": [{"name": "Brutality Support", "enabled": True}]},
                    {
                        "isMain": True,
                        "gems": [
                            {"name": "Cyclone", "enabled": True},
                            {"name": "Off Gem", "enabled": False},
                        ],
                    },
                ]
            }
        else:
            data = {"className": "Duelist"}
        return ToolResult(ok=True, text="", data=data)


def test_the_tool_takes_gems_and_class_from_the_build() -> None:
    leveling.store(DATA)
    runner = _ToolRunner(BuildToolbox())

    events, text = runner.run(ToolCall("c1", "quest_rewards", "{}"))

    table = next(e for e in events if e["type"] == "leveling")
    assert table["class_name"] == "Duelist"
    assert [g["gem"] for g in table["gems"]] == ["Cyclone", "Brutality Support"]
    assert '"Sever the Right Hand"' in text


def test_without_a_build_the_tool_needs_gem_names() -> None:
    with pytest.raises(ValueError, match="Name the gems"):
        tool.run({}, None)
    leveling.store(DATA)
    result = tool.run({"gems": ["Cyclone"], "class_name": "Scion"}, None)
    assert result["gems"][0]["quest_reward"]["act"] == 3
