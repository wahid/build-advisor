"""The report on answers that went wrong."""

from io import StringIO

import pytest
from django.core.management import call_command

from advisor.feedbackreport import cause, collect, render
from advisor.models import QuestionLog

from .test_advisor import FakeProvider

pytestmark = pytest.mark.django_db

DOWN = QuestionLog.Rating.DOWN


def log(question: str, **fields) -> QuestionLog:
    defaults = {"answer": "An answer [1].", "completed": True, "cited": [1]}
    return QuestionLog.objects.create(question=question, **{**defaults, **fields})


def test_the_cause_is_the_first_that_applies() -> None:
    assert cause(log("a", error="LLM down")) == "error"
    assert (
        cause(log("b", tools=[{"name": "load_build", "ok": False, "error": "bad"}]))
        == "tool_failed"
    )
    assert cause(log("c", facts_wrong=[{"fact": "Vaal Axe is two-handed."}])) == "wrong_facts"
    assert cause(log("d", numbers_unsupported=[{"text": "45%"}])) == "unsupported_numbers"
    assert (
        cause(log("e", answer="I couldn't find any wiki pages about this.")) == "no_answer_in_wiki"
    )
    assert cause(log("f", cited=[])) == "uncited"
    assert cause(log("g", total_ms=90_000)) == "slow"
    assert cause(log("h")) == "unexplained"


def test_only_answers_that_went_wrong_are_reported_grouped_by_cause() -> None:
    log("fine answer", rating=QuestionLog.Rating.UP)
    log("unrated and fine")
    log(
        "How much   life?",
        rating=DOWN,
        feedback="wrong number",
        numbers_unsupported=[{"text": "45%"}],
    )
    log("Broken", error="Path of Building stopped working.")
    log("Just bad", rating=DOWN)

    report = collect(days=7)

    assert (report["answers"], report["rated"], report["rated_down"], report["flagged"]) == (
        5,
        3,
        2,
        3,
    )
    assert dict(report["causes"]) == {"error": 1, "unsupported_numbers": 1, "unexplained": 1}
    text = render(report)
    assert "| Numbers not found in the sources | 1 |" in text
    assert "How much life? (rated not helpful)" in text and '"wrong number"' in text
    assert "  - 45%" in text
    assert "fine answer" not in text


def test_the_model_can_read_unexplained_thumbs_down() -> None:
    log("Why is my Cyclone weak?", rating=DOWN, sources=[{"title": "Poison"}])
    provider = FakeProvider(['{"cause": "wrong_page", "why": "The pages are about poison."}'])

    report = collect(days=7, provider=provider)

    assert report["rows"][0]["cause"] == "wrong_page"
    assert "Why: The pages are about poison." in render(report)
    garbled = collect(days=7, provider=FakeProvider(["not json"]))
    assert garbled["rows"][0]["cause"] == "unexplained"


def test_the_command_writes_the_report(tmp_path) -> None:
    out = StringIO()
    call_command("feedback_report", stdout=out)
    assert "Nothing was flagged." in out.getvalue()

    log("Broken", error="down")
    path = tmp_path / "reports" / "feedback.md"
    call_command("feedback_report", "--days", "30", "--output", str(path), stdout=StringIO())
    assert "## Ended in an error" in path.read_text()
