"""What the patch notes say about a build's gems and items."""

import pytest

from advisor import patchimpact
from advisor.llm import ToolCall
from advisor.pob import ToolResult
from advisor.rag import _ToolRunner
from wiki.models import DocumentType

from .factories import make_document

pytestmark = pytest.mark.django_db

NOTES_3_29_0 = """Version History

## Patch notes

### Skill Gem Changes

- Tornado Shot now fires 2 fewer secondary projectiles at all gem levels.
- Cyclone: no changes this patch.
- Brutality now grants 35% more Physical Damage at gem level 20 (previously 39%).

### Unique Item Changes

- Headhunter can no longer steal Soul Eater.
- Short.
"""
NOTES_3_29_3 = (
    "## Patch notes\n\n- Fixed a bug where Tornado Shot could miss with Barrage Support.\n"
)
NOTES_3_28 = "## Patch notes\n\n- Tornado Shot deals 10% more damage.\n"


@pytest.fixture
def notes():
    make_document("Version 3.29.0", NOTES_3_29_0, doc_type=DocumentType.PATCH)
    make_document("Version 3.29.3", NOTES_3_29_3, doc_type=DocumentType.PATCH)
    make_document("Version 3.28.0l", NOTES_3_28, doc_type=DocumentType.PATCH)
    make_document("Tornado Shot", "Tornado Shot fires arrows.")  # a gem page: not searched


def test_versions_sort_by_number_not_by_text() -> None:
    titles = ["Version 3.9.0", "Version 3.29.0b", "Version 3.29.3", "Version 3.29.0"]

    assert sorted(titles, key=patchimpact.version_key, reverse=True) == [
        "Version 3.29.3",
        "Version 3.29.0b",
        "Version 3.29.0",
        "Version 3.9.0",
    ]


def test_lines_naming_the_parts_come_back_newest_first_with_their_section(notes) -> None:
    result = patchimpact.find(["Tornado Shot", "Brutality Support", "Headhunter", "Grace"])

    assert result["versions"] == ["3.29.3", "3.29.0"]  # the current major version only
    lines = [(c["version"], c["name"], c["section"]) for c in result["changes"]]
    assert lines == [
        ("3.29.3", "Tornado Shot", "Patch notes"),
        ("3.29.0", "Tornado Shot", "Skill Gem Changes"),
        ("3.29.0", "Brutality Support", "Skill Gem Changes"),  # written without "Support"
        ("3.29.0", "Headhunter", "Unique Item Changes"),
    ]
    assert result["changes"][1]["line"].startswith("Tornado Shot now fires 2 fewer")
    assert result["changes"][0]["url"].endswith("/Version_3.29.3")
    assert result["not_mentioned"] == ["Grace"]


def test_an_earlier_league_can_be_included(notes) -> None:
    result = patchimpact.find(["Tornado Shot"], major_versions=2)

    assert result["versions"] == ["3.29.3", "3.29.0", "3.28.0l"]
    assert result["changes"][-1]["line"] == "Tornado Shot deals 10% more damage."


class BuildToolbox:
    has_build = True
    definitions: list = []

    def call_internal(self, name, arguments):
        data = {
            "get_build_summary": {"ascendancy": "Slayer"},
            "get_skills": {"groups": [{"isMain": True, "gems": [{"name": "Tornado Shot"}]}]},
            "get_items": {"items": [{"name": "Headhunter, Leather Belt", "rarity": "UNIQUE"}]},
        }[name]
        return ToolResult(ok=True, text="", data=data)


def test_the_tool_uses_the_attached_builds_parts(notes) -> None:
    events, text = _ToolRunner(BuildToolbox()).run(ToolCall("c1", "patch_changes", "{}"))

    table = next(e for e in events if e["type"] == "patch_changes")
    assert {c["name"] for c in table["changes"]} == {"Tornado Shot", "Headhunter"}
    assert table["not_mentioned"] == ["Slayer"]
    assert "can no longer steal Soul Eater" in text


def test_without_a_build_names_are_needed(notes) -> None:
    events, text = _ToolRunner(None).run(ToolCall("c1", "patch_changes", "{}"))
    assert events[-1]["ok"] is False and "Name the gems" in text

    events, _ = _ToolRunner(None).run(ToolCall("c2", "patch_changes", '{"names": ["Headhunter"]}'))
    assert next(e for e in events if e["type"] == "patch_changes")["changes"]


def test_a_gems_name_inside_another_term_doesnt_count() -> None:
    make_document(
        "Version 3.29.0",
        "## Notes\n\n- +1 to Maximum Frenzy Charges on Rings, and Frenzy/Power charges too.\n"
        "- Armageddon Brand of Volatility now has 520% effectiveness.\n"
        "- Frenzy now has 10% more attack speed.\n",
        doc_type=DocumentType.PATCH,
    )

    result = patchimpact.find(["Frenzy", "Volatility Support"])

    assert [c["line"] for c in result["changes"]] == ["Frenzy now has 10% more attack speed."]
    assert result["not_mentioned"] == ["Volatility Support"]
