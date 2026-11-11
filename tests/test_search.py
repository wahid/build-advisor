from io import StringIO

import pytest
from django.core.management import call_command

from wiki.indexing import build_chunks, embed_pending
from wiki.models import Chunk, DocumentType
from wiki.search import SearchFilters, hybrid_search, keyword_query, titles_in

from .factories import FakeEmbedder, make_document, vector_for

pytestmark = pytest.mark.django_db

LONG = " It has a lot more detail written about it on the wiki page."


@pytest.fixture
def embedder() -> FakeEmbedder:
    make_document(
        "Righteous Fire",
        "Righteous Fire is a spell that burns you and nearby enemies."
        + LONG
        + "\n\n## Recommended supports\n\nPair it with Elemental Focus and Burning Damage."
        + LONG,
    )
    make_document(
        "Cast when Damage Taken Support",
        "Cast when Damage Taken triggers supported spells after taking damage." + LONG,
    )
    make_document(
        "Chieftain",
        "The Chieftain is a Marauder ascendancy focused on fire and life regeneration." + LONG,
        doc_type=DocumentType.ASCENDANCY,
    )
    make_document("Ice", "Ice is a page with a very short title that should not match." + LONG)
    make_document("Ice Nova", "Ice Nova is a cold spell that hits enemies around you." + LONG)
    build_chunks()
    fake = FakeEmbedder()
    embed_pending(fake)
    return fake


def _aim_at(embedder: FakeEmbedder, title: str) -> Chunk:
    chunk = Chunk.objects.filter(document__title=title).first()
    assert chunk is not None
    embedder.query_vector = vector_for(chunk.text)
    return chunk


def test_vector_list_finds_semantically_closest_chunk(embedder: FakeEmbedder) -> None:
    target = _aim_at(embedder, "Ice Nova")

    hits = hybrid_search("what hits enemies around me with frost", embedder=embedder)

    vector_top = [h for h in hits if h.ranks.get("vector") == 1]
    assert [h.chunk for h in vector_top] == [target]


def test_keyword_list_finds_exact_names(embedder: FakeEmbedder) -> None:
    _aim_at(embedder, "Ice Nova")  # vector points elsewhere on purpose

    hits = hybrid_search("damage taken trigger", embedder=embedder)

    cwdt = next(h for h in hits if h.title == "Cast when Damage Taken Support")
    assert cwdt.ranks["keyword"] == 1


def test_title_list_boosts_pages_named_in_the_question(embedder: FakeEmbedder) -> None:
    _aim_at(embedder, "Ice Nova")

    hits = hybrid_search("Which supports for Righteous Fire Chieftain?", embedder=embedder)

    titled = {h.title for h in hits if "title" in h.ranks}
    assert titled == {"Righteous Fire", "Chieftain"}
    assert hits[0].title in titled  # in two or three lists beats one list


def test_short_titles_are_not_matched_inside_words() -> None:
    make_document("Ice")
    make_document("Ice Nova")

    assert list(titles_in("How does ice nova scale?").values_list("title", flat=True)) == [
        "Ice Nova"
    ]


def test_max_chunks_per_document(embedder: FakeEmbedder) -> None:
    _aim_at(embedder, "Righteous Fire")

    hits = hybrid_search("Righteous Fire", embedder=embedder, max_per_document=1)

    titles = [h.title for h in hits]
    assert len(titles) == len(set(titles))


def test_filters_by_document_type(embedder: FakeEmbedder) -> None:
    _aim_at(embedder, "Righteous Fire")

    hits = hybrid_search(
        "fire", embedder=embedder, filters=SearchFilters(doc_types=(DocumentType.ASCENDANCY,))
    )

    assert {h.title for h in hits} == {"Chieftain"}


def test_top_k_limits_results(embedder: FakeEmbedder) -> None:
    assert len(hybrid_search("fire spell", embedder=embedder, top_k=2)) == 2


def test_keyword_query_handles_punctuation_only() -> None:
    assert keyword_query("???") is None
    query = keyword_query("Cast when Damage Taken — Chieftain's best?")
    assert query is not None
    raw = query.get_source_expressions()[-1].value
    assert raw == "cast | when | damage | taken | chieftains | best"


def test_search_command_prints_hits(embedder: FakeEmbedder, mocker) -> None:
    mocker.patch("wiki.search.get_embedder", return_value=embedder)
    _aim_at(embedder, "Chieftain")
    out = StringIO()

    call_command("search", "Chieftain fire", "-k", "3", stdout=out)

    output = out.getvalue()
    assert "1. " in output
    assert "https://wiki.test/wiki/Chieftain" in output
    assert "title #1" in output


def test_common_words_are_dropped_from_keyword_query(embedder: FakeEmbedder) -> None:
    from wiki.search import informative_words

    for i in range(12):
        make_document(f"Filler Support {i}", f"Filler support gem number {i}." + LONG)
    build_chunks()
    base = Chunk.objects.all()

    words = informative_words(base, ["which", "support", "gem", "righteous", "chieftain"])

    # "which" is a stop word; "support" and "gem" appear in most chunks.
    assert words == ["righteous", "chieftain"]


def test_rarest_words_are_kept_even_if_common(embedder: FakeEmbedder) -> None:
    from wiki.search import informative_words

    base = Chunk.objects.all()

    assert informative_words(base, ["is", "a", "spell"]) == ["spell"]


def test_every_named_page_gets_a_top_title_rank(embedder: FakeEmbedder) -> None:
    long_page = "\n\n".join(
        f"## Section {i}\n\nRighteous Fire detail number {i}." + LONG for i in range(8)
    )
    make_document("Righteous Fire Long", long_page)
    build_chunks()
    embed_pending(embedder)
    _aim_at(embedder, "Righteous Fire Long")

    hits = hybrid_search("Righteous Fire Long for Chieftain", embedder=embedder, top_k=8)

    chieftain = next(h for h in hits if h.title == "Chieftain")
    assert chieftain.ranks["title"] <= 3


def test_generic_one_word_titles_dont_count_as_named(embedder: FakeEmbedder, monkeypatch) -> None:
    monkeypatch.setattr("wiki.search.GENERIC_TITLE_MIN_CHUNKS", 3)  # tiny test corpus
    make_document("Fire", "Fire is a damage type. Fire spells deal fire damage." + LONG)
    for i in range(8):
        make_document(f"Fire Skill {i}", f"Fire skill number {i} deals fire damage." + LONG)
    build_chunks()
    embed_pending(embedder)
    _aim_at(embedder, "Ice Nova")

    hits = hybrid_search("Does Righteous Fire work with fire?", embedder=embedder, top_k=8)

    titled = {h.title for h in hits if "title" in h.ranks}
    assert "Righteous Fire" in titled
    assert "Fire" not in titled  # "fire" is in most chunks: not a meaningful match


def test_intro_of_a_found_page_is_included(embedder: FakeEmbedder) -> None:
    sections = "\n\n".join(f"## Detail {i}\n\nFreeze detail number {i}." + LONG for i in range(6))
    make_document("Freeze", "Freeze stops the enemy from acting." + LONG + "\n\n" + sections)
    build_chunks()
    embed_pending(embedder)
    detail = Chunk.objects.get(document__title="Freeze", section="Detail 4")
    embedder.query_vector = vector_for(detail.text)  # the question matches a later section

    hits = hybrid_search("what does it do?", embedder=embedder, top_k=4)

    intro = next(h for h in hits if h.chunk.document.title == "Freeze" and h.chunk.section == "")
    assert "intro" in intro.ranks


def test_pinned_titles_come_first_in_order(embedder: FakeEmbedder) -> None:
    _aim_at(embedder, "Ice Nova")

    hits = hybrid_search(
        "is this strong?",
        embedder=embedder,
        pinned=["chieftain", "Righteous Fire", "Not A Page", "Cast when Damage Taken"],
        top_k=4,
    )

    titles = ["Chieftain", "Righteous Fire", "Cast when Damage Taken Support"]
    assert [h.title for h in hits[:3]] == titles  # supports match without the suffix
    assert all(h.chunk.section == "" for h in hits[:3])
    assert hits[0].ranks["pinned"] == 1
    assert len(hits) == 4


def test_pinned_titles_take_at_most_half_the_results(embedder: FakeEmbedder) -> None:
    pinned = ["Ice", "Ice Nova", "Chieftain", "Righteous Fire"]

    hits = hybrid_search("cold", embedder=embedder, pinned=pinned, top_k=2)

    assert sum("pinned" in h.ranks for h in hits) == 2  # top_k // 2 + 1


def test_a_title_inside_a_longer_named_title_is_not_counted(embedder: FakeEmbedder) -> None:
    make_document("Tornado", "Tornado is a spell that creates a moving whirlwind." + LONG)
    make_document("Tornado Shot", "Tornado Shot fires an arrow that splits into more." + LONG)
    build_chunks()
    embed_pending(embedder)
    _aim_at(embedder, "Chieftain")

    hits = hybrid_search("Is Tornado Shot good?", embedder=embedder)

    assert {h.title for h in hits if "title" in h.ranks} == {"Tornado Shot"}


@pytest.fixture
def listing_pages(embedder: FakeEmbedder) -> FakeEmbedder:
    make_document(
        "Poison",
        "Poison is an ailment that deals chaos damage over time."
        + LONG
        + "\n\n## Mechanics\n\nEvery poison on an enemy deals its damage at the same time."
        + LONG
        + "\n\n## Related passive skills\n\nPoison chance, poison damage and poison duration."
        + LONG,
        doc_type=DocumentType.MECHANIC,
    )
    build_chunks()
    embed_pending(embedder)
    return embedder


def _rank_of(hits, section: str) -> int:
    return next(i for i, h in enumerate(hits) if h.title == "Poison" and h.chunk.section == section)


def test_reference_lists_count_for_less(listing_pages: FakeEmbedder) -> None:
    listing = Chunk.objects.get(document__title="Poison", section="Related passive skills")
    listing_pages.query_vector = vector_for(listing.text)  # vector prefers the list

    hits = hybrid_search("how does poison damage work", embedder=listing_pages, top_k=20)

    assert _rank_of(hits, "Mechanics") < _rank_of(hits, "Related passive skills")


def test_reference_lists_count_fully_when_asked_for(listing_pages: FakeEmbedder) -> None:
    listing = Chunk.objects.get(document__title="Poison", section="Related passive skills")
    listing_pages.query_vector = vector_for(listing.text)

    hits = hybrid_search("which passives give poison chance", embedder=listing_pages, top_k=20)

    assert _rank_of(hits, "Related passive skills") < _rank_of(hits, "Mechanics")
