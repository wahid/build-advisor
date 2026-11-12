"""Record each question while its answer streams: timings, tools, tokens, cost.

Timings come from the events the client gets anyway (sources, first text,
tool calls, done), so the answer pipeline needs no extra instrumentation.
Tokens come from `llm.metering()`.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from django.conf import settings

from .llm import Usage, metering
from .models import QuestionLog
from .rag import Event

logger = logging.getLogger(__name__)

MAX_STORED_BUILD = 300
MAX_STORED_HISTORY_ANSWER = 1500


def cost(usage: Usage, web_searches: int) -> Decimal:
    uncached = max(usage.prompt_tokens - usage.cached_prompt_tokens, 0)
    dollars = (
        uncached * settings.LLM_PRICE_INPUT
        + usage.cached_prompt_tokens * settings.LLM_PRICE_CACHED_INPUT
        + usage.completion_tokens * settings.LLM_PRICE_OUTPUT
    ) / 1_000_000 + web_searches * settings.WEB_SEARCH_PRICE
    return Decimal(str(round(dollars, 6)))


class Recorder:
    """Wraps an answer's event stream and saves a QuestionLog when it ends.

    The `done` event gets the log's id, so the client can send feedback on it.
    """

    def __init__(
        self,
        question: str,
        *,
        build: str,
        doc_types: list[str],
        history: list[dict[str, str]] | None = None,
    ):
        history = history or []
        self.log = QuestionLog(
            id=uuid.uuid4(),
            question=question,
            build=build[:MAX_STORED_BUILD],
            history_turns=len(history),
            history=[
                {"question": t["question"], "answer": t["answer"][:MAX_STORED_HISTORY_ANSWER]}
                for t in history
            ],
            doc_types=doc_types,
            model=settings.LLM_MODEL,
        )
        self._tool_started: dict[str, float] = {}

    def _ms(self, since: float) -> int:
        return int((time.monotonic() - since) * 1000)

    def wrap(self, events: Iterator[Event]) -> Iterator[Event]:
        started = time.monotonic()
        log = self.log
        parts: list[str] = []
        with metering() as usage:
            try:
                for event in events:
                    kind = event["type"]
                    if kind == "rewrite":
                        log.search_terms = str(event.get("terms", ""))[:300]
                    elif kind == "sources":
                        if log.search_ms is None:
                            log.search_ms = self._ms(started)
                        log.sources = [
                            {k: s.get(k) for k in ("number", "title", "section", "url", "doc_type")}
                            for s in event["sources"]
                        ]
                    elif kind == "delta":
                        if log.first_token_ms is None and event["text"].strip():
                            log.first_token_ms = self._ms(started)
                        parts.append(event["text"])
                    elif kind == "tool_call":
                        self._tool_started[event["id"]] = time.monotonic()
                    elif kind == "tool_result":
                        began = self._tool_started.pop(event["id"], time.monotonic())
                        log.tools.append(
                            {
                                "name": event["name"],
                                "ok": event["ok"],
                                "ms": self._ms(began),
                                "error": event.get("error", "")[:300],
                            }
                        )
                    elif kind == "done":
                        log.cited = event.get("cited", [])
                        numbers = event.get("numbers") or {}
                        log.numbers_checked = min(int(numbers.get("checked", 0)), 32767)
                        log.numbers_unsupported = numbers.get("unsupported", [])[:20]
                        log.completed = True
                        event = {**event, "log_id": str(log.id)}
                    elif kind == "error":
                        log.error = str(event.get("message", ""))[:1000]
                    yield event
            finally:
                log.answer = "".join(parts)
                log.total_ms = self._ms(started)
                log.llm_calls = usage.calls
                log.prompt_tokens = usage.prompt_tokens
                log.cached_prompt_tokens = usage.cached_prompt_tokens
                log.completion_tokens = usage.completion_tokens
                log.web_searches = sum(1 for t in log.tools if t["name"] == "web_search")
                log.cost_usd = cost(usage, log.web_searches)
                self.save()

    def save(self) -> None:
        try:
            self.log.save(force_insert=True)
        except Exception:  # logging must never break an answer
            logger.exception("Couldn't save the question log")


def record(events: Iterator[Event], question: str, **context: Any) -> Iterator[Event]:
    if not settings.QUESTION_LOG_ENABLED:
        yield from events
        return
    yield from Recorder(question, **context).wrap(events)
