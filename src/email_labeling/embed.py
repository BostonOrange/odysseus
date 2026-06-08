"""Adapter: embed label names via the app's fastembed client for the reconciler.

Returns ``None`` on any failure (missing fastembed, model load error, etc.) so
the reconciler degrades to string-only dedup instead of crashing the labeler.
"""
import logging

logger = logging.getLogger(__name__)

_client = None


def embed_names(names):
    """Return a list of float vectors for ``names``, or None on any failure."""
    global _client
    if not names:
        return None
    try:
        if _client is None:
            from src.embeddings import get_embedding_client
            _client = get_embedding_client()
        vecs = _client.encode(list(names))
        return [list(map(float, v)) for v in vecs]
    except Exception as e:
        logger.warning("embed_names failed (%s); reconciler will use string dedup", e)
        return None
