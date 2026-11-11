from datetime import date

import pytest

from advisor.limits import questions_today, take_question
from advisor.models import DailyUsage

pytestmark = pytest.mark.django_db


def test_counts_until_the_limit(settings) -> None:
    settings.ASK_DAILY_LIMIT = 3

    assert [take_question() for _ in range(5)] == [True, True, True, False, False]
    assert questions_today() == 3  # refused questions aren't counted


def test_zero_means_no_limit(settings) -> None:
    settings.ASK_DAILY_LIMIT = 0

    assert all(take_question() for _ in range(5))
    assert not DailyUsage.objects.exists()


def test_new_day_starts_from_zero(settings, mocker) -> None:
    settings.ASK_DAILY_LIMIT = 1
    mocker.patch("advisor.limits.today", return_value=date(2026, 11, 11))
    assert take_question() and not take_question()

    mocker.patch("advisor.limits.today", return_value=date(2026, 11, 12))
    assert take_question()


@pytest.fixture
def wired(mocker):
    from wiki.indexing import build_chunks, embed_pending

    from .factories import FakeEmbedder, make_document
    from .test_advisor import FakeProvider

    make_document()
    build_chunks()
    embedder = FakeEmbedder()
    embed_pending(embedder)
    mocker.patch("wiki.search.get_embedder", return_value=embedder)
    mocker.patch("advisor.rag.get_provider", return_value=FakeProvider(["ok [1]."]))


def _ask(client, **data):
    return client.post(
        "/api/ask/",
        {"question": "Righteous Fire", "stream": False, **data},
        content_type="application/json",
    )


def test_endpoint_refuses_after_the_daily_limit(client, settings, wired) -> None:
    settings.ASK_DAILY_LIMIT = 2

    assert _ask(client).status_code == 200
    assert _ask(client).status_code == 200
    response = _ask(client)

    assert response.status_code == 429
    assert response.json()["code"] == "daily_limit"
    assert "limit of 2 questions" in response.json()["detail"]


def test_invalid_questions_dont_count(client, settings, wired) -> None:
    settings.ASK_DAILY_LIMIT = 1

    assert client.post("/api/ask/", {}, content_type="application/json").status_code == 400
    assert _ask(client).status_code == 200
