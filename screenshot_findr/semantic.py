"""Search by meaning: "shoes I wanted to buy" finds a product page that never says "shoes".

Uses a small local embedding model through `fastembed` (optional install:
`pip install -e ".[smart]"`). The model (~70 MB) downloads once on first use
and then runs offline on your machine.
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol, Sequence

import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
MAX_CHARS = 2000  # OCR text beyond this adds little meaning and slows embedding


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedder:
    def __init__(self, model: str = DEFAULT_MODEL):
        from fastembed import TextEmbedding

        self.name = model
        self._model = TextEmbedding(model)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return _normalize(np.array(list(self._model.embed([t[:MAX_CHARS] for t in texts]))))

    def embed_query(self, text: str) -> np.ndarray:
        # query_embed adds the model's "this is a search query" instruction when it has one
        return _normalize(np.array(list(self._model.query_embed(text))))[0]


def _normalize(m: np.ndarray) -> np.ndarray:
    m = m.astype(np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(norms, 1e-12)


def get_embedder(enabled: bool = True, model: str = DEFAULT_MODEL) -> Optional[Embedder]:
    """The embedder, or None when meaning search is off or fastembed isn't installed."""
    if not enabled:
        return None
    try:
        return FastEmbedder(model)
    except ImportError:
        return None
    except Exception as exc:  # e.g. the model couldn't be downloaded
        log.warning("Meaning search unavailable: %s", exc)
        return None


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def rank(query_vec: np.ndarray, rows: list[tuple[int, bytes]], limit: int,
         min_score: float) -> list[tuple[int, float]]:
    """Cosine-rank stored vectors against the query; returns (id, score) best first."""
    if not rows:
        return []
    ids = np.array([r[0] for r in rows])
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    scores = matrix @ query_vec.astype(np.float32)
    order = np.argsort(-scores)[:limit]
    return [(int(ids[i]), float(scores[i])) for i in order if scores[i] >= min_score]


def search_by_meaning(db, embedder: Embedder, query: str, *, tag: Optional[str] = None,
                      exclude: Sequence[int] = (), limit: int = 24,
                      min_score: float = 0.55) -> list:
    """Screenshots related in meaning to `query`, best first (skipping ids in `exclude`)."""
    if not query.strip():
        return []
    skip = set(exclude)
    rows = [r for r in db.embeddings(embedder.name, tag) if r[0] not in skip]
    hits = rank(embedder.embed_query(query), rows, limit, min_score)
    shots = db.get_many([sid for sid, _ in hits])
    for shot in shots:
        shot.match = "meaning"
    return shots
