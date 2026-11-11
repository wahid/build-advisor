"""Follow-up questions: earlier turns reach the rewrite, the search and the model."""

import pytest

from advisor.prompts import MAX_HISTORY_TURNS, Turn, build_messages
from advisor.rag import answer
from advisor.rewrite import parse_rewrite, rewrite_question
from wiki.indexing import build_chunks, embed_pending

from .factories import FakeEmbedder, make_document
from .test_advisor import FakeProvider

HISTORY = [Turn("How does poison stack?", "Every poison deals its own damage [1][2].")]


def test_earlier_turns_come_before_the_question_without_their_citations() -> None:
    messages = build_messages("And bleed?", [], history=HISTORY)

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "How does poison stack?"
    assert messages[2]["content"] == "Every poison deals its own damage."
    assert messages[3]["content"].endswith("Question: And bleed?")
    assert "follow-up" in messages[0]["content"]


def test_only_recent_turns_are_kept() -> None:
    history = [Turn(f"q{i}", f"a{i}") for i in range(MAX_HISTORY_TURNS + 3)]

    messages = build_messages("next", [], history=history)

    assert len(messages) == 2 + 2 * MAX_HISTORY_TURNS
    assert messages[1]["content"] == "q3"


def test_a_question_without_history_has_no_follow_up_note() -> None:
    system = build_messages("q", [])[0]["content"]

    assert "follow-up" not in system


def test_rewrite_reads_the_standalone_query() -> None:
    reply = '{"terms": ["Bleeding"], "build": false, "query": "How do multiple bleeds stack?"}'

    assert parse_rewrite(reply).query == "How do multiple bleeds stack?"
    assert parse_rewrite('{"terms": ["Bleeding"], "build": false}').query == ""


def test_rewrite_sees_the_conversation() -> None:
    provider = FakeProvider(['{"terms": ["Bleeding"], "build": false, "query": "q"}'])

    rewrite_question("And bleed?", provider, HISTORY)

    content = provider.calls[0][0][1]["content"]
    assert "Q: How does poison stack?" in content
    assert content.endswith("Question: And bleed?")


@pytest.fixture
def embedder(db) -> FakeEmbedder:
    make_document()
    build_chunks()
    fake = FakeEmbedder()
    embed_pending(fake)
    return fake


@pytest.mark.django_db
def test_follow_up_searches_for_the_standalone_question(embedder, mocker) -> None:
    search = mocker.patch("advisor.rag.hybrid_search", return_value=[])
    provider = FakeProvider(
        ['{"terms": ["Bleeding"], "build": false, "query": "How do bleeds stack?"}'],
        ["Only the strongest bleed deals damage."],
    )

    answer("And bleed?", provider=provider, embedder=embedder, rewrite=True, history=HISTORY)

    assert search.call_args.args[0] == "How do bleeds stack?"


@pytest.mark.django_db
def test_follow_up_without_rewrite_searches_with_the_previous_question(embedder, mocker) -> None:
    search = mocker.patch("advisor.rag.hybrid_search", return_value=[])

    answer(
        "And bleed?",
        provider=FakeProvider(),
        embedder=embedder,
        rewrite=False,
        use_tools=False,
        history=HISTORY,
    )

    assert search.call_args.args[0] == "How does poison stack?\nAnd bleed?"


@pytest.mark.django_db
def test_ask_endpoint_passes_history_to_the_model(client, embedder, mocker, settings) -> None:
    settings.SEARCH_QUERY_REWRITE = False
    provider = FakeProvider(["Bleed is different [1]."])
    mocker.patch("advisor.rag.get_provider", return_value=provider)
    mocker.patch("advisor.rag.get_embedder", return_value=embedder, create=True)
    mocker.patch("wiki.search.get_embedder", return_value=embedder)
    mocker.patch("advisor.rag.get_pool", return_value=None)
    body = {
        "question": "And bleed?",
        "stream": False,
        "history": [{"question": "How does poison stack?", "answer": "Each poison counts [1]."}],
    }

    response = client.post("/api/ask/", body, content_type="application/json")

    assert response.status_code == 200
    assert provider.calls[-1][0][1] == {"role": "user", "content": "How does poison stack?"}


@pytest.mark.django_db
def test_ask_endpoint_validates_history(client) -> None:
    bad = {"question": "q", "history": [{"question": "x" * 501, "answer": ""}]}

    assert client.post("/api/ask/", bad, content_type="application/json").status_code == 400
