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
