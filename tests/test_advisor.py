import json
from collections.abc import Iterator
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command

from advisor import llm
from advisor.llm import LLMError, OpenAICompatibleProvider, get_provider
from advisor.prompts import NO_SOURCES_ANSWER, build_messages
from advisor.rag import answer, answer_stream, cited_numbers
from wiki.indexing import build_chunks, embed_pending
from wiki.search import hybrid_search

from .factories import FakeEmbedder, make_document

pytestmark = pytest.mark.django_db


class FakeProvider:
    """Plays back one scripted list of stream items per round."""

    name = "fake"
    model = "fake-model"

    def __init__(self, *rounds: list, fail: bool = False) -> None:
        self.rounds = list(rounds) or [
            ["Righteous Fire burns you [1]", " and scales with life [2]."]
        ]
        self.fail = fail
        self.calls: list[tuple[list[llm.Message], list | None]] = []

    @property
    def messages(self) -> list[llm.Message]:
        return self.calls[-1][0] if self.calls else []

    def stream(self, messages: list[llm.Message], tools: list | None = None) -> Iterator:
        self.calls.append(([dict(m) for m in messages], tools))
        if self.fail:
            raise LLMError("down")
        script = self.rounds[min(len(self.calls), len(self.rounds)) - 1]
        yield from script


@pytest.fixture
def embedder() -> FakeEmbedder:
    make_document()
    make_document(
        "Chieftain",
        "The Chieftain is a Marauder ascendancy focused on fire damage and life regeneration.",
    )
    build_chunks()
    fake = FakeEmbedder()
    embed_pending(fake)
    return fake


@pytest.fixture(autouse=True)
def _clear_provider_cache() -> Iterator[None]:
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()


# --- prompts -------------------------------------------------------------------


def test_messages_number_sources_and_state_the_patch(embedder: FakeEmbedder) -> None:
    hits = hybrid_search("Righteous Fire Chieftain", embedder=embedder, top_k=3)

    system, user = build_messages("Is RF good on Chieftain?", hits)

    assert system["role"] == "system"
    assert "ONLY with information from the numbered sources" in system["content"]
    assert "game version 3.29.3c" in system["content"]
    assert user["content"].startswith("Sources:\n\n[1] ")
    assert "[3] " in user["content"]
    assert "https://" not in user["content"]  # URLs tempt the model to write links
    assert user["content"].endswith("Question: Is RF good on Chieftain?")


def test_cited_numbers_ignores_unknown_sources() -> None:
    assert cited_numbers("A [2], B [1][2], C [9], D [0]", source_count=3) == [1, 2]


# --- RAG -----------------------------------------------------------------------


def test_answer_stream_sends_sources_then_deltas_then_done(embedder: FakeEmbedder) -> None:
    provider = FakeProvider()

    events = list(answer_stream("Righteous Fire", provider=provider, embedder=embedder))

    assert [e["type"] for e in events] == ["sources", "delta", "delta", "done"]
    sources = events[0]["sources"]
    assert sources[0]["number"] == 1
    assert {"title", "section", "url", "patch", "doc_type"} <= set(sources[0])
    assert events[-1] == {"type": "done", "cited": [1, 2], "patch": "3.29.3c"}
    assert provider.messages[1]["content"].endswith("Question: Righteous Fire")


def test_answer_without_hits_does_not_call_the_llm() -> None:
    provider = FakeProvider()

    result = answer("anything", provider=provider, embedder=FakeEmbedder())

    assert result.text == NO_SOURCES_ANSWER
    assert result.sources == []
    assert provider.messages == []


def test_llm_failure_becomes_an_error_event(embedder: FakeEmbedder) -> None:
    result = answer("Righteous Fire", provider=FakeProvider(fail=True), embedder=embedder)

    assert result.error
    assert "down" not in result.error  # no internals leaked to users


# --- provider ------------------------------------------------------------------


def _chunk(text: str | None = None, tool_calls: list | None = None, reasoning: str | None = None):
    delta = SimpleNamespace(content=text, tool_calls=tool_calls, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def test_openai_compatible_provider_streams_content_only() -> None:
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        return iter([_chunk(None), SimpleNamespace(choices=[]), _chunk("Hel"), _chunk("lo")])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = OpenAICompatibleProvider(
        "deepseek", "some-model", "key", "https://x", extra_body={"a": 1}, client=client
    )

    assert "".join(provider.stream([{"role": "user", "content": "hi"}])) == "Hello"
    assert calls[0]["model"] == "some-model"
    assert calls[0]["stream"] is True
    assert calls[0]["extra_body"] == {"a": 1}


def test_provider_errors_are_wrapped() -> None:
    from openai import APIConnectionError

    def create(**kwargs):
        raise APIConnectionError(request=SimpleNamespace())  # type: ignore[arg-type]

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = OpenAICompatibleProvider("deepseek", "m", "k", "https://x", client=client)

    with pytest.raises(LLMError, match="deepseek request failed"):
        list(provider.stream([]))


def test_get_provider_uses_settings_and_default_base_url(settings) -> None:
    settings.LLM_PROVIDER = "anthropic"
    settings.LLM_MODEL = "some-claude-model"
    settings.LLM_API_KEY = "secret"
    settings.LLM_BASE_URL = ""

    provider = get_provider()

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "some-claude-model"
    assert str(provider.client.base_url).startswith("https://api.anthropic.com/v1")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"LLM_MODEL": ""}, "LLM_MODEL"),
        ({"LLM_API_KEY": ""}, "LLM_API_KEY"),
        ({"LLM_PROVIDER": "mystery", "LLM_BASE_URL": ""}, "Unknown LLM_PROVIDER"),
    ],
)
def test_get_provider_rejects_incomplete_config(settings, overrides, message) -> None:
    settings.LLM_PROVIDER = "deepseek"
    settings.LLM_MODEL = "m"
    settings.LLM_API_KEY = "k"
    for key, value in overrides.items():
        setattr(settings, key, value)

    with pytest.raises(ImproperlyConfigured, match=message):
        get_provider()


# --- API and CLI ---------------------------------------------------------------


@pytest.fixture
def wired(embedder: FakeEmbedder, mocker) -> FakeProvider:
    provider = FakeProvider()
    mocker.patch("wiki.search.get_embedder", return_value=embedder)
    mocker.patch("advisor.rag.get_provider", return_value=provider)
    return provider


def test_ask_endpoint_streams_server_sent_events(client, wired: FakeProvider) -> None:
    response = client.post(
        "/api/ask/", {"question": "Righteous Fire"}, content_type="application/json"
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    body = b"".join(response.streaming_content).decode()
    blocks = [b for b in body.split("\n\n") if b]
    assert blocks[0].startswith("event: sources\ndata: ")
    assert blocks[-1].startswith("event: done\n")
    done = json.loads(blocks[-1].split("data: ", 1)[1])
    assert done["cited"] == [1, 2]


def test_ask_endpoint_json_mode(client, wired: FakeProvider) -> None:
    response = client.post(
        "/api/ask/",
        {"question": "Righteous Fire", "stream": False, "doc_types": ["gem"]},
        content_type="application/json",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "Righteous Fire burns you [1] and scales with life [2]."
    assert data["cited"] == [1, 2]
    assert all(s["doc_type"] == "gem" for s in data["sources"])


def test_ask_endpoint_validates_input(client, wired: FakeProvider) -> None:
    response = client.post(
        "/api/ask/", {}, content_type="application/json", HTTP_ACCEPT="text/event-stream"
    )
    assert response.status_code == 400
    assert "question" in response.json()
    too_long = {"question": "x" * 501}
    assert client.post("/api/ask/", too_long, content_type="application/json").status_code == 400
    bad_type = {"question": "q", "doc_types": ["nope"]}
    assert client.post("/api/ask/", bad_type, content_type="application/json").status_code == 400


def test_ask_command_prints_answer_and_marks_cited_sources(wired: FakeProvider) -> None:
    out = StringIO()

    call_command("ask", "Righteous Fire", stdout=out)

    text = out.getvalue()
    assert "Righteous Fire burns you [1] and scales with life [2]." in text
    assert " *[1] " in text
    assert "Sources (patch 3.29.3c)" in text


def test_frontend_is_served_when_built(client, settings, tmp_path) -> None:
    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    settings.FRONTEND_DIST = tmp_path

    response = client.get("/")

    assert response.status_code == 200
    assert b"<div id=root>" in response.content


def test_frontend_explains_missing_build(client, settings, tmp_path) -> None:
    settings.FRONTEND_DIST = tmp_path / "missing"

    response = client.get("/")

    assert response.status_code == 503
    assert b"localhost:5173" in response.content
