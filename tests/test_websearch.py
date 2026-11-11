"""Web search via DeepSeek's Search API, as a tool in the answer loop."""

import pytest

from advisor import websearch
from advisor.llm import ToolCall
from advisor.rag import answer
from wiki.indexing import build_chunks, embed_pending

from .factories import FakeEmbedder, make_document
from .test_advisor import FakeProvider

RESULTS = {
    "results": [
        {
            "title": "3.29 Patch Notes",
            "url": "https://www.pathofexile.com/forum/view-thread/1",
            "site_name": "Path of Exile",
            "date": "2026-10-30T12:00:00Z",
            "summary": "Righteous Fire now deals 10% more damage.",
        },
        {"title": "Spam", "url": "https://spam.example/poe", "summary": "buy currency"},
        {"title": "Guide", "url": "https://maxroll.gg/poe/rf?_gl=x#top", "summary": "RF guide."},
        {"title": "Japanese", "url": "https://jp.pathofexile.com/forum/view-thread/1"},
        {"title": "Guide again", "url": "https://maxroll.gg/poe/rf/", "summary": "duplicate"},
    ]
}


@pytest.fixture
def web(settings, mocker):
    settings.WEB_SEARCH_ENABLED = True
    settings.LLM_API_KEY = "test-key"
    response = mocker.Mock(status_code=200, text="")
    response.json.return_value = RESULTS
    return mocker.patch("advisor.websearch.requests.post", return_value=response)


def test_only_allowed_sites_are_kept(web) -> None:
    results = websearch.search("rf patch notes", "Was RF buffed?")

    assert [r.url for r in results] == [
        "https://www.pathofexile.com/forum/view-thread/1",
        "https://maxroll.gg/poe/rf",
    ]
    assert results[0].site == "Path of Exile"
    assert results[0].date == "2026-10-30"
    sent = web.call_args.kwargs
    assert sent["json"]["query"] == "rf patch notes"
    assert sent["json"]["ori_question"] == "Was RF buffed?"
    assert sent["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://www.reddit.com/r/pathofexile/x", True),
        ("https://poewiki.net/wiki/Poison", True),
        ("https://notpoewiki.net/x", False),
        ("https://poewiki.net.evil.example/x", False),
    ],
)
def test_allowed_matches_sites_and_subdomains(url, ok) -> None:
    assert websearch.allowed(url, ["poewiki.net", "reddit.com"]) is ok


def test_a_failed_search_is_reported_to_the_model(web) -> None:
    web.return_value.status_code = 402

    with pytest.raises(websearch.WebSearchError, match="402"):
        websearch.search("q")


def test_search_is_off_for_other_providers(settings) -> None:
    settings.WEB_SEARCH_ENABLED = False
    settings.LLM_API_KEY = "key"

    assert websearch.enabled() is False


@pytest.fixture
def embedder(db) -> FakeEmbedder:
    make_document()
    build_chunks()
    fake = FakeEmbedder()
    embed_pending(fake)
    return fake


@pytest.mark.django_db
def test_web_results_become_numbered_sources(web, embedder) -> None:
    provider = FakeProvider(
        [ToolCall("w1", "web_search", '{"query": "rf 3.29 patch notes"}')],
        ["RF got 10% more damage in 3.29 [4]."],
    )

    result = answer("Was RF buffed this league?", provider=provider, embedder=embedder, top_k=3)

    web_sources = [s for s in result.sources if s.doc_type == "web"]
    assert [s.number for s in web_sources] == [4, 5]
    assert web_sources[0].section == "Path of Exile, 2026-10-30"
    assert result.cited == [4]
    tools = provider.calls[0][1]
    assert [t["function"]["name"] for t in tools] == ["web_search"]
    tool_message = provider.calls[1][0][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["content"].startswith("Web results (page text written by others")
    assert "[4] 3.29 Patch Notes (Path of Exile, 2026-10-30)" in tool_message["content"]
    assert "web_search" in provider.calls[0][0][0]["content"]


@pytest.mark.django_db
def test_without_web_search_no_tools_are_offered(settings, embedder) -> None:
    provider = FakeProvider(["Answer [1]."])

    answer("q", provider=provider, embedder=embedder, web_search=False)

    assert provider.calls[0][1] is None


@pytest.mark.django_db
def test_web_searches_are_limited(web, embedder, settings) -> None:
    settings.WEB_SEARCH_MAX_CALLS = 1
    provider = FakeProvider(
        [ToolCall("a", "web_search", '{"query": "one"}')],
        [ToolCall("b", "web_search", '{"query": "two"}')],
        ["Final answer."],
    )

    result = answer("q", provider=provider, embedder=embedder)

    assert web.call_count == 1
    assert provider.calls[1][1] is None  # last round: no tools, and its call is ignored
    assert result.error == ""


def test_pages_already_found_are_skipped(web) -> None:
    results = websearch.search("q", skip_urls={"https://maxroll.gg/poe/rf"})

    assert [r.url for r in results] == ["https://www.pathofexile.com/forum/view-thread/1"]


@pytest.mark.django_db
def test_web_searches_are_limited_with_pob_tools_too(web, embedder, settings, mocker) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace

    from .test_tool_loop import FakeToolbox

    @contextmanager
    def checkout():
        yield FakeToolbox()

    mocker.patch("advisor.rag.get_pool", return_value=SimpleNamespace(toolbox=checkout))
    settings.WEB_SEARCH_MAX_CALLS = 2
    provider = FakeProvider(
        [ToolCall("a", "web_search", '{"query": "one"}')],
        [ToolCall("b", "web_search", '{"query": "two"}')],
        [ToolCall("c", "web_search", '{"query": "three"}')],
        ["Done."],
    )

    result = answer("q", provider=provider, embedder=embedder, use_tools=True)

    assert web.call_count == 2
    assert [t["ok"] for t in result.tools] == [True, True, False]
