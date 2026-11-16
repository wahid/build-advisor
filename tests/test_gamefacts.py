"""Simple game facts in answers are checked against Path of Building's data."""

import pytest

from advisor.gamefacts import check, load

LEVELS = {"Cyclone": 28, "Brutality Support": 38}


def wrong(answer: str) -> list[str]:
    return [w["fact"] for w in check(answer, levels=LEVELS)["wrong"]]


def test_the_shipped_data_knows_weapons_and_gems() -> None:
    facts = load()

    assert facts["weapons"]["Siege Axe"] == "One Handed Axe"
    assert facts["weapons"]["Vaal Axe"] == "Two Handed Axe"
    assert "Attack" in facts["gems"]["Cyclone"]["tags"]


def test_wrong_handedness_is_flagged() -> None:
    assert wrong("Your Siege Axe is a two-handed weapon, so skip Sleight of Hand.") == [
        "Siege Axe is a one-handed axe."
    ]
    assert wrong("A Vaal Axe is one-handed.") == ["Vaal Axe is a two-handed axe."]
    assert wrong("A Thicket Bow is a 1h weapon.") == ["Thicket Bow is a bow, which is two-handed."]


def test_right_and_unclear_statements_pass() -> None:
    for answer in (
        "Your Siege Axe is one-handed, so Sleight of Hand applies.",
        "The Vaal Axe is a two-handed axe.",
        "Skip Butchery (two-handed only) while you're on a Siege Axe, isn't it?",
        "Use a Siege Axe instead of a two-handed weapon.",
        "A Siege Axe or a two-handed Vaal Axe both work.",
        "Sleight of Hand needs a one-handed weapon.",
    ):
        assert wrong(answer) == [], answer


def test_attack_and_spell_claims_use_the_gems_tags() -> None:
    assert wrong("Cyclone is a channelled spell that hits around you.") == [
        "Cyclone is tagged Attack, not spell."
    ]
    assert wrong("Fireball is an attack.") == ["Fireball is tagged Spell, not attack."]
    assert wrong("Cyclone is a channelling attack. Fireball is a spell.") == []
    assert wrong("Cyclone is not a spell.") == []


def test_a_wrong_required_level_is_flagged() -> None:
    assert wrong("Cyclone requires level 34, so level with something else first.") == [
        "Cyclone requires level 28, not 34."
    ]
    assert wrong("Cyclone requires level 28. Brutality Support needs level 38.") == []


@pytest.mark.django_db
def test_the_done_event_carries_the_fact_check(mocker) -> None:
    from advisor.rag import answer_stream
    from wiki.indexing import build_chunks, embed_pending

    from .factories import FakeEmbedder, make_document
    from .test_advisor import FakeProvider

    make_document()
    build_chunks()
    embedder = FakeEmbedder()
    embed_pending(embedder)
    provider = FakeProvider(["A Vaal Axe is one-handed."])

    events = list(answer_stream("q", provider=provider, embedder=embedder, use_tools=False))

    assert events[-1]["facts"]["wrong"][0]["text"] == "Vaal Axe"
