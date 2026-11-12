"""Question logs: timings, tools, tokens and cost per answer; feedback on them."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from advisor.llm import Usage, metering
from advisor.models import QuestionLog
from advisor.questionlog import Recorder, cost

pytestmark = pytest.mark.django_db


def events():
    yield {"type": "rewrite", "terms": "Poison, Bleeding", "tools": False}
    yield {
        "type": "sources",
        "sources": [
            {
                "number": 1,
                "title": "Poison",
                "section": "",
                "url": "https://w/Poison",
                "patch": "3.29",
                "doc_type": "mechanic",
            }
        ],
    }
    yield {"type": "tool_call", "id": "w1", "name": "web_search", "arguments": {"query": "q"}}
    yield {"type": "tool_result", "id": "w1", "name": "web_search", "ok": True, "error": ""}
    yield {"type": "delta", "text": "Poisons stack [1]."}
    yield {"type": "done", "cited": [1], "patch": "3.29"}


def test_a_finished_answer_is_logged_with_its_trace(settings) -> None:
    settings.LLM_PRICE_INPUT, settings.LLM_PRICE_CACHED_INPUT = 1.0, 0.1
    settings.LLM_PRICE_OUTPUT, settings.WEB_SEARCH_PRICE = 2.0, 0.001
    earlier = [{"question": "What is poison?", "answer": "A chaos damage ailment [1]."}]
    recorder = Recorder("How does it stack?", build="", history=earlier, doc_types=["mechanic"])

    out = []
    for event in recorder.wrap(events()):
        out.append(event)

    log = QuestionLog.objects.get()
    assert out[-1]["log_id"] == str(log.id)
    assert log.completed and log.answer == "Poisons stack [1]."
    assert log.history_turns == 1 and log.history[0]["question"] == "What is poison?"
    assert log.search_terms == "Poison, Bleeding" and log.cited == [1]
    assert log.sources[0]["title"] == "Poison"
    assert log.tools[0]["name"] == "web_search" and log.web_searches == 1
    assert log.search_ms is not None and log.first_token_ms is not None and log.total_ms is not None
    assert log.cost_usd == Decimal("0.001")  # no LLM calls were metered here


def test_a_stopped_answer_is_still_logged() -> None:
    stream = Recorder("q", build="https://pobb.in/x", doc_types=[]).wrap(events())
    next(stream)
    stream.close()  # the client went away

    log = QuestionLog.objects.get()
    assert log.completed is False
    assert log.build == "https://pobb.in/x"


def test_cost_counts_cached_tokens_at_their_own_price(settings) -> None:
    settings.LLM_PRICE_INPUT, settings.LLM_PRICE_CACHED_INPUT = 1.0, 0.1
    settings.LLM_PRICE_OUTPUT, settings.WEB_SEARCH_PRICE = 2.0, 0.0
    usage = Usage(
        calls=2, prompt_tokens=1_000_000, cached_prompt_tokens=500_000, completion_tokens=100_000
    )

    assert cost(usage, 0) == Decimal("0.75")  # 0.5 + 0.05 + 0.2


def test_tokens_are_metered_from_the_stream() -> None:
    from advisor.llm import OpenAICompatibleProvider

    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Hi", tool_calls=None, reasoning_content=None)
                )
            ],
            usage=None,
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=8,
                prompt_tokens_details=None,
                prompt_cache_hit_tokens=100,
            ),
        ),
    ]
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return iter(chunks)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = OpenAICompatibleProvider("deepseek", "m", "k", "u", client=client)

    with metering() as usage:
        assert list(provider.stream([{"role": "user", "content": "hi"}])) == ["Hi"]

    assert sent["stream_options"] == {"include_usage": True}
    assert (
        usage.calls,
        usage.prompt_tokens,
        usage.cached_prompt_tokens,
        usage.completion_tokens,
    ) == (1, 120, 100, 8)


def test_feedback_is_stored_on_the_log(client) -> None:
    log = QuestionLog.objects.create(question="q")

    response = client.post(
        "/api/feedback/",
        {"log_id": str(log.id), "rating": -1, "feedback": " Missed the bleed rule "},
        content_type="application/json",
    )

    assert response.status_code == 200
    log.refresh_from_db()
    assert (log.rating, log.feedback) == (-1, "Missed the bleed rule")
    assert log.rated_at is not None


def test_feedback_for_an_unknown_answer_is_rejected(client) -> None:
    unknown = "00000000-0000-0000-0000-000000000000"
    bad = client.post(
        "/api/feedback/", {"log_id": unknown, "rating": 1}, content_type="application/json"
    )
    invalid = client.post(
        "/api/feedback/", {"log_id": unknown, "rating": 5}, content_type="application/json"
    )

    assert bad.status_code == 404
    assert invalid.status_code == 400


def test_the_ask_endpoint_returns_the_log_id(client, mocker) -> None:
    mocker.patch("advisor.views.answer_stream", return_value=iter(list(events())))

    data = client.post(
        "/api/ask/", {"question": "q", "stream": False}, content_type="application/json"
    ).json()

    assert QuestionLog.objects.filter(id=data["log_id"]).exists()
    assert data["text"] == "Poisons stack [1]." and data["cited"] == [1]
    assert json.dumps(data)  # serialisable


@pytest.fixture
def admin_client(client, django_user_model):
    user = django_user_model.objects.create_superuser("admin", "a@example.com", "pw")
    client.force_login(user)
    return client


def test_admin_list_shows_totals(admin_client) -> None:
    QuestionLog.objects.create(
        question="How does poison stack?",
        rating=-1,
        total_ms=4000,
        first_token_ms=900,
        cost_usd=Decimal("0.0021"),
    )

    page = admin_client.get("/admin/advisor/questionlog/").content.decode()

    assert "How does poison stack?" in page
    assert "Last 7 days" in page and "0.0021" in page


def test_rated_answers_download_as_eval_cases(admin_client) -> None:
    import yaml

    log = QuestionLog.objects.create(
        question="And bleed?",
        rating=-1,
        feedback="Missed Crimson Dance",
        history=[{"question": "How does poison stack?", "answer": "Each poison counts."}],
        build="https://pobb.in/x",
        tools=[{"name": "rank_skill_gems", "ok": True}],
        answer="Only the strongest bleed counts.",
    )

    response = admin_client.post(
        "/admin/advisor/questionlog/",
        {"action": "download_eval_cases", "_selected_action": [str(log.id)]},
    )

    assert response["Content-Disposition"].endswith('feedback-cases.yaml"')
    [case] = yaml.safe_load(response.content.decode())
    assert case["question"] == "And bleed?" and case["category"] == "feedback"
    assert case["history"][0]["question"] == "How does poison stack?"
    assert case["build"] == "https://pobb.in/x" and case["seen_tools"] == ["rank_skill_gems"]
    assert "Missed Crimson Dance" in case["notes"]
