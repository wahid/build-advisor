from datetime import timedelta
from typing import Any

import yaml
from django.contrib import admin
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .models import DailyUsage, QuestionLog


@admin.register(DailyUsage)
class DailyUsageAdmin(admin.ModelAdmin):
    list_display = ("date", "questions")


def summary(logs: Any) -> dict[str, Any]:
    """Totals for the admin header: questions, speed, tokens, cost and ratings."""
    data = logs.aggregate(
        questions=Count("id"),
        first_token_ms=Avg("first_token_ms"),
        total_ms=Avg("total_ms"),
        prompt_tokens=Sum("prompt_tokens"),
        completion_tokens=Sum("completion_tokens"),
        web_searches=Sum("web_searches"),
        cost=Sum("cost_usd"),
        up=Count("id", filter=Q(rating=QuestionLog.Rating.UP)),
        down=Count("id", filter=Q(rating=QuestionLog.Rating.DOWN)),
        errors=Count("id", filter=~Q(error="")),
    )
    count = data["questions"] or 0
    data["cost_per_question"] = (data["cost"] / count) if count and data["cost"] else None
    return data


def as_eval_cases(logs: Any) -> str:
    """YAML eval cases for evals/questions.yaml, from rated answers. The checks
    (expected sources, facts to mention) are left for a person to fill in."""
    cases = []
    for log in logs:
        case: dict[str, Any] = {
            "id": f"feedback-{str(log.id)[:8]}",
            "question": log.question,
            "category": "feedback",
            "expected_sources": [],
            "must_mention": [],
        }
        if log.history:
            case["history"] = log.history
        if log.build:
            case["build"] = log.build
        tools = sorted({t["name"] for t in log.tools if t.get("ok")})
        if tools:
            case["seen_tools"] = tools
        case["notes"] = (
            f"Rated {log.get_rating_display() or 'unrated'} on {log.created_at:%Y-%m-%d}. "
            f"Feedback: {log.feedback or '(none)'}. Answer started: {log.answer[:300]}"
        )
        cases.append(case)
    header = (
        "# Eval cases from rated answers. Fill in expected_sources and must_mention,\n"
        "# drop `notes` and `seen_tools`, and paste them into evals/questions.yaml.\n"
    )
    return header + yaml.safe_dump(cases, sort_keys=False, allow_unicode=True, width=100)


@admin.register(QuestionLog)
class QuestionLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "short_question",
        "rating",
        "first_token_ms",
        "total_ms",
        "tokens",
        "web_searches",
        "tool_count",
        "cost_usd",
        "has_error",
    )
    list_filter = ("rating", "completed", ("created_at", admin.DateFieldListFilter))
    search_fields = ("question", "answer", "feedback")
    date_hierarchy = "created_at"
    actions = ["download_eval_cases"]
    readonly_fields = [f.name for f in QuestionLog._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.display(description="Question")
    def short_question(self, log: QuestionLog) -> str:
        return log.question[:90]

    @admin.display(description="Tokens (in/out)")
    def tokens(self, log: QuestionLog) -> str:
        return f"{log.prompt_tokens:,} / {log.completion_tokens:,}"

    @admin.display(description="Tools")
    def tool_count(self, log: QuestionLog) -> int:
        return len(log.tools)

    @admin.display(description="Error", boolean=True)
    def has_error(self, log: QuestionLog) -> bool:
        return bool(log.error)

    @admin.action(description="Download as eval cases (YAML)")
    def download_eval_cases(self, request: HttpRequest, queryset: Any) -> HttpResponse:
        response = HttpResponse(as_eval_cases(queryset), content_type="text/yaml; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="feedback-cases.yaml"'
        return response

    def changelist_view(self, request: HttpRequest, extra_context: dict | None = None) -> Any:
        now = timezone.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        extra = {
            "periods": [
                ("Today", summary(QuestionLog.objects.filter(created_at__gte=today))),
                (
                    "Last 7 days",
                    summary(QuestionLog.objects.filter(created_at__gte=now - timedelta(days=7))),
                ),
            ]
        }
        return super().changelist_view(request, extra_context={**(extra_context or {}), **extra})
