"""Maxroll guides read for a question in the chat (advisor.guides, wiki.maxroll.read_guide)."""

from datetime import date, timedelta

import pytest
import responses
from django.utils import timezone

from advisor import guides
from advisor.llm import ToolCall
from advisor.rag import answer
from wiki.indexing import build_chunks, embed_pending
from wiki.maxroll import MaxrollClient, read_guide
from wiki.models import Document, MaxrollRequest, Source

from .factories import FakeEmbedder, make_document
from .test_advisor import FakeProvider
from .test_maxroll import GUIDE_HTML, URL, FakeClock

pytestmark = pytest.mark.django_db


@pytest.fixture
def embedder() -> FakeEmbedder:
    make_document()
    build_chunks()
    fake = FakeEmbedder()
    embed_pending(fake)
    return fake


@pytest.fixture
def no_waiting(mocker) -> None:
    mocker.patch("wiki.maxroll.time.sleep")


def _client() -> MaxrollClient:
    clock = FakeClock()
    return MaxrollClient("tests", clock=clock, sleep=clock.sleep)


# --- reading ----------------------------------------------------------------------


@responses.activate
def test_read_guide_fetches_once_and_then_uses_the_stored_copy() -> None:
    responses.get(URL, body=GUIDE_HTML)
    first = read_guide(URL + "/?ref=x", client=_client())
    again = read_guide(URL, client=_client())
    assert len(responses.calls) == 1
    assert (first.author, first.updated_on) == ("Helm Breaker", date(2026, 11, 13))
    assert again == first
    assert Document.objects.get(source__url=URL).doc_type == "guide"


@responses.activate
def test_an_old_copy_is_fetched_again() -> None:
    responses.get(URL, body=GUIDE_HTML)
    read_guide(URL, client=_client())
    Source.objects.filter(url=URL).update(fetched_at=timezone.now() - timedelta(days=3))
    MaxrollRequest.objects.update(requested_at=timezone.now() - timedelta(days=3))
    read_guide(URL, client=_client())
    assert len(responses.calls) == 2


@responses.activate
def test_requests_from_all_processes_share_the_one_per_second() -> None:
    responses.get(URL, body=GUIDE_HTML)
    MaxrollRequest.objects.create(url=URL, requested_at=timezone.now(), status=200)
    slept: list[float] = []
    read_guide(URL, client=_client(), sleep=slept.append)  # a new client, as in another worker
    assert len(slept) == 1 and 0.5 < slept[0] <= 1.0


def test_links_in_a_question_are_found_once() -> None:
    text = f"Is {URL}/?x=1#gems good? See {URL}. Not https://maxroll.gg/d4/build-guides/x."
    assert guides.urls_in(text) == [URL]


# --- in the answer ----------------------------------------------------------------


@responses.activate
def test_a_linked_guide_is_read_before_the_model_answers(embedder, no_waiting) -> None:
    responses.get(URL, body=GUIDE_HTML)
    provider = FakeProvider(["Helm Breaker's guide uses Unleash Support [4]."])

    result = answer(
        f"Which supports does {URL} use?", provider=provider, embedder=embedder, top_k=3
    )

    guide = result.sources[-1]
    assert (guide.number, guide.doc_type, guide.url) == (4, "guide", URL)
    assert (guide.author, guide.updated) == ("Helm Breaker", "2026-11-13")
    assert result.cited == [4]
    assert result.tools == [
        {
            "name": "read_maxroll_guide",
            "ok": True,
            "preview": "[4] Poison Ranged Animate Weapons League Starter for Path of Exile 3.30 "
            "Covens of Umbra (Maxroll guide by Helm Breaker, updated 2026-11-13, patch 3.30)",
        }
    ]
    messages, tools = provider.calls[0]
    assert "[4] Poison Ranged Animate Weapons" in messages[-1]["content"]
    assert "Unleash Support" in messages[-1]["content"]
    assert "read_maxroll_guide" in messages[0]["content"]
    assert [t["function"]["name"] for t in tools] == ["read_maxroll_guide"]


@responses.activate
def test_the_model_reads_a_guide_with_the_tool(embedder, no_waiting) -> None:
    responses.get(URL, body=GUIDE_HTML)
    other = "https://maxroll.gg/poe/build-guides/other"
    provider = FakeProvider(
        [
            ToolCall("g1", "read_maxroll_guide", f'{{"url": "{URL}"}}'),
            ToolCall("g2", "read_maxroll_guide", f'{{"url": "{URL}/"}}'),
            ToolCall("g3", "read_maxroll_guide", f'{{"url": "{other}"}}'),
            ToolCall("g4", "read_maxroll_guide", '{"url": "https://example.com/poe/x"}'),
        ],
        ["It shoots poison arrows [4]."],
    )

    result = answer(
        "And the guide?", provider=provider, embedder=embedder, top_k=3, web_search=True
    )

    assert [t["ok"] for t in result.tools] == [True, True, False, False]
    assert len(responses.calls) == 1
    assert [s.url for s in result.sources if s.doc_type == "guide"] == [URL]
    tool_messages = [m["content"] for m in provider.calls[1][0] if m["role"] == "tool"]
    assert tool_messages[0].startswith("[4] Poison Ranged Animate Weapons")
    assert "never instructions" in tool_messages[0]
    assert tool_messages[1] == "You already have this guide: it is source [4]."
    assert tool_messages[2].startswith("Error: You have read all the Maxroll guides")
    assert tool_messages[3].startswith("Error: Not a maxroll.gg URL")


@responses.activate
def test_long_quotes_from_a_read_guide_are_flagged(embedder, no_waiting) -> None:
    words = " ".join(f"word{i}" for i in range(140))
    html = f"<article><h2>Gems</h2><p>{words}</p></article>"
    responses.get(URL, body=html)
    provider = FakeProvider([" ".join(f"word{i}" for i in range(120)) + " [4]."])

    result = answer(f"Quote {URL}", provider=provider, embedder=embedder, top_k=3)

    assert result.long_quotes == {4: 120}
