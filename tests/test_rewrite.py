import pytest

from advisor.llm import LLMError
from advisor.rag import answer_stream
from advisor.rewrite import parse_terms, rewrite_query
from wiki.indexing import build_chunks, embed_pending
from wiki.search import hybrid_search

from .factories import FakeEmbedder, make_document
from .test_advisor import FakeProvider

LONG = " It has a lot more detail written about it on the wiki page."


def test_parse_terms_cleans_model_output() -> None:
    raw = 'Totem, Spell Totem Support\n- Ancestral Warchief; 1. "Ignite".'
    assert parse_terms(raw) == "Totem, Spell Totem Support, Ancestral Warchief, Ignite"


def test_parse_terms_dedupes_and_limits() -> None:
    raw = "Shock, shock, A, B, C, D, E, F, G"
    assert parse_terms(raw) == "Shock, A, B, C, D, E"


def test_rewrite_failure_means_no_terms() -> None:
    assert rewrite_query("q", FakeProvider(fail=True)) == ""


def test_rewrite_sends_the_question() -> None:
    provider = FakeProvider(["Totem, Spell Totem Support"])

    assert rewrite_query("Can something cast for me?", provider) == "Totem, Spell Totem Support"
    assert provider.calls[0][0][1] == {"role": "user", "content": "Can something cast for me?"}
    assert provider.calls[0][1] is None  # no tools


@pytest.fixture
def embedder() -> FakeEmbedder:
    make_document(
        "Totem", "A totem is an immobile summoned object that uses a skill for you." + LONG
    )
    make_document("Ground effect", "Ground effects cover an area on the ground." + LONG)
    build_chunks()
    fake = FakeEmbedder()
    embed_pending(fake)
    return fake


@pytest.mark.django_db
def test_expansion_finds_pages_the_question_never_names(embedder: FakeEmbedder) -> None:
    question = "Can I place something on the ground that uses my spells?"

    plain = hybrid_search(question, embedder=embedder, top_k=8)
    expanded = hybrid_search(question, embedder=embedder, top_k=8, expansion="Totem")

    assert not any("title" in h.ranks and h.title == "Totem" for h in plain)
    totem = next(h for h in expanded if h.title == "Totem")
    assert "title" in totem.ranks
    assert all(
        "rewrite" in h.ranks or "vector" in h.ranks or "keyword" in h.ranks or "title" in h.ranks
        for h in expanded
    )


@pytest.mark.django_db
def test_answer_stream_rewrites_when_asked(embedder: FakeEmbedder) -> None:
    provider = FakeProvider(["Totem"], ["A totem uses skills for you [1]."])

    events = list(
        answer_stream(
            "Can something cast for me?", provider=provider, embedder=embedder, rewrite=True
        )
    )

    assert events[0] == {"type": "rewrite", "terms": "Totem"}
    assert events[1]["type"] == "sources"
    assert events[1]["sources"][0]["title"] == "Totem"
    assert len(provider.calls) == 2  # rewrite + answer


@pytest.mark.django_db
def test_rewrite_is_off_by_default(embedder: FakeEmbedder, settings) -> None:
    settings.SEARCH_QUERY_REWRITE = False
    provider = FakeProvider(["answer [1]."])

    events = list(answer_stream("q", provider=provider, embedder=embedder))

    assert events[0]["type"] == "sources"
    assert len(provider.calls) == 1


def test_llm_error_type_is_caught() -> None:
    class Broken:
        name = "x"
        model = "y"

        def stream(self, messages, tools=None):
            raise LLMError("down")
            yield

    assert rewrite_query("q", Broken()) == ""


@pytest.mark.django_db
def test_given_expansion_skips_the_rewrite_call(embedder: FakeEmbedder) -> None:
    provider = FakeProvider(["A totem uses skills for you [1]."])

    events = list(
        answer_stream("q", provider=provider, embedder=embedder, expansion="Totem", rewrite=True)
    )

    assert events[0] == {"type": "rewrite", "terms": "Totem"}
    assert len(provider.calls) == 1  # only the answer
