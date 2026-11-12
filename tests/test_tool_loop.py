"""The RAG loop with Path of Building tools (fake LLM, fake toolbox)."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from advisor import gemrank, passives
from advisor.llm import OpenAICompatibleProvider, Reasoning, ToolCall
from advisor.pob import PobToolError, PobUnavailable, ToolResult
from advisor.rag import MAX_TOOL_RESULT_CHARS, answer, answer_stream
from wiki.indexing import build_chunks, embed_pending

from .factories import FakeEmbedder, make_document
from .test_advisor import FakeProvider, _chunk

pytestmark = pytest.mark.django_db

SUMMARY = {"ascendancy": "Chieftain", "mainSkill": "Righteous Fire", "stats": {"Life": 6200}}


class FakeToolbox:
    definitions = [
        {"type": "function", "function": {"name": n, "parameters": {}}}
        for n in ("get_build_summary", "export_build", "load_build", "rank_support_gems")
    ]

    def __init__(self, results: dict | None = None, reused: bool = False) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []
        self.reused = reused
        self.loaded = ""

    def mark_loaded(self, source: str) -> None:
        self.loaded = source

    def call(self, name: str, arguments: dict) -> ToolResult:
        self.calls.append((name, arguments))
        if name == "load_build" and arguments.get("source") == "bad":
            raise PobToolError("Only Path of Building share codes can be loaded.")
        result = self.results.get(name, SUMMARY)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(ok=True, text=json.dumps(result), data=result)


@pytest.fixture
def embedder() -> FakeEmbedder:
    make_document()
    build_chunks()
    fake = FakeEmbedder()
    embed_pending(fake)
    return fake


@pytest.fixture
def toolbox(mocker, settings) -> FakeToolbox:
    box = FakeToolbox()

    @contextmanager
    def checkout(**_kwargs):
        yield box

    mocker.patch("advisor.rag.get_pool", return_value=SimpleNamespace(toolbox=checkout))
    settings.POB_MAX_TOOL_ROUNDS = 3
    return box


def _types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def test_model_calls_a_tool_and_answers_with_the_result(embedder, toolbox) -> None:
    provider = FakeProvider(
        ["Let me check.", ToolCall("c1", "get_build_summary", "{}")],
        ["Your build has 6200 life according to Path of Building."],
    )

    events = list(answer_stream("How much life?", provider=provider, embedder=embedder))

    assert _types(events) == [
        "sources",
        "delta",
        "tool_call",
        "tool_result",
        "delta",
        "delta",
        "done",
    ]
    assert events[2] == {
        "type": "tool_call",
        "id": "c1",
        "name": "get_build_summary",
        "arguments": {},
    }
    assert events[3]["ok"] is True
    # Second request carries the assistant tool call and the tool result.
    messages, tools = provider.calls[1]
    assert messages[-2]["tool_calls"][0]["function"]["name"] == "get_build_summary"
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": json.dumps(SUMMARY)}
    assert tools == [*FakeToolbox.definitions, gemrank.TOOL_DEFINITION, passives.TOOL_DEFINITION]
    assert "Path of Building tools" in messages[0]["content"]


def test_last_round_has_no_tools_and_says_so(embedder, toolbox) -> None:
    provider = FakeProvider(
        [ToolCall("a", "get_build_summary", "{}")],
        [ToolCall("b", "get_build_summary", "{}")],
        [ToolCall("c", "get_build_summary", "{}")],
        ["Final answer."],
    )

    result = answer("q", provider=provider, embedder=embedder)

    assert [tools is None for _, tools in provider.calls] == [False, False, False, True]
    assert len(toolbox.calls) == 3
    assert result.text == "Final answer."
    assert provider.calls[-1][0][-1]["content"].startswith("You have used all your tool calls")


def test_invalid_arguments_and_rejected_calls_go_back_to_the_model(embedder, toolbox) -> None:
    provider = FakeProvider(
        [
            ToolCall("x", "rank_support_gems", "{not json"),
            ToolCall("y", "load_build", '{"source": "bad"}'),
        ],
        ["Sorry, that didn't work."],
    )

    events = list(answer_stream("q", provider=provider, embedder=embedder))

    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["ok"] for r in results] == [False, False]
    tool_messages = [m for m in provider.calls[1][0] if m["role"] == "tool"]
    assert tool_messages[0]["content"].startswith("Invalid JSON arguments")
    assert "share codes" in tool_messages[1]["content"]
    assert toolbox.calls == [("load_build", {"source": "bad"})]


def test_export_is_sent_to_the_client_not_the_model(embedder, toolbox) -> None:
    toolbox.results["export_build"] = {"code": "eNrFXN9z4jgS"}
    provider = FakeProvider([ToolCall("e", "export_build", "{}")], ["Done, the code is below."])

    events = list(answer_stream("make a build", provider=provider, embedder=embedder))

    assert {"type": "pob_export", "code": "eNrFXN9z4jgS"} in events
    tool_message = provider.calls[1][0][-1]
    assert "eNrFXN9z4jgS" not in tool_message["content"]


def test_long_tool_results_are_truncated_for_the_model(embedder, toolbox) -> None:
    toolbox.results["get_build_summary"] = ToolResult(
        ok=True, text="x" * (MAX_TOOL_RESULT_CHARS + 50)
    )
    provider = FakeProvider([ToolCall("c", "get_build_summary", "{}")], ["ok"])

    list(answer_stream("q", provider=provider, embedder=embedder))

    content = provider.calls[1][0][-1]["content"]
    assert len(content) < MAX_TOOL_RESULT_CHARS + 100
    assert content.endswith("ask for fewer stats)")


def test_reasoning_is_sent_back_with_tool_calls(embedder, toolbox) -> None:
    provider = FakeProvider(
        [Reasoning("I should load the summary."), ToolCall("c", "get_build_summary", "{}")],
        ["ok"],
    )

    list(answer_stream("q", provider=provider, embedder=embedder))

    assistant = provider.calls[1][0][-2]
    assert assistant["reasoning_content"] == "I should load the summary."
    assert assistant["content"] is None


def test_attached_build_is_loaded_before_the_model_runs(embedder, toolbox) -> None:
    provider = FakeProvider(["Your Chieftain has 6200 life."])

    events = list(answer_stream("q", provider=provider, embedder=embedder, build="eNrCODE"))

    assert toolbox.calls[:2] == [("load_build", {"source": "eNrCODE"}), ("get_build_summary", {})]
    assert [e["type"] for e in events[:3]] == ["tool_call", "tool_result", "sources"]
    assert events[0]["name"] == "load_build"
    system = provider.calls[0][0][0]["content"]
    assert "already loaded" in system
    assert '"ascendancy": "Chieftain"' in system


def test_attached_build_steers_the_wiki_search(embedder, toolbox, mocker) -> None:
    toolbox.results["get_skills"] = {
        "groups": [
            {"isMain": False, "gems": [{"name": "Frenzy", "enabled": True}]},
            {
                "isMain": True,
                "gems": [
                    {"name": "Righteous Fire", "enabled": True},
                    {"name": "Burning Damage", "enabled": True},
                    {"name": "Chain", "enabled": False},
                ],
            },
        ]
    }
    toolbox.results["get_items"] = {
        "items": [
            {"name": "New Item, Spine Bow", "rarity": "RARE"},
            {"name": "Darkray Vectors, Dragonscale Boots", "rarity": "UNIQUE"},
        ]
    }
    search = mocker.patch("advisor.rag.hybrid_search", return_value=[])

    list(
        answer_stream(
            "is this strong?", provider=FakeProvider(["ok"]), embedder=embedder, build="eNrCODE"
        )
    )

    expected = ["Righteous Fire", "Chieftain", "Darkray Vectors", "Burning Damage"]
    assert search.call_args.kwargs["pinned"] == expected
    assert search.call_args.args[0] == "is this strong?\n" + ", ".join(expected)


def test_a_build_still_loaded_from_the_last_question_isnt_loaded_again(embedder, toolbox) -> None:
    toolbox.reused = True

    events = list(
        answer_stream("q", provider=FakeProvider(["ok"]), embedder=embedder, build="eNrC")
    )

    assert ("load_build", {"source": "eNrC"}) not in toolbox.calls
    assert events[0] == {
        "type": "tool_call",
        "id": "attached-build",
        "name": "reuse_build",
        "arguments": {},
    }


def test_a_loaded_build_is_remembered(embedder, toolbox) -> None:
    list(answer_stream("q", provider=FakeProvider(["ok"]), embedder=embedder, build="eNrC"))

    assert toolbox.loaded == "eNrC"


def test_attached_build_that_fails_to_load_stops_with_an_error(embedder, toolbox) -> None:
    provider = FakeProvider(["never"])

    result = answer("q", provider=provider, embedder=embedder, build="bad")

    assert "couldn't be loaded" in result.error
    assert provider.calls == []


def test_without_pob_an_attached_build_is_an_error(embedder) -> None:
    result = answer("q", provider=FakeProvider(), embedder=embedder, build="eNrCODE")

    assert "isn't available" in result.error


def test_busy_pool_falls_back_to_wiki_only(embedder, mocker) -> None:
    @contextmanager
    def busy(**_kwargs):
        raise PobUnavailable("busy")
        yield

    mocker.patch("advisor.rag.get_pool", return_value=SimpleNamespace(toolbox=busy))
    provider = FakeProvider(["Wiki-only answer [1]."])

    result = answer("q", provider=provider, embedder=embedder)

    assert result.text == "Wiki-only answer [1]."
    assert provider.calls[0][1] is None


def test_provider_assembles_streamed_tool_calls() -> None:
    def part(index, id=None, name=None, arguments=None):
        return SimpleNamespace(
            index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments)
        )

    chunks = [
        _chunk(reasoning="think "),
        _chunk(reasoning="more"),
        _chunk(tool_calls=[part(0, id="call_a", name="rank_support_gems", arguments='{"gro')]),
        _chunk(
            tool_calls=[part(0, arguments='up": 1}'), part(1, id="call_b", name="export_build")]
        ),
    ]
    sent: list[dict] = []

    def create(**kwargs):
        sent.append(kwargs)
        return iter(chunks)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = OpenAICompatibleProvider("deepseek", "m", "k", "https://x", client=client)
    tools = [{"type": "function", "function": {"name": "export_build"}}]

    items = list(provider.stream([], tools))

    assert items == [
        Reasoning("think more"),
        ToolCall("call_a", "rank_support_gems", '{"group": 1}'),
        ToolCall("call_b", "export_build", "{}"),
    ]
    assert sent[0]["tools"] == tools


def test_ask_endpoint_passes_an_attached_build(client, embedder, toolbox, mocker) -> None:
    mocker.patch("wiki.search.get_embedder", return_value=embedder)
    mocker.patch("advisor.rag.get_provider", return_value=FakeProvider(["Loaded."]))

    response = client.post(
        "/api/ask/",
        {"question": "How tanky is this?", "build": "eNrCODE", "stream": False},
        content_type="application/json",
    )

    assert response.status_code == 200
    tool = response.json()["tools"][0]
    assert (tool["name"], tool["ok"]) == ("load_build", True)
    assert '"ascendancy": "Chieftain"' in tool["preview"]
    assert toolbox.calls[0] == ("load_build", {"source": "eNrCODE"})


def test_ask_command_shows_tool_calls_and_the_export(embedder, toolbox, mocker) -> None:
    from io import StringIO

    from django.core.management import call_command

    toolbox.results["export_build"] = {"code": "eNrEXPORT"}
    mocker.patch("wiki.search.get_embedder", return_value=embedder)
    mocker.patch(
        "advisor.rag.get_provider",
        return_value=FakeProvider([ToolCall("e", "export_build", "{}")], ["Here it is."]),
    )
    out, err = StringIO(), StringIO()

    call_command("ask", "make a build", stdout=out, stderr=err)

    assert "[PoB] export_build()" in err.getvalue()
    assert "Path of Building code:\neNrEXPORT" in out.getvalue()


def test_empty_final_answer_gets_one_more_turn(embedder, toolbox) -> None:
    provider = FakeProvider(
        [ToolCall("c", "get_build_summary", "{}")],
        [],  # the model ends without text
        ["Your build has 6200 life according to Path of Building."],
    )

    result = answer("How much life?", provider=provider, embedder=embedder)

    assert result.text == "Your build has 6200 life according to Path of Building."
    last_messages, tools = provider.calls[-1]
    assert tools is None
    assert last_messages[-1]["content"].startswith("Write your final answer")


def test_leaked_tool_markup_is_removed_and_the_model_asked_again(embedder, toolbox) -> None:
    provider = FakeProvider(
        ["I'll build this.", ToolCall("c", "get_build_summary", "{}")],
        ["<", "\uff5c\uff5cDSML\uff5c\uff5c calls>", '<invoke name="get_stats">'],
        ["It has 6200 life."],
    )

    result = answer("q", provider=provider, embedder=embedder)

    assert "DSML" not in result.text and "invoke" not in result.text
    assert result.text.endswith("It has 6200 life.")
    assert provider.calls[-1][0][-1]["content"].startswith("Write your final answer")


def test_changed_build_is_exported_even_if_the_model_forgets(embedder, toolbox) -> None:
    toolbox.results["new_build"] = {"ascendancy": "Chieftain"}
    toolbox.results["export_build"] = {"code": "eNrAUTO"}
    provider = FakeProvider([ToolCall("n", "new_build", "{}")], ["Here is your Chieftain."])

    events = list(answer_stream("make a build", provider=provider, embedder=embedder))

    assert {"type": "pob_export", "code": "eNrAUTO"} in events
    assert toolbox.calls[-1] == ("export_build", {})


def test_reading_a_build_doesnt_trigger_an_export(embedder, toolbox) -> None:
    provider = FakeProvider([ToolCall("s", "get_build_summary", "{}")], ["6200 life."])

    list(answer_stream("q", provider=provider, embedder=embedder))

    assert [name for name, _ in toolbox.calls] == ["get_build_summary"]


def test_quick_calls_add_the_quick_request_options() -> None:
    sent: list[dict] = []

    def create(**kwargs):
        sent.append(kwargs)
        return iter([_chunk("ok")])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = OpenAICompatibleProvider(
        "deepseek",
        "m",
        "k",
        "https://x",
        extra_body={"user_tag": "a"},
        quick_extra_body={"thinking": {"type": "disabled"}},
        client=client,
    )

    list(provider.stream([]))
    list(provider.stream([], quick=True))

    assert sent[0]["extra_body"] == {"user_tag": "a"}
    assert sent[1]["extra_body"] == {"user_tag": "a", "thinking": {"type": "disabled"}}
