"""Game names in answers, for hover cards."""

import pytest

from wiki.entities import entities_in, summarize
from wiki.indexing import build_chunks
from wiki.models import DocumentType

from .factories import make_document

pytestmark = pytest.mark.django_db


@pytest.fixture
def pages():
    make_document(
        "Tornado Shot", "Tornado Shot\n\nTornado Shot\nAttack, Bow, Projectile. Fires an arrow."
    )
    make_document("Tornado", "Tornado is a spell that creates a whirlwind.")
    make_document(
        "Darkray Vectors", "Darkray Vectors are unique boots.", doc_type=DocumentType.UNIQUE
    )
    make_document("Poison", "Poison is an ailment.", doc_type=DocumentType.MECHANIC)
    make_document(
        "Point Blank Support", "Point Blank Support\n\nSupport, Projectile. More damage up close."
    )
    build_chunks()


def test_known_gems_and_items_are_found(pages) -> None:
    found = entities_in("Tornado Shot with Darkray Vectors applies poison and Poison.")

    by_name = {e["name"]: e for e in found}
    assert set(by_name) == {"Tornado Shot", "Darkray Vectors"}  # no mechanics, no "Tornado"
    assert by_name["Tornado Shot"]["summary"].startswith("Attack, Bow, Projectile")
    assert by_name["Darkray Vectors"]["doc_type"] == "unique"
    assert by_name["Darkray Vectors"]["url"].endswith("/Darkray_Vectors")


def test_names_must_appear_as_written(pages) -> None:
    assert entities_in("tornado shot in lower case") == []
    assert entities_in("") == []


def test_summaries_drop_the_repeated_title_and_are_cut_at_a_word() -> None:
    assert summarize("Sunder", "Sunder\n\nSunder  Slams the ground.") == "Slams the ground."
    long = summarize("X", "X " + "word " * 100)
    assert long.endswith("…") and len(long) <= 262


def test_support_gems_are_found_without_the_support_suffix(pages) -> None:
    [entity] = entities_in("Link Point Blank for close targets.")

    assert entity["name"] == "Point Blank"  # as the answer writes it
    assert entity["title"] == "Point Blank Support"
    assert entity["summary"].startswith("Support, Projectile")
    assert entities_in("Use Point Blank Support.")[0]["name"] == "Point Blank Support"


def test_a_support_name_inside_a_longer_one_doesnt_count() -> None:
    make_document("Multiple Projectiles Support", "Support, Projectile.")
    make_document("Greater Multiple Projectiles Support", "Support, Projectile. More arrows.")
    build_chunks()

    names = [e["name"] for e in entities_in("Link Greater Multiple Projectiles.")]

    assert names == ["Greater Multiple Projectiles"]
