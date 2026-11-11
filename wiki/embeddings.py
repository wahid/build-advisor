"""Embedding backends.

Production uses `bge-m3` through sentence-transformers. The import is lazy so
the web app and the test suite don't need torch installed.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Protocol

from django.conf import settings

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    model_name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str = "auto", batch_size: int = 32) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model: Any = None

    @property
    def model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - depends on install
                raise RuntimeError(
                    "sentence-transformers is not installed; run `uv sync --extra cpu` "
                    "or `uv sync --extra cuda`."
                ) from exc
            device = None if self.device == "auto" else self.device
            self._model = SentenceTransformer(self.model_name, device=device)
            logger.info("Loaded %s on %s", self.model_name, self._model.device)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        # bge-m3 needs no query instruction prefix.
        return self.embed_documents([text])[0]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return SentenceTransformerEmbedder(
        model_name=settings.EMBEDDING_MODEL,
        device=settings.EMBEDDING_DEVICE,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
    )
