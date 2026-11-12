"""Numbers in answers are checked against the sources and tool results."""

import pytest

from advisor.guardrails import check, claims
from advisor.models import QuestionLog
from advisor.questionlog import record

EVIDENCE = [
    "[1] Cyclone (patch 3.29.3c)\nAttack speed multiplier 300%. Requires level 28.",
    '{"changes": {"Life": {"before": 1229, "after": 1294, "change": 65, "pct": 5.29},'
    ' "CombinedDPS": {"before": 95.55, "after": 1116.42}, "TotalEHP": {"pct": 18.86}}}',
    "Melee Physical Damage: 30-49% more melee physical damage",
]


def texts(answer: str) -> list[str]:
    return [c.text for c in claims(answer)]


def test_numbers_worth_checking_are_found() -> None:
    answer = (
        "1. Take Cyclone [3] at level 28 in act 3 (patch 3.29.3c), 2 sockets.\n"
        "It deals 1.1M DPS, +18.9% EHP and 30-49% more damage, since 2024."
    )
    assert texts(answer) == ["28", "1.1M", "18.9%", "30", "49%"]


def test_numbers_from_the_evidence_pass_with_rounding() -> None:
    answer = (
        "Cyclone has a 300% attack speed multiplier [1] and needs level 28. "
        "Life goes from 1229 to 1294 (+65), DPS from 95.6 to 1116, EHP +19% (+18.9%), "
        "and Melee Physical Damage gives 30-49% more. That's about 1.1k DPS."
    )
    result = check(answer, EVIDENCE)

    assert result.unsupported == []
    assert result.checked == 12


def test_made_up_numbers_are_flagged_once_with_context() -> None:
    answer = "Cyclone needs level 34 and gives 45% more damage. Really, 45% more."

    result = check(answer, EVIDENCE)

    assert [u["text"] for u in result.unsupported] == ["34", "45%"]
    assert result.unsupported[0]["context"].startswith("Cyclone needs level 34")


def test_general_knowledge_sentences_are_counted_apart() -> None:
    answer = (
        "Strength gives +1 life per 2 points, so 25 Strength is 12 life (general game "
        "knowledge). The ring adds 65 life."
    )
    result = check(answer, EVIDENCE)

    assert result.knowledge == 2  # 25 and 12; "+1" and "2" are too small to check
    assert result.unsupported == [] and result.checked == 1


@pytest.mark.django_db
def test_the_check_is_logged() -> None:
    numbers = {"checked": 4, "unsupported": [{"text": "45%", "context": "x"}], "knowledge": 0}
    events = [
        {"type": "delta", "text": "Answer"},
        {"type": "done", "cited": [], "patch": "", "numbers": numbers},
    ]

    list(record(iter(events), "q", build="", doc_types=[]))

    log = QuestionLog.objects.get()
    assert log.numbers_checked == 4 and log.numbers_unsupported[0]["text"] == "45%"


def test_arithmetic_shown_in_the_answer_and_percent_fractions_pass() -> None:
    evidence = ["Lethal Dose: supported skills deal 60% less damage with poison", "1229 and 1294"]
    answer = (
        "Each poison deals 0.4 of the damage, so 3 poisons are 3 × 0.4 = 1.2× as much. "
        "Life goes 1229 → 1294 (+65), and 0.4 m range."
    )
    result = check(answer, evidence)

    assert result.unsupported == [], result.unsupported


def test_metres_are_not_millions() -> None:
    assert [(c.text, c.value) for c in claims("+0.4 m strike range, 1.1M DPS")] == [
        ("0.4", 0.4),
        ("1.1M", 1_100_000),
    ]
