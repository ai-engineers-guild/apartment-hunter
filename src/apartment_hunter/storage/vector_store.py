"""ChromaDB vector store for semantic apartment search."""

from __future__ import annotations

import logging
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from apartment_hunter.core.interfaces import VectorStore as VectorStoreABC
from apartment_hunter.core.models import Apartment

log = logging.getLogger(__name__)

_COLLECTION = "apartments"


class ChromaVectorStore(VectorStoreABC):
    """Thin wrapper around ChromaDB for semantic search over apartment descriptions."""

    def __init__(self, persist_dir: str) -> None:
        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._col = self._client.get_or_create_collection(
            name=_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            "ChromaDB initialized at %s  (%d documents)",
            persist_dir,
            self._col.count(),
        )

    def upsert(self, apt: Apartment) -> None:
        text = apt.to_embedding_text()
        if not text.strip():
            return
        meta = apt.to_search_metadata()
        # ChromaDB metadata values must be str | int | float | bool
        clean_meta = {}
        for k, v in meta.items():
            if isinstance(v, (str, int, float, bool)):
                clean_meta[k] = v
        self._col.upsert(
            ids=[apt.source_id],
            documents=[text],
            metadatas=[clean_meta],
        )

    def semantic_search(
        self,
        query: str,
        n_results: int = 10,
        where: dict | None = None,
    ) -> list[str]:
        """Search by natural language query. Returns source_ids ordered by relevance."""
        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": min(n_results, self._col.count() or 1),
        }
        if where:
            kwargs["where"] = where
        try:
            results = self._col.query(**kwargs)
        except Exception as exc:
            log.warning("ChromaDB query failed: %s", exc)
            return []
        ids = results.get("ids", [[]])[0]
        return ids

    def delete(self, source_id: str) -> None:
        try:
            self._col.delete(ids=[source_id])
        except Exception:
            pass

    @property
    def count(self) -> int:
        return self._col.count()
