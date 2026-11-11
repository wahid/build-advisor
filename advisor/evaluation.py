"""Evaluation of retrieval and answers against evals/questions.yaml.

Retrieval (no LLM needed):
  hit@k     one of the expected pages is among the top-k chunks
  recall@k  share of the expected pages found in the top-k
  MRR       1 / rank of the first chunk from an expected page

Answers (needs an LLM):
  must_mention   the answer contains each required fact
  citations      every [n] refers to a real source
  judge          an LLM rates groundedness and relevance (1-5) and whether the
                 answer admits what the sources don't cover
  tools          build cases call the expected Path of Building tools

A case passes when its retrieval hit (if it has expected pages) and all answer
checks that apply to it pass. For build cases the judge's groundedness is
reported but not required: it only sees truncated Path of Building results,
so it can't verify most PoB-derived claims. Those cases rely on the objective
checks (expected tools including the export, citations, required facts) and
relevance.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from wiki.embeddings import Embedder
from wiki.search import SearchFilters, SearchHit, hybrid_search

from .llm import LLMProvider, Message
from .prompts import format_sources
from .rag import CITATION_RE, answer
from .rewrite import rewrite_query

logger = logging.getLogger(__name__)

PASSING_SCORE = 4  # judge scores of 4 or 5 pass

JUDGE_PROMPT = """\
You grade answers of a Path of Exile assistant that must answer only from the
numbered wiki sources it was given and, for build questions, from Path of
Building tool results (shown after the sources, possibly truncated).
The app shows exported Path of Building share codes below the answer, so an
answer that says "the code is below" does deliver it.

Return only a JSON object:
{
  "grounded": 1-5,      // 5 = every factual claim is supported by the sources
                        //     (claims explicitly attributed to Path of Building count as supported)
  "relevant": 1-5,      // 5 = directly and fully answers the question
  "admits_gap": true/false,  // says the sources/wiki don't cover (part of) the question
  "unsupported": ["claims not supported by the sources"],
  "reason": "one sentence"
}"""


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    category: str
    expected_sources: tuple[str, ...] = ()
    must_mention: tuple[tuple[str, ...], ...] = ()
    answerable: bool = True
    requires_pob: bool = False
    expect_tools: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCase:
        mentions = tuple(
            tuple(_phrase(a, data["id"]) for a in (item if isinstance(item, list) else [item]))
            for item in data.get("must_mention", [])
        )
        return cls(
            id=data["id"],
            question=data["question"],
            category=data["category"],
            expected_sources=tuple(data.get("expected_sources", [])),
            must_mention=mentions,
            answerable=data.get("answerable", True),
            requires_pob=data.get("requires_pob", False),
            expect_tools=tuple(data.get("expect_tools", [])),
            doc_types=tuple(data.get("doc_types", [])),
        )


def _phrase(value: Any, case_id: str) -> str:
    # YAML turns bare yes/no/on/off into booleans; demand quotes instead of guessing.
    if isinstance(value, bool):
        raise ValueError(f'{case_id}: quote yes/no/true/false in must_mention, e.g. "yes"')
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        raise ValueError(f"{case_id}: must_mention entries must be text, got {value!r}")
    return value


def load_cases(path: Path) -> list[EvalCase]:
    cases = [EvalCase.from_dict(item) for item in yaml.safe_load(path.read_text(encoding="utf-8"))]
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate eval ids: {sorted(duplicates)}")
    return cases


# --- retrieval ----------------------------------------------------------------------


@dataclass
class RetrievalScore:
    hit: bool
    recall: float
    reciprocal_rank: float
    retrieved: list[str]


def score_retrieval(expected: Iterable[str], hits: list[SearchHit]) -> RetrievalScore:
    wanted = {title.casefold() for title in expected}
    titles = [hit.title for hit in hits]
    found = {t.casefold() for t in titles} & wanted
    first = next((i for i, t in enumerate(titles, start=1) if t.casefold() in wanted), None)
    return RetrievalScore(
        hit=bool(found),
        recall=len(found) / len(wanted) if wanted else 0.0,
        reciprocal_rank=1 / first if first else 0.0,
        retrieved=titles,
    )


# --- answer checks --------------------------------------------------------------------


def missing_mentions(text: str, must_mention: tuple[tuple[str, ...], ...]) -> list[str]:
    lowered = text.casefold()
    return [
        " / ".join(alternatives)
        for alternatives in must_mention
        if not any(a.casefold() in lowered for a in alternatives)
    ]


def invalid_citations(text: str, source_count: int) -> list[int]:
    return sorted({n for n in map(int, CITATION_RE.findall(text)) if not 1 <= n <= source_count})


@dataclass
class Verdict:
    grounded: int = 0
    relevant: int = 0
    admits_gap: bool = False
    unsupported: list[str] = field(default_factory=list)
    reason: str = ""
    error: str = ""


def parse_verdict(text: str) -> Verdict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return Verdict(error="judge returned no JSON")
    try:
        data = json.loads(match.group(0))
        return Verdict(
            grounded=int(data.get("grounded", 0)),
            relevant=int(data.get("relevant", 0)),
            admits_gap=bool(data.get("admits_gap", False)),
            unsupported=[str(c) for c in data.get("unsupported", [])][:10],
            reason=str(data.get("reason", ""))[:500],
        )
    except (ValueError, TypeError) as exc:
        return Verdict(error=f"judge returned invalid JSON: {exc}")


def judge(
    provider: LLMProvider, question: str, sources: str, answer_text: str, tools: str = ""
) -> Verdict:
    messages: list[Message] = [
        {"role": "system", "content": JUDGE_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question: {question}\n\nSources:\n{sources}\n\n"
                + (f"Path of Building tool results:\n{tools}\n\n" if tools else "")
                + f"Answer to grade:\n{answer_text}"
            ),
        },
    ]
    verdict = Verdict(error="judge not run")
    for _ in range(2):  # one retry: reasoning models sometimes return no final text
        text = "".join(item for item in provider.stream(messages) if isinstance(item, str))
        verdict = parse_verdict(text)
        if not verdict.error:
            break
    return verdict


# --- running ----------------------------------------------------------------------------


@dataclass
class CaseResult:
    id: str
    category: str
    question: str
    passed: bool
    retrieval: RetrievalScore | None = None
    answer: str = ""
    missing: list[str] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    verdict: Verdict | None = None
    error: str = ""
    seconds: float = 0.0
    rewrite: str = ""


@dataclass
class Report:
    k: int
    answered: bool
    cases: list[CaseResult]
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        retrieval = [c.retrieval for c in self.cases if c.retrieval is not None]
        out: dict[str, Any] = {
            "cases": len(self.cases),
            "skipped": len(self.skipped),
            f"hit@{self.k}": _ratio(r.hit for r in retrieval),
            f"recall@{self.k}": _avg(r.recall for r in retrieval),
            "mrr": _avg(r.reciprocal_rank for r in retrieval),
        }
        if self.answered:
            answerable = [c for c in self.cases if c.verdict and c.category != "unanswerable"]
            unanswerable = [c for c in self.cases if c.verdict and c.category == "unanswerable"]
            out.update(
                {
                    "pass_rate": _ratio(c.passed for c in self.cases),
                    "must_mention": _ratio(not c.missing for c in self.cases if not c.error),
                    "valid_citations": _ratio(not c.invalid_citations for c in self.cases),
                    "grounded": _avg(c.verdict.grounded for c in answerable if c.verdict),
                    "relevant": _avg(c.verdict.relevant for c in answerable if c.verdict),
                    "admits_gap": _ratio(c.verdict.admits_gap for c in unanswerable if c.verdict),
                }
            )
        return out

    def by_category(self) -> dict[str, dict[str, Any]]:
        categories: dict[str, list[CaseResult]] = {}
        for case in self.cases:
            categories.setdefault(case.category, []).append(case)
        return {
            name: {
                "cases": len(items),
                f"hit@{self.k}": _ratio(c.retrieval.hit for c in items if c.retrieval),
                "pass_rate": _ratio(c.passed for c in items) if self.answered else None,
            }
            for name, items in categories.items()
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "by_category": self.by_category(),
            "skipped": self.skipped,
            "cases": [asdict(c) for c in self.cases],
        }


def _ratio(values: Iterable[bool]) -> float | None:
    items = list(values)
    return round(sum(items) / len(items), 3) if items else None


def _avg(values: Iterable[float]) -> float | None:
    items = list(values)
    return round(mean(items), 3) if items else None


def run(
    cases: list[EvalCase],
    k: int = 8,
    answer_questions: bool = False,
    provider: LLMProvider | None = None,
    judge_provider: LLMProvider | None = None,
    embedder: Embedder | None = None,
    pob_available: bool = False,
    progress: Callable[[CaseResult], None] | None = None,
    rewrite: bool = False,
) -> Report:
    report = Report(k=k, answered=answer_questions, cases=[])
    for case in cases:
        if case.requires_pob and not (answer_questions and pob_available):
            report.skipped.append(case.id)
            continue
        started = time.monotonic()
        result = _run_case(case, k, answer_questions, provider, judge_provider, embedder, rewrite)
        result.seconds = round(time.monotonic() - started, 1)
        report.cases.append(result)
        if progress:
            progress(result)
    return report


def _run_case(
    case: EvalCase,
    k: int,
    answer_questions: bool,
    provider: LLMProvider | None,
    judge_provider: LLMProvider | None,
    embedder: Embedder | None,
    rewrite: bool = False,
) -> CaseResult:
    filters = SearchFilters(doc_types=case.doc_types)
    expansion = rewrite_query(case.question, provider) if rewrite and provider else ""
    hits = hybrid_search(
        case.question, top_k=k, filters=filters, embedder=embedder, expansion=expansion
    )
    retrieval = score_retrieval(case.expected_sources, hits) if case.expected_sources else None
    result = CaseResult(case.id, case.category, case.question, passed=False, retrieval=retrieval)
    result.rewrite = expansion
    retrieval_ok = retrieval is None or retrieval.hit
    if not answer_questions:
        result.passed = retrieval_ok
        return result

    produced = answer(
        case.question,
        filters=filters,
        provider=provider,
        embedder=embedder,
        top_k=k,
        use_tools=case.requires_pob,
        expansion=expansion,  # same terms as the retrieval score; no second rewrite
    )
    result.answer = produced.text
    result.tools_called = [t["name"] for t in produced.tools]
    if produced.error:
        result.error = produced.error
        return result

    result.missing = missing_mentions(produced.text, case.must_mention)
    result.invalid_citations = invalid_citations(produced.text, len(produced.sources))
    result.missing_tools = [t for t in case.expect_tools if t not in result.tools_called]
    tool_results = "\n".join(f"- {t['name']}: {t['preview']}" for t in produced.tools)
    verdict = judge(
        judge_provider or provider,  # type: ignore[arg-type]
        case.question,
        format_sources(hits),
        produced.text,
        tool_results,
    )
    result.verdict = verdict

    if verdict.error:
        result.error = verdict.error
    elif case.answerable:
        grounded_ok = case.category == "build" or verdict.grounded >= PASSING_SCORE
        result.passed = (
            retrieval_ok
            and not result.missing
            and not result.invalid_citations
            and not result.missing_tools
            and grounded_ok
            and verdict.relevant >= PASSING_SCORE
        )
    else:
        result.passed = verdict.admits_gap and not result.invalid_citations
    return result


# --- reporting -----------------------------------------------------------------------------

README_START = "<!-- evals:start -->"
README_END = "<!-- evals:end -->"

LABELS = {
    "hit@": "Expected page in top {k}",
    "recall@": "Expected pages found (recall@{k})",
    "mrr": "Mean reciprocal rank",
    "pass_rate": "Cases passed",
    "must_mention": "Required facts mentioned",
    "valid_citations": "Answers with only valid citations",
    "grounded": "Groundedness (judge, 1-5)",
    "relevant": "Relevance (judge, 1-5)",
    "admits_gap": "Says so when the wiki doesn't cover it",
}


def _label(key: str, k: int) -> str:
    for prefix, label in LABELS.items():
        if key == prefix or (prefix.endswith("@") and key.startswith(prefix)):
            return label.format(k=k)
    return key


def _format(key: str, value: Any) -> str:
    if value is None:
        return "n/a"
    if key in {"grounded", "relevant", "mrr"}:
        return f"{value:.2f}"
    return f"{value * 100:.0f}%"


def render_markdown(report: Report, meta: str = "") -> str:
    summary = report.summary()
    lines = []
    if meta:
        lines += [meta, ""]
    lines += ["| Metric | Score |", "|---|---|"]
    for key, value in summary.items():
        if key in {"cases", "skipped"}:
            continue
        lines.append(f"| {_label(key, report.k)} | {_format(key, value)} |")
    lines += ["", "| Category | Cases | " + f"Hit@{report.k} | Passed |", "|---|---|---|---|"]
    for name, row in report.by_category().items():
        passed = _format("pass_rate", row["pass_rate"]) if report.answered else "n/a"
        lines.append(
            f"| {name} | {row['cases']} | {_format('hit', row[f'hit@{report.k}'])} | {passed} |"
        )
    failed = [c for c in report.cases if not c.passed]
    if failed:
        lines += ["", f"<details><summary>{len(failed)} failing cases</summary>", ""]
        for case in failed:
            lines.append(f"- `{case.id}`: {_why(case)}")
        lines += ["", "</details>"]
    return "\n".join(lines)


def _why(case: CaseResult) -> str:
    reasons = []
    if case.error:
        reasons.append(case.error)
    if case.retrieval and not case.retrieval.hit:
        reasons.append(
            "expected page not retrieved (got: "
            + ", ".join(dict.fromkeys(case.retrieval.retrieved))
            + ")"
        )
    if case.missing:
        reasons.append("missing: " + "; ".join(case.missing))
    if case.invalid_citations:
        reasons.append(f"invalid citations {case.invalid_citations}")
    if case.missing_tools:
        reasons.append("tools not called: " + ", ".join(case.missing_tools))
    if case.verdict and not case.verdict.error:
        if case.category == "unanswerable" and not case.verdict.admits_gap:
            reasons.append("didn't say the wiki doesn't cover it")
        elif case.category != "unanswerable" and (
            case.verdict.relevant < PASSING_SCORE
            or (case.category != "build" and case.verdict.grounded < PASSING_SCORE)
        ):
            v = case.verdict
            reasons.append(f"judge: grounded {v.grounded}, relevant {v.relevant} ({v.reason})")
    return "; ".join(reasons) or "failed"


def update_readme(readme: Path, markdown: str) -> bool:
    """Replace the block between the eval markers. Returns False if the markers are missing."""
    text = readme.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return False
    before, rest = text.split(README_START, 1)
    _, after = rest.split(README_END, 1)
    readme.write_text(f"{before}{README_START}\n{markdown}\n{README_END}{after}", encoding="utf-8")
    return True
