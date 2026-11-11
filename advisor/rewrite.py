"""Query rewriting and routing: one quick LLM call before searching.

It does two things:
- translates the question into the wiki's own terms ("can I place something
  that casts my spells?" -> "Spell Totem Support, Totem"), which
  hybrid_search uses next to the original question;
- decides whether the question needs Path of Building. Offering the PoB
  tools costs ~10k prompt tokens and several seconds, so plain wiki
  questions are answered without them.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from .llm import LLMError, LLMProvider, Message
from .prompts import Turn, recent

logger = logging.getLogger(__name__)

MAX_TERMS = 6
MAX_CHARS = 200

REWRITE_PROMPT = """\
You prepare a Path of Exile 1 question for search. Reply with only a JSON object:
{"terms": [...], "build": true or false}

terms: at most 6 Path of Exile wiki terms the question is about (game mechanics,
skill gems, support gems, unique items, ascendancy classes), written as they
would be titled on the wiki (e.g. "Shock", "Spell Totem Support", "Endurance
charge"). Include the obvious mechanic even if the question describes it
without naming it.

build: true only if answering needs calculations on a concrete character build
in Path of Building: creating or changing a build, numbers like DPS, life, EHP
or resistances for a build, ranking gems or passives for a build, or a question
about the user's own build. False for questions about how the game works.

If earlier turns of a conversation are given, the question may be a follow-up
("and bleed?", "how do I get more of it?"). Then also add
"query": the question rewritten to stand on its own, in the user's language,
and base the terms and the build decision on that."""

MAX_CONTEXT_ANSWER_CHARS = 400  # of each earlier answer, for the rewrite only


@dataclass(frozen=True)
class Rewrite:
    terms: str = ""
    # None = unknown (rewrite failed or gave no decision): callers keep tools available.
    needs_build_tools: bool | None = None
    query: str = ""  # a follow-up rewritten to stand on its own ("" = not needed)


def parse_terms(text: str) -> str:
    """Keep a short, clean, comma-separated list whatever the model returned."""
    text = re.sub(r"<[^>]+>", " ", text)  # stray tags
    parts = re.split(r"[,\n;]+", text)
    terms: list[str] = []
    for part in parts:
        term = re.sub(r"^[\s\-*\d.)\"'\[]+|[\s\"'.\]]+$", "", part)
        if term and len(term) <= 60 and term.casefold() not in {t.casefold() for t in terms}:
            terms.append(term)
        if len(terms) == MAX_TERMS:
            break
    return ", ".join(terms)[:MAX_CHARS]


def parse_rewrite(text: str) -> Rewrite:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            terms = data.get("terms", [])
            joined = ", ".join(str(t) for t in terms) if isinstance(terms, list) else str(terms)
            build = data.get("build")
            query = data.get("query")
            return Rewrite(
                parse_terms(joined),
                build if isinstance(build, bool) else None,
                query.strip()[:500] if isinstance(query, str) else "",
            )
        except (ValueError, AttributeError):
            pass
    return Rewrite(parse_terms(text))  # plain list: terms only, no routing decision


def rewrite_question(question: str, provider: LLMProvider, history: Sequence[Turn] = ()) -> Rewrite:
    """Search terms and routing for the question; empty on failure (search still works)."""
    content = question
    if history:
        earlier = "\n\n".join(
            f"Q: {t.question}\nA: {t.answer[:MAX_CONTEXT_ANSWER_CHARS]}" for t in recent(history)
        )
        content = f"Earlier in the conversation:\n\n{earlier}\n\nQuestion: {question}"
    messages: list[Message] = [
        {"role": "system", "content": REWRITE_PROMPT},
        {"role": "user", "content": content},
    ]
    try:
        text = "".join(
            item for item in provider.stream(messages, quick=True) if isinstance(item, str)
        )
    except LLMError as exc:
        logger.warning("Query rewrite failed, searching without it: %s", exc)
        return Rewrite()
    return parse_rewrite(text)


def rewrite_query(question: str, provider: LLMProvider) -> str:
    """Just the search terms (kept for callers that don't route)."""
    return rewrite_question(question, provider).terms
