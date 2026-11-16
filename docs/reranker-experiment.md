# The reranker I tried and turned off

A short account of one experiment on build-advisor's search: what I expected, what
the numbers said, and why the feature ships switched off.

## The idea

The app answers Path of Exile questions from wiki pages. Search is hybrid: vector
similarity, Postgres full-text search and page-title matches, merged with
reciprocal rank fusion (RRF). Each of those lists is blind to how well a chunk
answers the question as a whole.

The standard next step in a RAG pipeline is a cross-encoder reranker: a small model
that reads the question and one chunk together and scores the pair. It's too slow
to run on every chunk, so it reorders the best candidates. I expected the right
page to move up.

## The setup

- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (22M parameters), chosen because the
  demo runs on a 4 GB server next to the bge-m3 embedding model.
- It rescores the top 30 candidates of the hybrid search. Pages pinned by an
  attached build stay first.
- Two modes: the cross-encoder's order alone ("replace"), or fused with the search's
  own order by RRF ("blend").
- Measured on the project's evaluation set: 55 questions with the wiki pages that
  should be found. Retrieval only, query rewriting off, so runs are comparable (the
  rewriting step calls an LLM and varies from run to run).

## The result

| Setup | Right page in top 8 | Mean reciprocal rank | Time per search |
|---|---|---|---|
| Hybrid search (baseline) | 96% | 0.88 | 0.19 s |
| + reranker, blended | 98% | 0.85 | 1.09 s |
| + reranker, alone | 98% | 0.76 | 1.09 s |

The reranker found one page the search had missed (an indirect question about energy
shield recharge). But it pushed the best page down more often than up: mean
reciprocal rank fell, a lot when it was trusted alone. And every search took about
0.9 seconds longer on CPU.

Looking at the cases that got worse, the pattern was clear. The hybrid search's
title match is a strong signal in this domain: a question about "Grace" should rank
the Grace page first. A general-purpose cross-encoder trained on web search queries
doesn't know that; it preferred longer passages that talk around the topic.

## The decision

Off by default (`SEARCH_RERANK=false`). One extra hit in 55 doesn't pay for a lower
rank of the best page and a second of latency, and query rewriting, which is on in
production, already closes the gap: with it the current setup finds the right page
for 100% of the cases at 0.89 mean reciprocal rank.

The code stays in (`wiki/rerank.py`), and the experiment is recorded in
`evals/history.jsonl` and shown on the app's How it works page as "not kept".

## What I'd try next

- A reranker trained or fine-tuned on this domain, or a larger multilingual one
  (bge-reranker-v2-m3) on a server with a GPU.
- Reranking only when the search is unsure, e.g. when no title matched.
- A bigger evaluation set: 55 cases can't resolve differences of a point or two.

## What I took from it

The useful part wasn't the reranker; it was having an evaluation set that could say
no. Without it, "add a reranker" would have shipped as an obvious improvement.
