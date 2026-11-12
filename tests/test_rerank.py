"""The optional cross-encoder reranker and the eval history."""

from datetime import date

import pytest

from advisor import evalhistory
from wiki.indexing import build_chunks, embed_pending
from wiki.rerank import reorder
from wiki.search import hybrid_search

from .factories import FakeEmbedder, make_document


class FakeReranker:
    """Scores a passage by how often it says 'ignite'."""

    def __init__(self):
        self.calls = 0

    def scores(self, question, passages):
        self.calls += 1
        return [p.lower().count("ignite") for p in passages]


def test_replace_trusts_the_model_and_blend_keeps_the_search_order_in_play() -> None:
    passages = {1: "poison", 2: "ignite", 3: "ignite ignite"}

    assert reorder("q", [1, 2, 3], passages, FakeReranker(), mode="replace") == [3, 2, 1]
    # Blend: 1 and 3 are first in one order and last in the other, which RRF scores a
    # little above second in both (2); the tie between 1 and 3 keeps the search order.
    assert reorder("q", [1, 2, 3], passages, FakeReranker(), mode="blend") == [1, 3, 2]
    assert reorder("q", [7], {7: "x"}, FakeReranker()) == [7]


@pytest.mark.django_db
def test_the_search_reorders_unpinned_hits_only(settings) -> None:
    settings.SEARCH_RERANK_MODE = "replace"
    make_document("Poison", "Poison\n\nPoison deals chaos damage over time.")
    make_document("Ignite", "Ignite\n\nIgnite deals fire damage over time. Ignite ignite.")
    make_document("Burning", "Burning\n\nBurning damage over time, ignite.")
    build_chunks()
    embedder = FakeEmbedder()
    embed_pending(embedder)
    reranker = FakeReranker()

    hits = hybrid_search(
        "damage over time", embedder=embedder, rerank=True, reranker=reranker, pinned=["Poison"]
    )

    titles = [h.title for h in hits]
    assert titles[0] == "Poison"  # pinned stays first
    assert titles.index("Ignite") < titles.index("Burning")
    assert "rerank" in hits[1].ranks and "rerank" not in hits[0].ranks
    assert reranker.calls == 1
    hybrid_search("damage over time", embedder=embedder, rerank=False, reranker=reranker)
    assert reranker.calls == 1  # off: never called


def test_eval_runs_are_recorded_and_read_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GIT_COMMIT", "abc1234")
    path = tmp_path / "history.jsonl"
    summary = {"cases": 55, "hit@8": 0.98181, "mrr": 0.85, "recall@8": 0.97}

    row = evalhistory.entry(summary, "Reranker", "retrieval only", when=date(2026, 11, 12))
    evalhistory.append(row, path)
    path.open("a").write("not json\n")
    evalhistory.append({**row, "label": "Second", "experiment": True}, path)

    runs = evalhistory.load(path)
    assert [r["label"] for r in runs] == ["Reranker", "Second"]
    assert runs[0]["commit"] == "abc1234" and runs[0]["hit@8"] == 0.982
    assert runs[0]["pass_rate"] is None and runs[1]["experiment"] is True
    assert evalhistory.load(tmp_path / "missing.jsonl") == []


def test_settings_are_read_from_the_eval_meta_line() -> None:
    meta = (
        "_2026-11-12, patch 3.29.3c, 3.29.3d, 2952 wiki pages, 27377 chunks, query rewriting, "
        "retrieval only, 5 PoB/web cases skipped._"
    )
    assert evalhistory.config_from_meta(meta) == "query rewriting, retrieval only"
