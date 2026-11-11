import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.core.management import call_command

from advisor.evaluation import (
    EvalCase,
    invalid_citations,
    load_cases,
    missing_mentions,
    parse_verdict,
    render_markdown,
    run,
    score_retrieval,
    update_readme,
)
from wiki.corpus import load_corpus, read_corpus, select_documents, write_corpus
from wiki.indexing import build_chunks, embed_pending
from wiki.models import Document, DocumentType

from .factories import FakeEmbedder, make_document
from .test_advisor import FakeProvider

QUESTIONS = Path(settings.BASE_DIR) / "evals" / "questions.yaml"


def hit(title: str) -> SimpleNamespace:
    return SimpleNamespace(title=title)


# --- the question set itself ----------------------------------------------------------


def test_question_set_is_valid() -> None:
    cases = load_cases(QUESTIONS)

    assert len(cases) >= 30
    categories = {c.category for c in cases}
    assert {"mechanic", "gem", "unique", "ascendancy", "unanswerable"} <= categories
    for case in cases:
        if case.answerable and case.category != "build":
            assert case.expected_sources, case.id
            assert case.must_mention, case.id
        if not case.answerable:
            assert not case.must_mention, case.id


def test_unquoted_yes_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "q.yaml"
    path.write_text("- {id: a, question: q, category: gem, must_mention: [[yes, both]]}\n")

    with pytest.raises(ValueError, match="quote yes"):
        load_cases(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "q.yaml"
    path.write_text(
        "- {id: a, question: q, category: gem}\n- {id: a, question: q, category: gem}\n"
    )

    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(path)


# --- metrics ----------------------------------------------------------------------------


def test_retrieval_scores() -> None:
    hits = [
        hit("Vaal Righteous Fire"),
        hit("Righteous Fire"),
        hit("Chieftain"),
        hit("Righteous Fire"),
    ]

    score = score_retrieval(["Righteous Fire", "chieftain", "Kaom's Heart"], hits)

    assert score.hit is True
    assert score.recall == pytest.approx(2 / 3)
    assert score.reciprocal_rank == 0.5


def test_retrieval_miss() -> None:
    score = score_retrieval(["Ignite"], [hit("Freeze")])

    assert (score.hit, score.recall, score.reciprocal_rank) == (False, 0.0, 0.0)


def test_must_mention_with_alternatives() -> None:
    text = "Ignite deals Fire damage over time."

    assert missing_mentions(text, (("fire",), ("burning", "damage over time"))) == []
    assert missing_mentions(text, (("chaos",), ("stack", "multiple"))) == [
        "chaos",
        "stack / multiple",
    ]


def test_invalid_citations() -> None:
    assert invalid_citations("a [1] b [3] c [0]", source_count=2) == [0, 3]


def test_parse_verdict_tolerates_surrounding_text() -> None:
    verdict = parse_verdict(
        "Sure:\n```json\n"
        '{"grounded": 5, "relevant": 4, "admits_gap": false, "unsupported": [], "reason": "ok"}'
        "\n```"
    )

    assert (verdict.grounded, verdict.relevant, verdict.admits_gap, verdict.error) == (
        5,
        4,
        False,
        "",
    )
    assert parse_verdict("no idea").error


# --- running ----------------------------------------------------------------------------


@pytest.fixture
def indexed() -> FakeEmbedder:
    make_document(
        "Ignite",
        "Ignite is a fire damage over time ailment caused by fire hits.\n\n"
        "## Duration\n\nIt lasts four seconds by default.",
        doc_type=DocumentType.MECHANIC,
    )
    make_document(
        "Freeze",
        "Freeze prevents an enemy from acting for a short time.",
        doc_type=DocumentType.MECHANIC,
    )
    build_chunks()
    embedder = FakeEmbedder()
    embed_pending(embedder)
    return embedder


CASES = [
    EvalCase(
        "ignite", "What is ignite?", "mechanic", ("Ignite",), (("fire",), ("damage over time",))
    ),
    EvalCase("future", "Best build next league?", "unanswerable", answerable=False),
    EvalCase("pob", "Make a build", "build", requires_pob=True),
]


@pytest.mark.django_db
def test_retrieval_only_run(indexed: FakeEmbedder) -> None:
    report = run(CASES, k=4, embedder=indexed)

    assert report.skipped == ["pob"]
    ignite = report.cases[0]
    assert ignite.retrieval is not None and ignite.retrieval.hit
    assert ignite.passed
    assert report.summary()["hit@4"] == 1.0


GOOD = '{"grounded": 5, "relevant": 5, "admits_gap": false, "unsupported": [], "reason": "fine"}'
GAP = '{"grounded": 5, "relevant": 3, "admits_gap": true, "unsupported": [], "reason": "says so"}'


@pytest.mark.django_db
def test_answer_run_with_judge(indexed: FakeEmbedder) -> None:
    answers = FakeProvider(
        ["Ignite deals fire damage over time [1]."],
        ["The wiki doesn't cover future leagues."],
    )
    judge = FakeProvider([GOOD], [GAP])

    report = run(
        CASES[:2],
        k=4,
        answer_questions=True,
        provider=answers,
        judge_provider=judge,
        embedder=indexed,
    )

    assert [c.passed for c in report.cases] == [True, True]
    summary = report.summary()
    assert summary["pass_rate"] == 1.0
    assert summary["admits_gap"] == 1.0
    assert summary["grounded"] == 5
    # The judge saw the question, the sources and the answer.
    judged = judge.calls[0][0][1]["content"]
    assert (
        "What is ignite?" in judged
        and "[1] Ignite" in judged
        and "fire damage over time [1]" in judged
    )


@pytest.mark.django_db
def test_failures_are_explained_in_the_report(indexed: FakeEmbedder) -> None:
    answers = FakeProvider(["Ignite is chaos damage [7]."])
    judge = FakeProvider(
        ['{"grounded": 2, "relevant": 4, "admits_gap": false, "reason": "wrong type"}']
    )

    report = run(
        CASES[:1],
        k=4,
        answer_questions=True,
        provider=answers,
        judge_provider=judge,
        embedder=indexed,
    )

    case = report.cases[0]
    assert not case.passed
    assert case.missing == ["fire", "damage over time"]
    assert case.invalid_citations == [7]
    markdown = render_markdown(report, "_meta_")
    assert "1 failing cases" in markdown
    assert "missing: fire; damage over time" in markdown
    assert "grounded 2" in markdown
    assert "| Cases passed | 0% |" in markdown


def test_update_readme_replaces_only_the_marked_block(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n<!-- evals:start -->\nold\n<!-- evals:end -->\nAfter\n")

    assert update_readme(readme, "| new |")
    assert (
        readme.read_text() == "# Title\n<!-- evals:start -->\n| new |\n<!-- evals:end -->\nAfter\n"
    )

    other = tmp_path / "OTHER.md"
    other.write_text("no markers")
    assert update_readme(other, "x") is False


# --- corpus ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_corpus_selection_export_and_load(tmp_path: Path) -> None:
    for title in [
        "Righteous Fire",
        "Vaal Righteous Fire",
        "Chieftain",
        "Ice Nova",
        "Fireball",
        "Frostbolt",
    ]:
        make_document(title)

    documents, missing, hard = select_documents(
        ["Righteous Fire", "Chieftain", "Nope"], distractors=2, seed=1
    )

    titles = {d.title for d in documents}
    assert {"Righteous Fire", "Chieftain", "Vaal Righteous Fire"} <= titles
    assert len(titles) == 5  # 2 expected + 1 hard + 2 random
    assert missing == ["Nope"]
    assert hard == 1

    path = tmp_path / "corpus.jsonl.gz"
    write_corpus(documents, path)
    first_bytes = path.read_bytes()
    write_corpus(documents, path)
    assert path.read_bytes() == first_bytes  # deterministic file
    assert {r["title"] for r in read_corpus(path)} == titles

    Document.objects.all().delete()
    assert load_corpus(path) == 5
    rf = Document.objects.get(title="Righteous Fire")
    assert rf.source.url == "https://wiki.test/wiki/Righteous_Fire"
    assert rf.content_hash


@pytest.mark.django_db
def test_run_evals_command_writes_results(indexed: FakeEmbedder, tmp_path: Path, mocker) -> None:
    mocker.patch("wiki.search.get_embedder", return_value=indexed)
    questions = tmp_path / "q.yaml"
    questions.write_text(
        "- id: ignite\n  question: What is ignite?\n  category: mechanic\n"
        "  expected_sources: [Ignite]\n  must_mention: [fire]\n"
    )
    out = StringIO()

    call_command(
        "run_evals", "--questions", str(questions), "--output", str(tmp_path / "res"), stdout=out
    )

    data = json.loads((tmp_path / "res.json").read_text())
    assert data["summary"]["cases"] == 1
    assert "retrieval only" in data["meta"]
    assert "Expected page in top" in (tmp_path / "res.md").read_text()
    assert "pass" in out.getvalue()


@pytest.mark.django_db
def test_retrieval_run_with_rewrite(indexed: FakeEmbedder) -> None:
    provider = FakeProvider(["Ignite"])

    report = run(CASES[:1], k=4, embedder=indexed, provider=provider, rewrite=True)

    assert report.cases[0].rewrite == "Ignite"
    assert report.cases[0].passed


def test_judge_retries_once_when_it_returns_no_json() -> None:
    from advisor.evaluation import judge

    provider = FakeProvider([""], [GOOD])

    verdict = judge(provider, "q", "sources", "answer")

    assert verdict.grounded == 5
    assert provider.quick == [False, True]  # the retry skips thinking


def test_judge_sees_path_of_building_results() -> None:
    from advisor.evaluation import judge

    provider = FakeProvider([GOOD])

    judge(provider, "q", "[1] Source", "answer", tools='- get_stats: {"Life": 5110}')

    content = provider.calls[0][0][1]["content"]
    assert "Path of Building tool results:\n- get_stats" in content


@pytest.mark.django_db
def test_build_cases_dont_require_groundedness(indexed: FakeEmbedder, mocker) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace as NS

    from advisor.llm import ToolCall
    from advisor.pob import ToolResult

    class Box:
        definitions = [{"type": "function", "function": {"name": "export_build"}}]

        def call(self, name, arguments):
            return ToolResult(ok=True, text='{"code": "eNr"}', data={"code": "eNr"})

    @contextmanager
    def checkout(**_kwargs):
        yield Box()

    mocker.patch("advisor.rag.get_pool", return_value=NS(toolbox=checkout))
    case = EvalCase(
        "b", "Make a build", "build", ("Ignite",), requires_pob=True, expect_tools=("export_build",)
    )
    answers = FakeProvider([ToolCall("e", "export_build", "{}")], ["Built it; the code is below."])
    judge_says = FakeProvider(
        ['{"grounded": 2, "relevant": 5, "admits_gap": false, "reason": "PoB data"}']
    )

    report = run(
        [case],
        k=4,
        answer_questions=True,
        provider=answers,
        judge_provider=judge_says,
        embedder=indexed,
        pob_available=True,
    )

    assert report.cases[0].passed
