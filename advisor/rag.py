"""Retrieval-augmented answering, optionally with Path of Building tools.

`answer_stream` yields events so callers (the SSE endpoint, the CLI) can show
sources first and then the answer as it streams in:

    {"type": "sources", "sources": [...]}
    {"type": "tool_call", "id": ..., "name": ..., "arguments": {...}}   (tools only)
    {"type": "tool_result", "id": ..., "name": ..., "ok": bool, "error": str}
    {"type": "pob_export", "code": "..."}                               (build exported)
    {"type": "delta", "text": "..."}            (repeated)
    {"type": "done", "cited": [1, 3], "patch": "3.29.3c"}
    {"type": "error", "message": "..."}         (instead of done, on failure)
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from typing import Any

from django.conf import settings

from wiki.embeddings import Embedder
from wiki.search import SearchFilters, SearchHit, hybrid_search

from .llm import LLMError, LLMProvider, Message, Reasoning, ToolCall, get_provider
from .pob import PobToolbox, PobToolError, PobUnavailable, get_pool
from .prompts import NO_SOURCES_ANSWER, build_messages
from .rewrite import rewrite_query

logger = logging.getLogger(__name__)

CITATION_RE = re.compile(r"\[(\d+)\]")
MAX_TOOL_RESULT_CHARS = 8000  # per tool result sent back to the model
MAX_EVENT_ARGUMENT_CHARS = 300  # per argument value shown to the user
FINAL_ANSWER_NUDGE = (
    "Write your final answer to my question now, based on the sources and tool results above."
)
OUT_OF_ROUNDS = (
    "You have used all your tool calls. Don't call any more tools: write your final answer "
    "to my question now, based on the sources and tool results above. If you changed the "
    "build, the app exports it and shows the share code below your answer, so say that."
)
TOOL_PREVIEW_CHARS = 1500  # of each tool result, for clients and the eval judge
# Tools that change the loaded build; if any ran and nothing was exported, export at the end.
MODIFYING_TOOLS = {"new_build", "apply_changes", "auto_allocate_passives", "fix_gaps"}
# DeepSeek's own tool-call markup ("<｜｜DSML｜｜ ...", "<｜tool▁calls▁begin｜>") can leak
# into the text when it wants a tool it wasn't offered.
MARKUP_START = "<\uff5c"


class _MarkupFilter:
    """Drops model-internal markup from streamed text, even when split across chunks."""

    def __init__(self) -> None:
        self._held = ""
        self._dropping = False

    def feed(self, text: str) -> str:
        if self._dropping:
            return ""
        text = self._held + text
        self._held = ""
        start = text.find(MARKUP_START)
        if start != -1:
            self._dropping = True
            return text[:start]
        # Hold back a trailing "<" that might be the start of markup.
        if text.endswith(MARKUP_START[0]):
            self._held = text[-1]
            return text[:-1]
        return text

    def flush(self) -> str:
        held, self._held = self._held, ""
        return "" if self._dropping else held


Event = dict[str, Any]


@dataclass(frozen=True)
class Source:
    number: int
    title: str
    section: str
    url: str
    patch: str
    doc_type: str

    @classmethod
    def from_hit(cls, number: int, hit: SearchHit) -> Source:
        chunk = hit.chunk
        return cls(number, hit.title, chunk.section, chunk.url, chunk.patch, chunk.doc_type)


@dataclass
class Answer:
    text: str = ""
    sources: list[Source] = field(default_factory=list)
    cited: list[int] = field(default_factory=list)
    patch: str = ""
    error: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    pob_export: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def cited_numbers(text: str, source_count: int) -> list[int]:
    return sorted({n for n in map(int, CITATION_RE.findall(text)) if 1 <= n <= source_count})


def _shorten(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_EVENT_ARGUMENT_CHARS:
        return value[:MAX_EVENT_ARGUMENT_CHARS] + "…"
    if isinstance(value, dict):
        return {k: _shorten(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten(v) for v in value[:20]]
    return value


def _for_model(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n… (result truncated; ask for fewer stats)"


class _ToolRunner:
    """Runs one round of tool calls and records them for the conversation."""

    def __init__(self, toolbox: PobToolbox) -> None:
        self.toolbox = toolbox

    def run(self, call: ToolCall) -> tuple[list[Event], str]:
        """Return (events for the client, text for the model)."""
        try:
            arguments = json.loads(call.arguments or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as exc:
            arguments = {}
            error = f"Invalid JSON arguments: {exc}"
            return self._events(call, arguments, ok=False, error=error), error

        started = time.monotonic()
        try:
            result = self.toolbox.call(call.name, arguments)
        except PobToolError as exc:
            logger.info("tool %s rejected: %s", call.name, exc)
            return self._events(call, arguments, ok=False, error=str(exc)), f"Error: {exc}"
        elapsed = time.monotonic() - started
        logger.info(
            "tool %s(%s) -> %s in %.1fs",
            call.name,
            json.dumps(_shorten(arguments))[:500],
            "ok" if result.ok else "error",
            elapsed,
        )
        events = self._events(call, arguments, ok=result.ok, error="" if result.ok else result.text)
        events[1]["preview"] = result.text[:TOOL_PREVIEW_CHARS]
        if result.ok and call.name == "export_build" and isinstance(result.data, dict):
            code = result.data.get("code")
            if code:
                events.append({"type": "pob_export", "code": code})
                return events, "Exported. The app shows the share code to the user."
        return events, _for_model(result.text)

    @staticmethod
    def _events(call: ToolCall, arguments: dict[str, Any], ok: bool, error: str) -> list[Event]:
        return [
            {
                "type": "tool_call",
                "id": call.id,
                "name": call.name,
                "arguments": _shorten(arguments),
            },
            {
                "type": "tool_result",
                "id": call.id,
                "name": call.name,
                "ok": ok,
                "error": error[:500],
            },
        ]


def answer_stream(
    question: str,
    filters: SearchFilters | None = None,
    provider: LLMProvider | None = None,
    embedder: Embedder | None = None,
    top_k: int | None = None,
    build: str = "",
    use_tools: bool = True,
    rewrite: bool | None = None,
    expansion: str | None = None,
) -> Iterator[Event]:
    """`expansion` passes search terms that were already worked out (skips rewriting)."""
    if expansion is None:
        expansion = ""
        if settings.SEARCH_QUERY_REWRITE if rewrite is None else rewrite:
            provider = provider or get_provider()
            expansion = rewrite_query(question, provider)
    if expansion:
        yield {"type": "rewrite", "terms": expansion}
    hits = hybrid_search(
        question, top_k=top_k, filters=filters, embedder=embedder, expansion=expansion
    )
    sources = [Source.from_hit(n, hit) for n, hit in enumerate(hits, start=1)]
    yield {"type": "sources", "sources": [asdict(s) for s in sources]}
    patch = ", ".join(sorted({s.patch for s in sources}))

    pool = get_pool() if use_tools else None
    if build and pool is None:
        yield {
            "type": "error",
            "message": "Path of Building isn't available, so builds can't be loaded.",
        }
        return
    if not hits and pool is None:
        yield {"type": "delta", "text": NO_SOURCES_ANSWER}
        yield {"type": "done", "cited": [], "patch": patch}
        return

    with ExitStack() as stack:
        toolbox: PobToolbox | None = None
        if pool is not None:
            try:
                toolbox = stack.enter_context(pool.toolbox())
            except PobUnavailable as exc:
                logger.warning("Answering without Path of Building: %s", exc)
                if build:
                    yield {"type": "error", "message": f"{exc} Try again in a minute."}
                    return

        build_summary = None
        if build and toolbox is not None:
            runner = _ToolRunner(toolbox)
            call = ToolCall("attached-build", "load_build", json.dumps({"source": build}))
            events, _ = runner.run(call)
            yield from events
            if not events[-1]["ok"]:
                yield {
                    "type": "error",
                    "message": f"The build couldn't be loaded: {events[-1]['error']}",
                }
                return
            build_summary = toolbox.call("get_build_summary", {}).data

        yield from _converse(question, hits, sources, patch, provider, toolbox, build_summary)


def _converse(
    question: str,
    hits: list[SearchHit],
    sources: list[Source],
    patch: str,
    provider: LLMProvider | None,
    toolbox: PobToolbox | None,
    build_summary: dict[str, Any] | None,
) -> Iterator[Event]:
    provider = provider or get_provider()
    rounds = settings.POB_MAX_TOOL_ROUNDS if toolbox is not None else 0
    messages: list[Message] = build_messages(question, hits, rounds, build_summary)
    runner = _ToolRunner(toolbox) if toolbox is not None else None
    answer_parts: list[str] = []

    final_text = ""
    changed = exported = False
    try:
        for round_number in range(rounds + 1):
            last_round = round_number == rounds
            # The last round gets no tools, so the model has to answer.
            tools = toolbox.definitions if toolbox is not None and not last_round else None
            if toolbox is not None and rounds and last_round:
                messages.append({"role": "user", "content": OUT_OF_ROUNDS})
            text: list[str] = []
            calls: list[ToolCall] = []
            reasoning = ""
            markup = _MarkupFilter()
            for item in provider.stream(messages, tools):
                if isinstance(item, ToolCall):
                    calls.append(item)
                elif isinstance(item, Reasoning):
                    reasoning = item.text
                elif clean := markup.feed(item):
                    text.append(clean)
                    yield {"type": "delta", "text": clean}
            if tail := markup.flush():
                text.append(tail)
                yield {"type": "delta", "text": tail}
            final_text = "".join(text)
            answer_parts.extend(text)
            if not calls or runner is None:
                break

            assistant: Message = {
                "role": "assistant",
                "content": final_text or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in calls
                ],
            }
            if reasoning:
                assistant["reasoning_content"] = reasoning
            messages.append(assistant)
            for call in calls:
                events, result = runner.run(call)
                changed |= call.name in MODIFYING_TOOLS and events[1]["ok"]
                exported |= any(e["type"] == "pob_export" for e in events)
                yield from events
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            final_text = ""
            if text:
                answer_parts.append("\n\n")
                yield {"type": "delta", "text": "\n\n"}

        if not final_text.strip():
            # Reasoning models sometimes end a tool session without a final answer.
            messages.append({"role": "user", "content": FINAL_ANSWER_NUDGE})
            markup = _MarkupFilter()
            for item in provider.stream(messages, None):
                if isinstance(item, str) and (clean := markup.feed(item)):
                    answer_parts.append(clean)
                    yield {"type": "delta", "text": clean}
            if tail := markup.flush():
                answer_parts.append(tail)
                yield {"type": "delta", "text": tail}

        if runner is not None and changed and not exported:
            # The model changed the build but didn't export it: give the user the code anyway.
            events, _ = runner.run(ToolCall("auto-export", "export_build", "{}"))
            yield from events
    except LLMError as exc:
        logger.error("LLM failed for %r: %s", question, exc)
        yield {"type": "error", "message": "The language model is unavailable. Try again later."}
        return
    except PobUnavailable as exc:
        logger.error("Path of Building failed for %r: %s", question, exc)
        yield {"type": "error", "message": "Path of Building stopped working. Try again later."}
        return

    full = "".join(answer_parts)
    logger.debug(
        "Answered %r with %s/%s: %d chars", question, provider.name, provider.model, len(full)
    )
    yield {"type": "done", "cited": cited_numbers(full, len(sources)), "patch": patch}


def answer(question: str, **kwargs: Any) -> Answer:
    """Non-streaming convenience wrapper around `answer_stream`."""
    result = Answer()
    for event in answer_stream(question, **kwargs):
        match event["type"]:
            case "sources":
                result.sources = [Source(**s) for s in event["sources"]]
            case "delta":
                result.text += event["text"]
            case "tool_result":
                result.tools.append(
                    {"name": event["name"], "ok": event["ok"], "preview": event.get("preview", "")}
                )
            case "pob_export":
                result.pob_export = event["code"]
            case "done":
                result.cited = event["cited"]
                result.patch = event["patch"]
            case "error":
                result.error = event["message"]
    return result
