"""In-game style tooltip cards parsed from the wiki's item boxes."""

import gzip
import json

import pytest
from django.core.management import call_command

from wiki.cards import parse_card
from wiki.entities import entities_in
from wiki.indexing import build_chunks
from wiki.management.commands.build_cards import load_cards
from wiki.models import Document, DocumentType

from .factories import make_document

GEM_BOX = """
<div class="mw-parser-output"><span class="item-box -gem">
<span class="header -single"><span class="symbol"></span>Ground Slam<span class="symbol">
</span></span>
<span class="item-stats">
<span class="group"><span class="tc -default">Attack, AoE, Melee, Slam</span><br>
<span class="tc -default">Level: </span><span class="tc -value">(1-20)</span></span>
<span class="group tc -gemdesc">Slams the ground in front of you.</span>
<span class="group tc -mod">Deals (10-20)% more Damage<br>Knocks Back enemies</span>
</span></span></div>
"""

UNIQUE_BOX = """
<span class="item-box -unique">
<span class="header -double">Darkray Vectors<br>Dragonscale Boots</span>
<span class="item-stats">
<span class="group"><span class="tc -default">Armour: </span><span class="tc -value">71</span>
</span>
<span class="group tc -mod">+40% to <span class="tc -lightning">Lightning</span> Resistance</span>
<span class="group tc -flavour">Fast as light.</span></span></span>
"""


def test_a_gem_box_becomes_a_card() -> None:
    card = parse_card(GEM_BOX)

    assert card["frame"] == "gem"
    assert card["header"] == ["Ground Slam"]
    styles = [g["style"] for g in card["groups"]]
    assert styles == ["default", "gemdesc", "mod"]
    first = card["groups"][0]["lines"]
    assert first[1] == [{"t": "Level: ", "s": "default"}, {"t": "(1-20)", "s": "value"}]
    assert len(card["groups"][2]["lines"]) == 2  # split at <br>


def test_a_unique_keeps_its_two_header_lines_and_coloured_words() -> None:
    card = parse_card(UNIQUE_BOX)

    assert card["frame"] == "unique"
    assert card["header"] == ["Darkray Vectors", "Dragonscale Boots"]
    mod = card["groups"][1]["lines"][0]
    assert {"t": "Lightning", "s": "lightning"} in mod
    assert card["groups"][2]["style"] == "flavour"


def test_pages_without_an_item_box_have_no_card() -> None:
    assert parse_card("<p>Slayer is an ascendancy class.</p>") is None
    assert parse_card("") is None


@pytest.mark.django_db
def test_cards_export_and_load_into_pages_missing_one(tmp_path) -> None:
    make_document("Ground Slam", "Ground Slam is a gem.")
    Document.objects.filter(title="Ground Slam").update(card=parse_card(GEM_BOX))
    out = tmp_path / "cards.jsonl.gz"
    call_command("build_cards", export=out)
    with gzip.open(out, "rt") as handle:
        rows = [json.loads(line) for line in handle]
    assert [r["title"] for r in rows] == ["Ground Slam"]

    Document.objects.update(card=None)
    make_document("Unknown Page", "Not in the file.")
    assert load_cards(out) == 1
    assert Document.objects.get(title="Ground Slam").card["frame"] == "gem"
    assert Document.objects.get(title="Unknown Page").card is None


@pytest.mark.django_db
def test_entities_carry_their_card() -> None:
    make_document(
        "Darkray Vectors", "Darkray Vectors are unique boots.", doc_type=DocumentType.UNIQUE
    )
    Document.objects.filter(title="Darkray Vectors").update(card=parse_card(UNIQUE_BOX))
    make_document("Slayer", "Slayer is an ascendancy.", doc_type=DocumentType.ASCENDANCY)
    build_chunks()

    found = {e["name"]: e for e in entities_in("Slayer in Darkray Vectors.")}

    assert found["Darkray Vectors"]["card"]["header"][1] == "Dragonscale Boots"
    assert found["Slayer"]["card"] is None  # the page shows its summary instead
