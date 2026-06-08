import sys
import src.email_labeling.embed as em


def test_embed_names_empty_returns_none():
    assert em.embed_names([]) is None


def test_embed_names_falls_back_when_embeddings_unavailable(monkeypatch):
    em._client = None
    # Make `from src.embeddings import get_embedding_client` raise ImportError.
    monkeypatch.setitem(sys.modules, "src.embeddings", None)
    assert em.embed_names(["a", "b"]) is None
