import sys
import types

from wiki.embeddings import SentenceTransformerEmbedder


class FakeVector(list):
    """Mimics a numpy row: has .tolist()."""

    def tolist(self) -> list[float]:
        return list(self)


def test_sentence_transformer_embedder_normalises_and_lazy_loads(monkeypatch) -> None:
    loaded: list[tuple[str, str | None]] = []

    class FakeModel:
        device = "cpu"

        def __init__(self, name: str, device: str | None = None) -> None:
            loaded.append((name, device))

        def encode(self, texts, **kwargs):
            assert kwargs["normalize_embeddings"] is True
            assert kwargs["batch_size"] == 8
            return [FakeVector([1.0, 1.0, 1.0]) for _ in texts]

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    embedder = SentenceTransformerEmbedder("BAAI/bge-m3", device="auto", batch_size=8)
    assert loaded == []

    assert embedder.embed_documents(["a", "b"]) == [[1.0, 1.0, 1.0]] * 2
    assert embedder.embed_query("q") == [1.0, 1.0, 1.0]
    assert loaded == [("BAAI/bge-m3", None)]


def test_explicit_device_is_passed_through(monkeypatch) -> None:
    devices: list[str | None] = []

    class FakeModel:
        device = "cuda"

        def __init__(self, name: str, device: str | None = None) -> None:
            devices.append(device)

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    _ = SentenceTransformerEmbedder("m", device="cuda").model
    assert devices == ["cuda"]
