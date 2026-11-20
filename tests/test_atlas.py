"""The atlas_tree tool: reading atlas tree links and planning a tree for a farm."""

import base64
import json

import pytest

from advisor import atlas
from advisor.llm import ToolCall
from advisor.prompts import build_messages
from advisor.rag import _ToolRunner, answer_stream

from .test_advisor import FakeProvider
from .test_tool_loop import embedder  # noqa: F401  (fixture)

# The link from the issue: an essence tree with shrines, delirium and Kingsmarch.
USER_LINK = (
    "https://poeplanner.com/atlas-tree/BQAeAACOAGEfyAJfPmf5xmayZJlIJO9M9XjBAEhTIQLx3DvQDN6ih"
    "deLLrsubKT_-sHuIEp441flp-I8WfONW5z8TSjnUSiCscaG_3Wozd40Oj4iiEyET_eovB19dKF0HYvhfZHo8l"
    "cyDkpZzN7-nzuxnZdloQPbfiTRnthnYKyke2Bt3NaaK3HtkX-rtdjJz22mvcfVPymNWYZw4343yySCUVp5BfG"
    "pgQD53YN_4rPHPkbhENMOia8ZCszkao77sX21gojrXwLJu7LEheIO-4de304bcz4hTMUhm1qrdhdQxB8NKxN9G"
    "wiQ2ZGJyXDw_RiLQGILcX1tHITa-h1r5cYvcp49_crVadlcqUN2vQ9oZh_UbMQW6z3Zxna4TdG51NAoFAAfiwg"
    "AAAAAAAADAwAAAAAAAAAAAA=="
)


def _node(name, group, out=(), kind="", icon="Small.png", stats=("stat",), **extra):
    node = {
        "name": name,
        "group": group,
        "icon": f"Art/2DArt/SkillIcons/passives/AtlasTrees/{icon}",
        "stats": list(stats),
        "out": [str(o) for o in out],
        "in": [],
        **extra,
    }
    if kind:
        node[kind] = True
    return node


# root -> hub (free) -> essence small -> essence notable -> keystone
#                    -> essence small 2 -> essence notable 2
#                    -> travel -> shrine small -> shrine notable
#                             -> notable outside a cluster with the essence icon
#                    -> maps small -> maps notable
#                    -> choice notable
#        gateways 20 and 21 (same name) are linked
EXPORT = {
    "points": {"totalPoints": 6},
    "nodes": {
        "root": {"group": 0, "out": ["100"], "in": []},
        "100": {"name": "", "group": 0, "stats": [], "out": ["1", "3", "5", "7", "9"], "in": []},
        "1": _node("Essence Chance", 1, out=[2], icon="EssenceNode1.png"),
        "2": _node("Prolific Essence", 1, out=[11], kind="isNotable", icon="EssenceNode1.png"),
        "11": _node("Wandering Path", 1, kind="isKeystone", stats=("Notables have no effect",)),
        "3": _node("Essence Chance", 1, out=[4], icon="EssenceNode1.png"),
        "4": _node("Amplified Energies", 1, kind="isNotable", icon="EssenceNode1.png"),
        "5": _node("Map Drop Chance", 9, out=[6, 12]),
        "6": _node("Shrine Chance", 2, out=[13]),
        "13": _node("Supplication", 2, kind="isNotable"),
        "12": _node("Ill Feeling", 9, kind="isNotable", icon="EssenceNode2.png", out=[20]),
        "7": _node("Map Drops", 3, out=[8]),
        "8": _node("Shaping the Skies", 3, kind="isNotable"),
        "9": _node(
            "Outside Entities",
            8,
            kind="isNotable",
            icon="TempestNotable1.png",
            stats=("Select a type of content",),
            isMultipleChoiceVariant=True,
            variantEffects=[{"stats": ["Breach"]}, {"stats": ["Legion"]}],
        ),
        "20": _node("Mortal Gateway", 9, kind="isWormhole"),
        "21": _node("Mortal Gateway", 9, kind="isWormhole"),
        "901": _node("Essence", 1, kind="isMastery", stats=()),
        "902": _node("Shrines", 2, kind="isMastery", stats=()),
        "903": _node("Maps", 3, kind="isMastery", stats=()),
    },
}


@pytest.fixture
def tree() -> atlas.Tree:
    return atlas.tree_from_data(atlas.trim_export(EXPORT, "3.30.0c"))


def _poeplanner(ids: list[int], minor: int = 30) -> str:
    head = b"\x05\x00" + minor.to_bytes(2, "little") + b"\x00"
    body = len(ids).to_bytes(2, "little") + b"".join(i.to_bytes(2, "little") for i in ids)
    code = base64.urlsafe_b64encode(head + body + b"\x00\x00").decode()
    return f"https://poeplanner.com/atlas-tree/{code}"


def test_export_is_trimmed_to_nodes_links_and_mechanics(tree) -> None:
    assert 100 not in tree.nodes  # the free hub is part of the start
    assert tree.adjacent[atlas.ROOT] == {1, 3, 5, 7, 9}
    assert 901 not in tree.nodes  # masteries are labels, not nodes
    assert tree.nodes[2].mechanic == "Essence"
    assert tree.nodes[5].mechanic == ""  # a travel node
    assert tree.nodes[12].mechanic == "Essence"  # by its icon
    assert tree.nodes[9].mechanic == atlas.CHOICE
    assert tree.nodes[9].choices == (("Breach",), ("Legion",))
    assert tree.nodes[11].kind == "keystone"
    assert 21 in tree.adjacent[20]  # gateways of one name are linked
    assert tree.points == 6


def test_poeplanner_links_round_trip(tree) -> None:
    url = _poeplanner([1, 2, 5])
    link = atlas.decode(url, tree)
    assert link.nodes == (1, 2, 5)
    assert link.layout == atlas.POEPLANNER
    assert link.link_minor_version == 30
    assert atlas.encode(link.nodes, tree, link) == url


def test_pathofexile_links_are_read(tree) -> None:
    ids = [1, 2]
    data = (6).to_bytes(4, "big") + b"\x00\x00" + bytes([len(ids)])
    data += b"".join(i.to_bytes(2, "big") for i in ids) + b"\x00\x00"
    url = "https://www.pathofexile.com/fullscreen-atlas-skill-tree/" + (
        base64.urlsafe_b64encode(data).decode()
    )
    assert atlas.decode(url, tree).nodes == (1, 2)


@pytest.mark.parametrize(
    "code", ["!!!", base64.urlsafe_b64encode(b"\x05\x00\x1e\x00\x00\x01\x00\xff\xff").decode()]
)
def test_unreadable_links_are_an_error(tree, code) -> None:
    with pytest.raises(atlas.AtlasError):
        atlas.decode(f"https://poeplanner.com/atlas-tree/{code}", tree)


def test_links_are_found_and_stripped_from_text() -> None:
    text = f"Is this good for essence? {USER_LINK} thanks"
    assert atlas.urls_in(text) == [USER_LINK]
    assert "BQAe" not in atlas.strip_urls(text)


def test_a_tree_is_broken_down_by_mechanic(tree) -> None:
    result = atlas.analyse(_poeplanner([1, 2, 3, 4, 5]), tree=tree)
    assert result["points_used"] == 5
    assert result["points_unspent"] == 1
    assert result["mechanics"][0] == {
        "mechanic": "Essence",
        "points": 4,
        "notables": ["Prolific Essence", "Amplified Energies"],
    }
    assert result["focus"] == ["Essence"]
    assert "plan" not in result


def test_a_plan_drops_what_the_farm_doesnt_use_and_buys_its_notables(tree) -> None:
    result = atlas.analyse(_poeplanner([5, 6, 13, 7, 8]), ["essences"], tree=tree)
    plan = result["plan"]
    assert plan["farm"] == ["Essence"]
    # Shrines and the travel node to them go; map sustain stays.
    assert {r["mechanic"] for r in plan["remove"]} == {"Shrines", "travel"}
    assert plan["points_freed"] == 3
    # Four points to spend: the cheapest essence notable is two away, then the next.
    assert [row["name"] for row in plan["add"]] == ["Prolific Essence", "Amplified Energies"]
    assert [row["cost"] for row in plan["add"]] == [2, 2]
    assert plan["points_after"] == 6
    assert plan["points_left"] == 0
    # The keystone is never added, only shown.
    assert [k["name"] for k in plan["keystones_in_reach"]] == ["Wandering Path"]
    new = atlas.decode(result["link"], tree)
    assert set(new.nodes) == {7, 8, 1, 2, 3, 4}


def test_a_tree_can_be_planned_from_scratch(tree) -> None:
    result = atlas.analyse("", ["Shrines"], tree=tree)
    assert result["plan"]["add"][0]["name"] == "Supplication"
    assert "mechanics" not in result


def test_unknown_mechanics_and_no_input_are_errors(tree) -> None:
    with pytest.raises(atlas.AtlasError, match="Not an atlas mechanic: heist"):
        atlas.analyse("", ["heist"], tree=tree)
    with pytest.raises(atlas.AtlasError, match="Give an atlas tree link"):
        atlas.analyse("", [], tree=tree)


def test_an_old_link_gets_a_note(tree) -> None:
    result = atlas.analyse(_poeplanner([1, 2], minor=29), tree=tree)
    assert any("3.29" in note for note in result["notes"])


def test_mechanic_names_players_use(tree) -> None:
    assert atlas.resolve_mechanics(["shrine", "map sustain", "nope"], tree) == (
        ["Shrines", "Maps"],
        ["nope"],
    )


def test_the_shipped_tree_reads_the_users_link() -> None:
    result = atlas.analyse(USER_LINK, ["Essence", "Delirium"])
    assert result["points_used"] == 142
    assert result["focus"][0] == "Essence"
    plan = result["plan"]
    dropped = {row["mechanic"] for row in plan["remove"]}
    assert {"Shrines", "Settlers of Kalguur"} <= dropped
    assert "Essence" not in dropped
    assert plan["points_after"] <= result["points_total"]
    tree = atlas.load()
    kept = {tree.nodes[n].name for n in atlas.decode(result["link"]).nodes}
    assert {"Prolific Essence", "Descent Into Madness"} <= kept


def test_the_runner_uses_the_link_in_the_conversation() -> None:
    runner = _ToolRunner(None, atlas_links=[USER_LINK])
    events, text = runner.run(ToolCall("a1", atlas.TOOL_NAME, json.dumps({"farm": ["essence"]})))
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "atlas_tree"]
    assert events[-1]["link"].startswith(atlas.POEPLANNER_URL)
    assert "poeplanner.com" not in text  # the app shows the link, not the model


def test_the_runner_reports_errors_to_the_model() -> None:
    runner = _ToolRunner(None)
    events, text = runner.run(ToolCall("a1", atlas.TOOL_NAME, "{}"))
    assert events[-1]["ok"] is False
    assert text.startswith("Error: Give an atlas tree link")


def test_the_prompt_asks_for_the_linked_tree() -> None:
    system = build_messages("q", [], atlas_tool=True, atlas_linked=True)[0]["content"]
    assert "atlas_tree" in system
    assert "call atlas_tree for it" in system


@pytest.mark.django_db
def test_an_atlas_link_offers_the_tool_in_the_chat(embedder) -> None:  # noqa: F811
    provider = FakeProvider(
        [ToolCall("a1", atlas.TOOL_NAME, json.dumps({"farm": ["Essence"]}))],
        ["Drop the shrine wheel [1]."],
    )
    events = list(
        answer_stream(
            f"Optimise this for essence {USER_LINK}",
            provider=provider,
            embedder=embedder,
            rewrite=False,
            use_tools=False,
            web_search=False,
        )
    )
    offered = [t["function"]["name"] for t in provider.calls[0][1] or []]
    assert atlas.TOOL_NAME in offered
    assert any(e["type"] == "atlas_tree" for e in events)
    assert events[-1]["type"] == "done"
