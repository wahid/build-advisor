"""Sharing a conversation as a read-only public page.

The app sends the log ids of the chat's answers (it got one with each answer);
the shared copy is built here from the question log. So nobody can publish text
of their own on this site through a share link: only real questions with the
answers the app gave to them.
"""

from __future__ import annotations

import secrets
from typing import Any

from wiki.entities import entities_in

from .models import QuestionLog, SharedChat

MAX_TURNS = 30
TITLE_CHARS = 100


class ShareError(ValueError):
    pass


def _turn(log: QuestionLog) -> dict[str, Any]:
    sources = [{"patch": "", **source} for source in log.sources]
    return {
        "question": log.question,
        "answer": log.answer,
        "sources": sources,
        "cited": log.cited,
        "patch": next((s["patch"] for s in sources if s.get("patch")), ""),
        "entities": entities_in(log.answer),
    }


def create(log_ids: list[str]) -> SharedChat:
    """Publish the answers with these log ids, in the given order."""
    ids = list(dict.fromkeys(str(i) for i in log_ids))[:MAX_TURNS]
    logs = {str(log.id): log for log in QuestionLog.objects.filter(id__in=ids, completed=True)}
    turns = [_turn(logs[i]) for i in ids if i in logs and logs[i].answer.strip()]
    if not turns:
        raise ShareError("There are no finished answers in this chat to share.")
    title = " ".join(turns[0]["question"].split())
    if len(title) > TITLE_CHARS:
        title = title[: TITLE_CHARS - 1] + "…"
    return SharedChat.objects.create(
        slug=secrets.token_urlsafe(8),
        delete_key=secrets.token_urlsafe(18),
        title=title or "Shared chat",
        turns=turns,
    )


def public(chat: SharedChat) -> dict[str, Any]:
    return {
        "slug": chat.slug,
        "title": chat.title,
        "created_at": chat.created_at.isoformat(),
        "turns": chat.turns,
    }
