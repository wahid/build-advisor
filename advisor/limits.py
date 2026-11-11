"""Site-wide daily question limit, so a public demo can't run up the LLM bill.

The counter is a row per UTC day. Taking a question is one conditional UPDATE
("add one if still below the limit"), so concurrent requests from several
workers can't push it over.
"""

from __future__ import annotations

from datetime import UTC, date

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import DailyUsage


def today() -> date:
    return timezone.now().astimezone(UTC).date()


def take_question() -> bool:
    """Count one question. False when today's limit is reached (nothing counted)."""
    limit = settings.ASK_DAILY_LIMIT
    if limit <= 0:
        return True
    day = today()
    try:
        with transaction.atomic():
            DailyUsage.objects.get_or_create(date=day)
    except IntegrityError:  # another request created today's row first
        pass
    updated = DailyUsage.objects.filter(date=day, questions__lt=limit).update(
        questions=F("questions") + 1
    )
    return updated == 1


def questions_today() -> int:
    usage = DailyUsage.objects.filter(date=today()).first()
    return usage.questions if usage else 0
