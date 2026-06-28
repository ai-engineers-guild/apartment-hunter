"""Generate text embeddings for semantic search using sentence-transformers."""

from __future__ import annotations

import logging
from typing import Any

from apartment_hunter.config import get_settings

log = logging.getLogger(__name__)


class EmbeddingEngine:
    """Wrapper around sentence-transformers to generate dense vectors."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._model: Any = None  # Lazy loading

    def _load_model(self) -> None:
        if self._model is None:
            log.info("Loading embedding model: %s", self._settings.embedding_model)
            # Import here to avoid slow startup for components that don't need it
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._settings.embedding_model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts. Returns list of vectors."""
        if not texts:
            return []

        self._load_model()
        try:
            # model.encode returns numpy array by default, we need pure floats
            embeddings = self._model.encode(texts, show_progress_bar=False)
            return embeddings.tolist()
        except Exception as exc:
            log.error("Embedding generation failed: %s", exc)
            return [[] for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query."""
        results = self.embed([query])
        return results[0] if results and results[0] else []
