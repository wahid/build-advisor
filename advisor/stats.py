"""Public numbers for the "How it works" page: eval scores, usage, data size.

Only aggregates: no questions, answers or anything about visitors.
"""

from __future__ import annotations

import json
from datetime import timedelta
from statistics import median
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.utils import timezone

from wiki.models import Chunk, Document

from .models import QuestionLog

CACHE_KEY = "public-stats"
CACHE_SECONDS = 300
USAGE_DAYS = 30


def eval_scores() -> dict[str, Any] | None:
    path = settings.BASE_DIR / "evals" / "results" / "latest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    summary = data.get("summary", {})
    keys = ("cases", "hit@8", "recall@8", "mrr", "pass_rate", "grounded", "relevant", "admits_gap")
    return {"meta": data.get("meta", ""), **{k: summary.get(k) for k in keys}}


def usage() -> dict[str, Any]:
    logs = QuestionLog.objects.filter(
        created_at__gte=timezone.now() - timedelta(days=USAGE_DAYS), completed=True
    )
    data = logs.aggregate(
        answers=Count("id"),
        cost=Avg("cost_usd"),
        up=Count("id", filter=Q(rating=QuestionLog.Rating.UP)),
        down=Count("id", filter=Q(rating=QuestionLog.Rating.DOWN)),
    )
    first_words = list(logs.exclude(first_token_ms=None).values_list("first_token_ms", flat=True))
    totals = list(logs.exclude(total_ms=None).values_list("total_ms", flat=True))
    rated = data["up"] + data["down"]
    return {
        "days": USAGE_DAYS,
        "answers": data["answers"],
        "median_first_word_ms": int(median(first_words)) if first_words else None,
        "median_answer_ms": int(median(totals)) if totals else None,
        "average_cost_usd": float(data["cost"]) if data["cost"] is not None else None,
        "helpful_share": round(data["up"] / rated, 3) if rated else None,
        "rated": rated,
    }


def corpus() -> dict[str, Any]:
    by_type = dict(Document.objects.values_list("doc_type").annotate(n=Count("id")))
    patches = sorted(set(Document.objects.values_list("patch", flat=True)))
    return {
        "pages": sum(by_type.values()),
        "by_type": by_type,
        "chunks": Chunk.objects.count(),
        "patch": patches[-1] if patches else "",
    }


def public_stats() -> dict[str, Any]:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    stats = {
        "evals": eval_scores(),
        "usage": usage(),
        "corpus": corpus(),
        "model": settings.LLM_MODEL,
        "web_search": bool(settings.WEB_SEARCH_ENABLED and settings.LLM_API_KEY),
    }
    cache.set(CACHE_KEY, stats, CACHE_SECONDS)
    return stats
