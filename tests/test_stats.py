"""The public numbers behind the How it works page."""

from decimal import Decimal

import pytest
from django.core.cache import cache

from advisor.models import QuestionLog

from .factories import make_document

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()


def test_stats_show_aggregates_only(client) -> None:
    make_document()
    QuestionLog.objects.create(
        question="secret question",
        completed=True,
        first_token_ms=3000,
        total_ms=9000,
        cost_usd=Decimal("0.002"),
        rating=1,
    )
    QuestionLog.objects.create(
        question="another",
        completed=True,
        first_token_ms=5000,
        total_ms=11000,
        cost_usd=Decimal("0.004"),
        rating=-1,
    )
    QuestionLog.objects.create(question="stopped", completed=False)

    data = client.get("/api/stats/").json()

    usage = data["usage"]
    assert usage["answers"] == 2 and usage["median_first_word_ms"] == 4000
    assert usage["average_cost_usd"] == pytest.approx(0.003)
    assert usage["helpful_share"] == 0.5
    assert data["corpus"]["pages"] == 1 and data["corpus"]["by_type"] == {"gem": 1}
    assert data["evals"]["cases"] >= 50  # from evals/results/latest.json
    assert data["eval_history"][0]["date"] and "mrr" in data["eval_history"][0]
    assert "secret question" not in str(data)


def test_stats_without_any_answers(client) -> None:
    usage = client.get("/api/stats/").json()["usage"]

    assert usage["answers"] == 0 and usage["median_first_word_ms"] is None
    assert usage["helpful_share"] is None


def test_share_of_answers_whose_numbers_are_all_found(client) -> None:
    QuestionLog.objects.create(question="a", completed=True, numbers_checked=3)
    QuestionLog.objects.create(
        question="b", completed=True, numbers_checked=2, numbers_unsupported=[{"text": "45%"}]
    )
    QuestionLog.objects.create(question="no numbers", completed=True)

    assert client.get("/api/stats/").json()["usage"]["numbers_grounded_share"] == 0.5
