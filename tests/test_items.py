"""Items pasted from the game: reading them and trying them on a build."""

import pytest

from advisor.items import ItemError, check_item, item_title, parse_item, split_item
from advisor.pob import ToolResult
from advisor.rag import answer_stream

from .test_advisor import FakeProvider
from .test_tool_loop import FakeToolbox, embedder, toolbox  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db

RING = """Item Class: Rings
Rarity: Rare
Storm Loop
Two-Stone Ring
--------
Requirements:
Level: 49
--------
Item Level: 84
--------
+16% to Fire and Lightning Resistances (implicit)
--------
+52 to maximum Life
+38% to Cold Resistance
{ Suffix Modifier "of the Penguin" (Tier: 3) }
--------
Corrupted
--------
Note: ~price 5 chaos"""

UNIQUE = """Item Class: Boots
Rarity: Unique
Darkray Vectors
Dragonscale Boots
--------
Armour: 71
Evasion Rating: 71
--------
Requirements:
Level: 65
--------
+40% to Lightning Resistance
Adds 1 to 2 Lightning Damage: per Frenzy Charge
--------
Fast as light."""


def test_a_rare_ring_is_read_with_its_card() -> None:
    item = parse_item(RING)

    assert (item.item_class, item.rarity, item.name, item.base) == (
        "Rings",
        "rare",
        "Storm Loop",
        "Two-Stone Ring",
    )
    assert item.slots == ("Ring 1", "Ring 2")
    assert "{" not in item.text  # advanced-copy details are dropped
    card = item.card
    assert card["frame"] == "rare" and card["header"] == ["Storm Loop", "Two-Stone Ring"]
    texts = [[seg for line in g["lines"] for seg in line] for g in card["groups"]]
    assert {"t": "Level: ", "s": "default"} in texts[0][1:] or texts[0][1]["s"] == "default"
    assert {"t": "+16% to Fire and Lightning Resistances", "s": "mod"} in texts[2]
    assert card["groups"][-1]["style"] == "corrupted"
    assert not any("price" in seg["t"] for group in texts for seg in group)  # notes left out


def test_a_unique_has_flavour_text_and_mods_with_colons() -> None:
    card = parse_item(UNIQUE).card

    assert card["frame"] == "unique"
    assert card["groups"][-1]["style"] == "flavour"
    mods = [seg for line in card["groups"][2]["lines"] for seg in line]
    assert {"t": "Adds 1 to 2 Lightning Damage: per Frenzy Charge", "s": "mod"} in mods


def test_text_that_isnt_an_item_is_rejected() -> None:
    with pytest.raises(ItemError):
        parse_item("hello there")
    assert item_title("nope") == ""
    assert item_title(RING) == "Storm Loop, Two-Stone Ring"


def test_an_item_is_split_out_of_a_question() -> None:
    question, item = split_item(f"Is this good for me?\n{RING}\n\nAnd what about the price?")

    assert item.startswith("Item Class: Rings") and item.endswith("Note: ~price 5 chaos")
    assert question == "Is this good for me?\nAnd what about the price?"
    assert split_item("Just a question: no item here") == ("Just a question: no item here", "")


class ItemToolbox(FakeToolbox):
    """compare_changes: Ring 2 (empty) is better than replacing Ring 1."""

    has_build = True

    def call_internal(self, name: str, arguments: dict) -> ToolResult:
        self.calls.append((name, arguments))
        if name == "get_items":
            data = {"items": [{"slot": "Ring 1", "name": "Doom Loop, Coral Ring"}]}
        elif name == "compare_changes":
            slot = arguments["edits"][0]["slot"]
            life = 5900 if slot == "Ring 1" else 6265
            data = {
                "changes": {
                    "Life": {"before": 6200, "after": life},
                    "ColdResist": {"before": 37, "after": 75},
                    "TotalEHP": {"before": 30000, "after": 30000 * life / 6200, "pct": 0.0},
                }
            }
            data["changes"]["TotalEHP"]["pct"] = (life - 6200) / 62
        else:
            return super().call(name, arguments)
        return ToolResult(ok=True, text="", data=data)


def test_a_ring_is_tried_in_both_slots_and_the_better_one_wins() -> None:
    box = ItemToolbox()

    result = check_item(box, parse_item(RING))

    assert result["slot"] == "Ring 2" and result["replaces"] == ""
    by_stat = {row["stat"]: row for row in result["rows"]}
    assert by_stat["Life"]["b"] == 6265 and by_stat["ColdResist"]["change_pct"] > 0
    equips = [a["edits"][0] for n, a in box.calls if n == "compare_changes"]
    assert [e["slot"] for e in equips] == ["Ring 1", "Ring 2"]
    assert equips[0]["op"] == "equip_item" and "Storm Loop" in equips[0]["item_text"]


def test_items_without_a_gear_slot_are_explained() -> None:
    gem = "Item Class: Skill Gems\nRarity: Gem\nCyclone\n--------\nLevel: 20"
    with pytest.raises(ItemError, match="isn't supported"):
        check_item(ItemToolbox(), parse_item(gem))


def test_a_pasted_item_is_tried_on_the_attached_build(embedder, mocker) -> None:  # noqa: F811
    from contextlib import contextmanager
    from types import SimpleNamespace

    box = ItemToolbox()

    @contextmanager
    def checkout(**_kwargs):
        yield box

    mocker.patch("advisor.rag.get_pool", return_value=SimpleNamespace(toolbox=checkout))
    provider = FakeProvider(["Yes: +65 life in your free ring slot."])

    events = list(answer_stream("", provider=provider, embedder=embedder, build="eNrC", item=RING))

    types = [e["type"] for e in events]
    assert types[0] == "item" and events[0]["item"]["card"]["frame"] == "rare"
    check = next(e for e in events if e["type"] == "item_check")
    assert check["slot"] == "Ring 2"
    system, user = provider.calls[0][0][0]["content"], provider.calls[0][0][-1]["content"]
    assert "equipped it on the attached build" in system
    assert "ITEM:\n```\nItem Class: Rings" in user and '"slot": "Ring 2"' in user
    assert "Question: Is this item an upgrade for my build?" in user


def test_without_a_build_the_item_is_only_described(embedder) -> None:  # noqa: F811
    provider = FakeProvider(["A life and resistance ring."])

    events = list(
        answer_stream("", provider=provider, embedder=embedder, item=UNIQUE, use_tools=False)
    )

    assert "item_check" not in [e["type"] for e in events]
    system, user = provider.calls[0][0][0]["content"], provider.calls[0][0][-1]["content"]
    assert "wasn't tried on a build (no build is attached)" in system
    assert "Question: What is this item good for?" in user


def test_text_that_isnt_an_item_ends_the_answer(embedder) -> None:  # noqa: F811
    events = list(answer_stream("q", provider=FakeProvider(["x"]), embedder=embedder, item="hi"))

    assert events == [{"type": "error", "message": events[0]["message"]}]


def test_the_ask_endpoint_takes_an_item_without_a_question(client, mocker) -> None:
    stream = mocker.patch("advisor.views.answer_stream", return_value=iter([]))
    body = {"question": "", "item": RING, "stream": False}

    assert client.post("/api/ask/", body, content_type="application/json").status_code == 200
    assert stream.call_args.kwargs["item"] == RING
    empty = client.post("/api/ask/", {"question": ""}, content_type="application/json")
    assert empty.status_code == 400
