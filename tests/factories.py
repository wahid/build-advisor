"""Shared test helpers: documents and a deterministic fake embedder."""

from django.utils import timezone

from wiki.ingest import content_hash
from wiki.models import Document, DocumentType, Source

DIMS = 1024


def _one_hot(text: str) -> list[float]:
    """A distinct, non-zero unit vector per text."""
    vector = [0.0] * DIMS
    vector[int(content_hash(text)[:8], 16) % DIMS] = 1.0
    return vector


class FakeEmbedder:
    def __init__(self, model_name: str = "fake-model") -> None:
        self.model_name = model_name
        self.calls: list[list[str]] = []
        self.query_vector: list[float] | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [_one_hot(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        if self.query_vector is not None:
            return self.query_vector
        return self.embed_documents([text])[0]


def make_document(
    title: str = "Righteous Fire",
    text: str | None = None,
    doc_type: str = DocumentType.GEM,
) -> Document:
    text = text or (
        "Intro paragraph about the skill and what it does.\n\n"
        "## Mechanics\n\nBurns for a percentage of maximum life every second.\n\n"
        "## Version history\n\nAdded in 0.11.0 and changed many times since then."
    )
    source = Source.objects.create(
        page_title=title,
        url=f"https://wiki.test/wiki/{title.replace(' ', '_')}",
        revision_id=1,
        fetched_at=timezone.now(),
    )
    return Document.objects.create(
        source=source,
        title=title,
        doc_type=doc_type,
        raw_text=text,
        patch="3.29.3c",
        content_hash=content_hash(text),
    )


def vector_for(text: str) -> list[float]:
    """The fake embedding of a chunk text, e.g. to aim a query at one chunk."""
    return _one_hot(text)
