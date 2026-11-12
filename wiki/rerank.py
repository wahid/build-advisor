"""A cross-encoder that rescores the hybrid search's best candidates.

The hybrid search ranks with vectors, keywords and titles, each blind to how well
a chunk answers the question as a whole. A cross-encoder reads the question and a
chunk together and scores the pair. It's too slow to run on every chunk, so it
reorders the first SEARCH_RERANK_POOL candidates; pinned pages (an attached
build's skills and items) stay first.

`blend` mode fuses the cross-encoder's order with the search's own (RRF), so a
strong keyword or title match isn't thrown away; `replace` trusts the
cross-encoder alone. The default model is small (22M parameters) so it fits next
to bge-m3 on a 4 GB server.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Protocol

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_PASSAGE_CHARS = 1500  # the model reads at most 512 tokens anyway
RRF_K = 60


class Reranker(Protocol):
    def scores(self, question: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str, device: str = "auto") -> None:
        self.model_name = model_name
        self.device = device
        self._model: Any = None

    @property
    def model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            device = None if self.device == "auto" else self.device
            self._model = CrossEncoder(self.model_name, device=device, max_length=512)
            logger.info("Loaded reranker %s", self.model_name)
        return self._model

    def scores(self, question: str, passages: list[str]) -> list[float]:
        pairs = [(question, p[:MAX_PASSAGE_CHARS]) for p in passages]
        return [float(s) for s in self.model.predict(pairs, show_progress_bar=False)]


@lru_cache(maxsize=1)
def get_reranker() -> Reranker:
    return CrossEncoderReranker(settings.SEARCH_RERANK_MODEL, device=settings.EMBEDDING_DEVICE)


def passage(title: str, section: str, text: str) -> str:
    heading = f"{title} > {section}" if section else title
    return f"{heading}\n{text.split(chr(10) * 2, 1)[-1]}"


def reorder(
    question: str,
    ids: list[int],
    passages: dict[int, str],
    reranker: Reranker,
    mode: str = "blend",
) -> list[int]:
    """The ids in their new order (best first)."""
    if len(ids) < 2:
        return ids
    scores = reranker.scores(question, [passages[i] for i in ids])
    by_model = [i for _, i in sorted(zip(scores, ids, strict=True), key=lambda p: -p[0])]
    if mode == "replace":
        return by_model
    fused: dict[int, float] = {}
    for order in (ids, by_model):
        for rank, chunk_id in enumerate(order, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
    return sorted(ids, key=lambda i: (-fused[i], ids.index(i)))
