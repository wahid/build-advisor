"""Maxroll's Build Progression Tool: the planner profile as guide text (wiki.progression)."""

import json

import pytest
import responses

from wiki.maxroll import MaxrollClient, parse_guide
from wiki.models import MaxrollRequest
from wiki.progression import gem_name, planner_ref, planner_text, profile_url, rich_text

from .test_maxroll import URL, FakeClock

PROFILE_ID = "ef5hj0rf"
PROFILE_URL = f"https://planners.maxroll.gg/profiles/load/poe/{PROFILE_ID}"

PAGE_HTML = f"""<html><head><title>Poison AW for Path of Exile 3.30 | Maxroll.gg</title></head>
<body><article><h1>Poison AW for Path of Exile 3.30</h1>
<h2>Build Tool</h2>
<p>All of our Build Guides are now found in the Build Progression Tool.</p>
<figure class="embed poe-embed-wrapper"><div class="poe-embed" data-poe-profile="{PROFILE_ID}"
 data-poe-id="11" data-poe-type="leveling"><div class="poeplanner-wrapper">Rendered tool</div>
</div></figure>
</article></body></html>"""


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _doc(*children: dict) -> dict:
    return {"root": {"type": "root", "children": list(children)}}


def _para(*children: dict) -> dict:
    return {"type": "paragraph", "children": list(children)}


def _gems(*ids: str) -> dict:
    return {"type": 0, "gems": [{"id": gem_id, "level": 1} for gem_id in ids]}


DATA = {
    "embeds": [
        {
            "type": "skills",
            "id": 3,
            "name": "Leveling skills",
            "steps": [
                {"name": "Lvl 2", "skills": [_gems("RollingMagma", "SupportArcaneSurge")]},
                {"name": "Lvl 12", "skills": [_gems("SummonRagingSpirit"), _gems("FlameDash")]},
            ],
        },
        {
            "type": "skills",
            "id": 4,
            "name": "Skill progression",
            "steps": [
                {
                    "name": "Late",
                    "skills": [_gems("AnimateWeaponAltY", "SupportChanceToPoison", "Despair")],
                }
            ],
        },
        {"type": "ascendancy", "id": 5, "ascendancy": "Necromancer", "steps": [[5415]]},
        {
            "type": "passives",
            "id": 6,
            "variants": [
                {"name": "Leveling", "history": [1, 2, 3]},
                {"name": "Late", "history": [1]},
            ],
        },
        {"type": "equipment", "id": 1, "name": "Early", "items": {"Helm": 43}},
        {
            "type": "leveling",
            "id": 11,
            "overview": {
                "title": "Poison Ranged Animate Weapons ",
                "league": "3.30",
                "showcaseVideo": "RewVHLHq5mM",
                "bandits": "all",
                "ascendancy": {"id": 5, "index": 0},
                "passives": {"id": 6, "index": 1},
                "skills": {"id": 4, "index": 0},
                "introduction": _doc(_para(_text("A powerful minion build."))),
                "buildRating": [{"title": "Budget", "subtitle": "Moderate", "difficulty": 3}],
                "strengthsAndWeaknesses": {"strengths": ["Very tanky"], "weaknesses": ["Clarity"]},
            },
            "steps": [
                {"level": 0, "skills": {"id": 3, "index": 0}},
                {"level": 12, "skills": {"id": 3, "index": 1}},
                {"level": 20, "skills": {"id": 3, "index": 1}},
                {"level": 30, "skills": {"id": 3, "index": 9}},
            ],
            "tabs": [
                {"id": "overview", "name": "Overview"},
                {
                    "id": "abc",
                    "name": "Build Info",
                    "content": _doc(
                        {"type": "heading", "tag": "h1", "children": [_text("Scaling")]},
                        _para(
                            _text("You use "),
                            {"type": "embed", "embedType": "poe-item", "text": "Despair"},
                            _text(" to curse."),
                            {"type": "linebreak"},
                            {"type": "embed", "embedType": "ad", "text": ""},
                            _text("Second line."),
                        ),
                    ),
                },
                {"id": "leveling", "name": "Leveling"},
                {"id": "progression", "name": "Progression"},
            ],
            "pobs": [{"label": "Softcore PoB", "link": "https://maxroll.gg/poe/pob/gm7x80au"}],
            "milestones": [
                {
                    "title": "Early Game",
                    "items": [
                        {
                            "title": "Gearing",
                            "content": _doc(
                                _para(_text("Look for Life on every piece.")),
                                {
                                    "type": "list",
                                    "children": [
                                        {"type": "listitem", "children": [_text("Bone rings")]},
                                        {
                                            "type": "listitem",
                                            "children": [
                                                {
                                                    "type": "link",
                                                    "url": "https://maxroll.gg/poe/x",
                                                    "children": [_text("Wands")],
                                                }
                                            ],
                                        },
                                    ],
                                },
                            ),
                        }
                    ],
                }
            ],
            "showTipsAndTricks": True,
            "tipsAndTricks": _doc(_para(_text("Pick up every Chaos Orb."))),
        },
    ]
}
PROFILE = {"id": PROFILE_ID, "name": "Poison ranged animate weapon", "data": json.dumps(DATA)}


def test_the_tool_is_found_in_the_page() -> None:
    assert planner_ref(PAGE_HTML) == (PROFILE_ID, 11)
    assert planner_ref("<article><p>No tool here.</p></article>") is None
    assert planner_ref('<div data-poe-profile="../../x" data-poe-id="1"></div>') is None
    assert planner_ref(f'<div data-poe-profile="{PROFILE_ID}" data-poe-type="tree"></div>') is None
    assert profile_url(PROFILE_ID) == PROFILE_URL
    with pytest.raises(ValueError):
        profile_url("a/b")


@pytest.mark.parametrize(
    ("gem_id", "name"),
    [
        ("SupportChanceToPoison", "Chance to Poison Support"),
        ("PurityOfElements", "Purity of Elements"),
        ("Despair", "Despair"),
        ("AnimateWeaponAltY", "Animate Weapon (transfigured version)"),
    ],
)
def test_gem_ids_become_names(gem_id: str, name: str) -> None:
    assert gem_name(gem_id) == name


def test_rich_text_keeps_names_lists_and_headings() -> None:
    tab = DATA["embeds"][-1]["tabs"][1]["content"]
    assert rich_text(tab) == "### Scaling\n\nYou use Despair to curse.\nSecond line."


def test_the_profile_becomes_guide_text() -> None:
    text = planner_text(PROFILE, 11)

    assert text.startswith("## Build overview: Poison Ranged Animate Weapons\n")
    for line in ("- League: 3.30", "- Ascendancy: Necromancer", "- Bandits: kill all"):
        assert line in text
    assert "- Budget: Moderate" in text
    assert "A powerful minion build." in text
    assert "Strengths: Very tanky." in text and "Weaknesses: Clarity." in text
    assert "- Softcore PoB: https://maxroll.gg/poe/pob/gm7x80au" in text
    assert "Leveling (3 points), Late (1 points)" in text
    assert (
        "## Skill gem setups\n\n### Late\n\n"
        "- Animate Weapon (transfigured version) + Chance to Poison Support + Despair" in text
    )
    assert "## Build Info\n\n### Scaling" in text
    assert "### From level 1\n\n- Rolling Magma + Arcane Surge Support" in text
    assert "### From level 12\n\n- Summon Raging Spirit\n- Flame Dash" in text
    assert "From level 20" not in text  # same setup as level 12
    assert "From level 30" not in text  # points at a step that isn't there
    assert "### Tips and tricks\n\nPick up every Chaos Orb." in text
    assert (
        "## Progression: Early Game\n\n### Gearing\n\nLook for Life on every piece.\n\n"
        "- Bone rings\n- Wands" in text
    )
    assert "RewVHLHq5mM" not in text  # the video
    assert text.index("## Build Info") < text.index("## Leveling") < text.index("## Progression")


@pytest.mark.parametrize("profile", [None, {}, {"data": "not json"}, {"data": {"embeds": [1]}}, []])
def test_an_unknown_format_gives_no_text(profile) -> None:
    assert planner_text(profile, 11) == ""


def test_parse_guide_adds_the_tool_after_the_article() -> None:
    page = parse_guide(URL, PAGE_HTML, PROFILE, 11)

    assert page.text.index("Build Progression Tool") < page.text.index("## Build overview")
    assert "Rendered tool" not in page.text  # the tool's own markup is still dropped
    assert "## Progression: Early Game" in page.text
    assert "## Build overview" not in parse_guide(URL, PAGE_HTML).text


@pytest.mark.django_db
@responses.activate
def test_loading_a_guide_fetches_its_profile_as_a_second_request() -> None:
    responses.get(URL, body=PAGE_HTML)
    responses.get(PROFILE_URL, json=PROFILE)
    clock = FakeClock()
    client = MaxrollClient("tests", clock=clock, sleep=clock.sleep)

    page = client.load_guide(URL)

    assert "### Gearing" in page.text
    assert [r.url for r in MaxrollRequest.objects.order_by("requested_at")] == [URL, PROFILE_URL]
    assert clock.slept == [1.0]  # one request per second, the profile included


@pytest.mark.django_db
@responses.activate
def test_a_guide_is_kept_when_its_profile_cant_be_loaded() -> None:
    responses.get(URL, body=PAGE_HTML)
    responses.get(PROFILE_URL, status=404)
    clock = FakeClock()

    page = MaxrollClient("tests", clock=clock, sleep=clock.sleep).load_guide(URL)

    assert "Build Progression Tool" in page.text
    assert "## Build overview" not in page.text
