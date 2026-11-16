"""A report on answers that went wrong, grouped by the most likely cause.

"Went wrong" means: rated not helpful, ended in an error, or flagged by the
number or fact checks. The cause is worked out from what the log already holds
(errors, failed tools, missing citations, flagged numbers), so the report costs
nothing to make; `feedback_report --classify` also asks the model to read the
unexplained ones. The point is to turn bad answers into fixes and eval cases.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from .llm import LLMError, LLMProvider, Message
from .models import QuestionLog

CAUSES = {
    "error": "Ended in an error",
    "tool_failed": "A tool call failed",
    "wrong_facts": "Contradicts Path of Building's data",
    "unsupported_numbers": "Numbers not found in the sources",
    "no_answer_in_wiki": "The wiki didn't have the answer",
    "uncited": "Answered without citing a source",
    "slow": "Took over a minute",
    "wrong_page": "Wrong or missing wiki page (model's reading)",
    "misunderstood": "Misunderstood the question (model's reading)",
    "bad_calculation": "Wrong calculation or build advice (model's reading)",
    "unexplained": "No cause found: read the feedback",
}
NO_ANSWER_RE = re.compile(
    r"couldn't find|doesn't cover|don't cover|not covered|no wiki page|can't answer", re.IGNORECASE
)
SLOW_MS = 60_000
CLASSIFY_PROMPT = """You review answers of a Path of Exile build Q&A app that users rated
as not helpful. Decide the most likely cause. Reply with JSON only:
{"cause": "wrong_page" | "misunderstood" | "bad_calculation" | "unexplained", "why": "one sentence"}

wrong_page: the cited wiki pages don't fit the question, or the needed page is missing.
misunderstood: the answer addresses a different question than was asked.
bad_calculation: numbers or build advice from Path of Building look wrong or unhelpful.
unexplained: none of these is clear from what you see."""


def cause(log: QuestionLog) -> str:
    """The most likely cause, from the log alone (the first that applies)."""
    if log.error or not log.completed:
        return "error"
    if any(not tool.get("ok") for tool in log.tools):
        return "tool_failed"
    if log.facts_wrong:
        return "wrong_facts"
    if log.numbers_unsupported:
        return "unsupported_numbers"
    if NO_ANSWER_RE.search(log.answer[:600]):
        return "no_answer_in_wiki"
    if not log.cited and not log.tools:
        return "uncited"
    if (log.total_ms or 0) > SLOW_MS:
        return "slow"
    return "unexplained"


def classify(log: QuestionLog, provider: LLMProvider) -> tuple[str, str]:
    """Ask the model why a not-helpful answer missed; ("unexplained", "") on failure."""
    sources = ", ".join(str(s.get("title")) for s in log.sources[:8])
    user = (
        f"Question: {log.question}\nUser feedback: {log.feedback or '(none)'}\n"
        f"Wiki pages used: {sources}\nTools: {[t['name'] for t in log.tools]}\n"
        f"Answer:\n{log.answer[:2500]}"
    )
    try:
        messages: list[Message] = [
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": user},
        ]
        text = "".join(i for i in provider.stream(messages, quick=True) if isinstance(i, str))
        data = json.loads(text[text.index("{") : text.rindex("}") + 1])
    except (LLMError, ValueError):
        return "unexplained", ""
    found = data.get("cause")
    if found not in ("wrong_page", "misunderstood", "bad_calculation"):
        return "unexplained", str(data.get("why", ""))[:200]
    return found, str(data.get("why", ""))[:200]


def collect(days: int = 7, provider: LLMProvider | None = None) -> dict[str, Any]:
    """Answers of the last `days` days that went wrong, with their causes."""
    since = timezone.now() - timedelta(days=days)
    logs = QuestionLog.objects.filter(created_at__gte=since)
    total = logs.count()
    rated = logs.exclude(rating=None).count()
    bad = logs.filter(
        Q(rating=QuestionLog.Rating.DOWN)
        | ~Q(error="")
        | ~Q(numbers_unsupported=[])
        | ~Q(facts_wrong=[])
    ).order_by("-created_at")
    rows = []
    for log in bad:
        found, why = cause(log), ""
        if found == "unexplained" and provider and log.rating == QuestionLog.Rating.DOWN:
            found, why = classify(log, provider)
        rows.append(
            {
                "id": str(log.id),
                "date": f"{log.created_at:%Y-%m-%d}",
                "question": " ".join(log.question.split())[:160],
                "cause": found,
                "why": why,
                "rated_down": log.rating == QuestionLog.Rating.DOWN,
                "feedback": " ".join(log.feedback.split())[:300],
                "detail": _detail(log, found),
            }
        )
    counts = Counter(row["cause"] for row in rows)
    return {
        "days": days,
        "answers": total,
        "rated": rated,
        "rated_down": sum(row["rated_down"] for row in rows),
        "flagged": len(rows),
        "causes": [(key, counts[key]) for key in CAUSES if counts[key]],
        "rows": rows,
    }


def _detail(log: QuestionLog, found: str) -> str:
    if found == "error":
        return log.error[:200] or "stopped before it finished"
    if found == "tool_failed":
        failed = [t for t in log.tools if not t.get("ok")]
        return "; ".join(f"{t['name']}: {t.get('error', '')[:100]}" for t in failed[:3])
    if found == "wrong_facts":
        return "; ".join(str(f.get("fact")) for f in log.facts_wrong[:3])
    if found == "unsupported_numbers":
        return ", ".join(str(n.get("text")) for n in log.numbers_unsupported[:6])
    if found == "slow":
        return f"{(log.total_ms or 0) / 1000:.0f} s"
    return ""


def render(report: dict[str, Any]) -> str:
    """The report as Markdown."""
    lines = [
        f"# Answers that went wrong, last {report['days']} days",
        "",
        f"{report['answers']} answers, {report['rated']} rated, {report['rated_down']} rated "
        f"not helpful, {report['flagged']} flagged in total.",
        "",
    ]
    if not report["rows"]:
        return "\n".join([*lines, "Nothing was flagged."]) + "\n"
    lines += ["| Cause | Answers |", "|---|---|"]
    lines += [f"| {CAUSES[key]} | {count} |" for key, count in report["causes"]]
    for key, _ in report["causes"]:
        lines += ["", f"## {CAUSES[key]}", ""]
        for row in (r for r in report["rows"] if r["cause"] == key):
            mark = " (rated not helpful)" if row["rated_down"] else ""
            lines.append(f"- {row['date']}: {row['question']}{mark}")
            for label, value in (("", row["detail"]), ("Why: ", row["why"])):
                if value:
                    lines.append(f"  - {label}{value}")
            if row["feedback"]:
                lines.append(f'  - Feedback: "{row["feedback"]}"')
    lines += [
        "",
        "Turn the rated ones into eval cases: admin, Question logs, filter on the rating, "
        'action "Download as eval cases (YAML)".',
    ]
    return "\n".join(lines) + "\n"
