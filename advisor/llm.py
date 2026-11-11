"""Provider-independent access to chat LLMs.

Everything goes through `LLMProvider`. DeepSeek, OpenAI and Anthropic all
offer an OpenAI-compatible chat API, so one implementation covers them; the
provider is picked with `LLM_PROVIDER`, and model, key and base URL come
from settings. Model names are never hardcoded.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# OpenAI chat format: {"role": ..., "content": ...}, plus tool_calls / tool_call_id.
Message = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """The model asks for a tool; `arguments` is the raw JSON string it produced."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Reasoning:
    """Thinking text from reasoning models. Not shown to users, but some
    providers (DeepSeek) want it sent back alongside tool results."""

    text: str


StreamItem = str | ToolCall | Reasoning


class LLMError(RuntimeError):
    """The LLM provider failed (network, auth, rate limit, ...)."""


class LLMProvider(Protocol):
    name: str
    model: str

    def stream(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> Iterator[StreamItem]:
        """Yield answer text in pieces; after the text, any tool calls (and reasoning)."""
        ...


# Default base URLs for the OpenAI-compatible endpoints; LLM_BASE_URL overrides.
BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1/",
}


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        model: str,
        api_key: str,
        base_url: str,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 60.0,
        extra_body: dict[str, Any] | None = None,
        client: Any = None,
    ) -> None:
        self.name = name
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = extra_body or {}
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=2)
        self.client = client

    def stream(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> Iterator[StreamItem]:
        from openai import OpenAIError

        options: dict[str, Any] = {}
        if tools:
            options["tools"] = tools
        calls: dict[int, dict[str, str]] = {}
        reasoning: list[str] = []
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
                extra_body=self.extra_body or None,
                **options,
            )
            for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                thinking = getattr(delta, "reasoning_content", None)
                if thinking:
                    reasoning.append(thinking)
                if delta.content:
                    yield delta.content
                # Tool calls arrive in pieces, keyed by index.
                for part in delta.tool_calls or []:
                    call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                    if part.id:
                        call["id"] = part.id
                    if part.function and part.function.name:
                        call["name"] += part.function.name
                    if part.function and part.function.arguments:
                        call["arguments"] += part.function.arguments
        except OpenAIError as exc:
            raise LLMError(f"{self.name} request failed: {exc}") from exc

        if reasoning:
            yield Reasoning("".join(reasoning))
        for index in sorted(calls):
            call = calls[index]
            yield ToolCall(call["id"] or f"call_{index}", call["name"], call["arguments"] or "{}")


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider:
    name = settings.LLM_PROVIDER
    if name not in BASE_URLS and not settings.LLM_BASE_URL:
        raise ImproperlyConfigured(
            f"Unknown LLM_PROVIDER {name!r}; use one of {sorted(BASE_URLS)} or set LLM_BASE_URL."
        )
    if not settings.LLM_MODEL:
        raise ImproperlyConfigured("Set LLM_MODEL to the model name of your provider.")
    if not settings.LLM_API_KEY:
        raise ImproperlyConfigured("Set LLM_API_KEY.")
    return OpenAICompatibleProvider(
        name=name,
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL or BASE_URLS[name],
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
        timeout=settings.LLM_TIMEOUT,
        extra_body=settings.LLM_EXTRA_BODY,
    )
