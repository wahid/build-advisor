"""Query rewriting: translate a question into the wiki's own terms.

Users ask "can I place something that casts my spells for me?"; the wiki page
is called "Totem". A short LLM call turns the question into likely page names
and terms, which hybrid_search uses next to the original question.
"""

from __future__ import annotations

import logging
import re

from .llm import LLMError, LLMProvider, Message

logger = logging.getLogger(__name__)

MAX_TERMS = 6
MAX_CHARS = 200

REWRITE_PROMPT = """\
You turn a Path of Exile 1 question into search terms for the Path of Exile wiki.
Return only a comma-separated list of at most 6 terms: the game mechanics, skill
gems, support gems, unique items or ascendancy classes the question is about,
written as they would be titled on the wiki (e.g. "Shock", "Spell Totem Support",
"Endurance charge"). Include the obvious mechanic even if the question describes
it without naming it. No explanations, no numbering."""


def parse_terms(text: str) -> str:
    """Keep a short, clean, comma-separated list whatever the model returned."""
    text = re.sub(r"<[^>]+>", " ", text)  # stray tags
    parts = re.split(r"[,\n;]+", text)
    terms: list[str] = []
    for part in parts:
        term = re.sub(r"^[\s\-*\d.)\"']+|[\s\"'.]+$", "", part)
        if term and len(term) <= 60 and term.casefold() not in {t.casefold() for t in terms}:
            terms.append(term)
        if len(terms) == MAX_TERMS:
            break
    return ", ".join(terms)[:MAX_CHARS]


def rewrite_query(question: str, provider: LLMProvider) -> str:
    """Wiki terms for the question, or "" if the model fails (search still works)."""
    messages: list[Message] = [
        {"role": "system", "content": REWRITE_PROMPT},
        {"role": "user", "content": question},
    ]
    try:
        text = "".join(item for item in provider.stream(messages) if isinstance(item, str))
    except LLMError as exc:
        logger.warning("Query rewrite failed, searching without it: %s", exc)
        return ""
    return parse_terms(text)
