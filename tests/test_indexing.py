import pytest
from django.utils import timezone

from wiki.indexing import build_chunks, embed_pending
from wiki.ingest import content_hash
from wiki.models import Chunk, Document, DocumentType, Source

pytestmark = pytest.mark.django_db

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

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [_one_hot(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def make_document(title: str = "Righteous Fire", text: str | None = None) -> Document:
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
        doc_type=DocumentType.GEM,
        raw_text=text,
        patch="3.29.3c",
        content_hash=content_hash(text),
    )


def test_build_chunks_copies_metadata() -> None:
    doc = make_document()

    result = build_chunks()

    assert (result.documents, result.chunks) == (1, 3)
    chunk = Chunk.objects.get(document=doc, section="Mechanics")
    assert chunk.doc_type == DocumentType.GEM
    assert chunk.patch == "3.29.3c"
    assert chunk.url == "https://wiki.test/wiki/Righteous_Fire"
    assert chunk.text_hash == content_hash(chunk.text)
    doc.refresh_from_db()
    assert doc.chunked_hash == doc.content_hash


def test_unchanged_documents_are_skipped() -> None:
    make_document()
    build_chunks()

    assert build_chunks().documents == 0
    assert build_chunks(force=True).documents == 1


def test_embed_pending_embeds_in_batches() -> None:
    make_document()
    make_document("Fire Trap")
    build_chunks()
    embedder = FakeEmbedder()

    assert embed_pending(embedder, batch_size=4) == 6

    assert [len(c) for c in embedder.calls] == [4, 2]
    assert not Chunk.objects.filter(embedding=None).exists()
    assert set(Chunk.objects.values_list("embedding_model", flat=True)) == {"fake-model"}
    assert embed_pending(embedder) == 0


def test_embed_pending_respects_limit() -> None:
    make_document()
    build_chunks()

    assert embed_pending(FakeEmbedder(), limit=2) == 2
    assert Chunk.objects.filter(embedding=None).count() == 1


def test_editing_one_section_reuses_other_embeddings() -> None:
    doc = make_document()
    build_chunks()
    embed_pending(FakeEmbedder())

    new_text = doc.raw_text.replace("every second", "every second while active")
    Document.objects.filter(pk=doc.pk).update(
        raw_text=new_text, content_hash=content_hash(new_text)
    )
    result = build_chunks()

    assert result.reused_embeddings == 2
    embedder = FakeEmbedder()
    assert embed_pending(embedder) == 1
    assert "while active" in embedder.calls[0][0]


def test_new_model_triggers_re_embedding() -> None:
    make_document()
    build_chunks()
    embed_pending(FakeEmbedder("old-model"))

    assert embed_pending(FakeEmbedder("new-model")) == 3


def test_vector_search_finds_nearest_chunk() -> None:
    from pgvector.django import CosineDistance

    make_document()
    build_chunks()
    embed_pending(FakeEmbedder())
    target = Chunk.objects.get(section="Mechanics")

    nearest = Chunk.objects.order_by(CosineDistance("embedding", target.embedding)).first()

    assert nearest == target
