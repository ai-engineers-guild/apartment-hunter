"""Qdrant vector store backend for semantic search."""

from __future__ import annotations

import logging

from apartment_hunter.core.interfaces import VectorStore as VectorStoreABC
from apartment_hunter.core.models import Apartment

log = logging.getLogger(__name__)


class QdrantVectorStore(VectorStoreABC):
    """Qdrant-backed vector store for semantic search."""

    def __init__(self, url: str | None, api_key: str | None) -> None:
        if not url:
            raise ValueError("qdrant_url must be set when using qdrant backend")
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
        except ImportError:
            raise ImportError(
                "qdrant-client is required for QdrantVectorStore. Run: pip install qdrant-client"
            )

        self.client = QdrantClient(url=url, api_key=api_key)
        self.collection_name = "apartments"

        # Initialize collection if not exists
        try:
            if not self.client.collection_exists(self.collection_name):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )
                log.info("Qdrant collection '%s' created.", self.collection_name)
        except Exception as e:
            log.error("Failed to check or create Qdrant collection: %s", e)

    def upsert(self, apt: Apartment) -> None:
        from qdrant_client.models import PointStruct

        from apartment_hunter.analysis.embeddings import EmbeddingEngine

        text = apt.to_embedding_text()
        if not text.strip():
            return

        # Get embedding vector
        engine = EmbeddingEngine()
        vector = engine.embed_query(text)
        if not vector:
            return

        meta = apt.to_search_metadata()
        clean_meta = {
            k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))
        }

        try:
            # We need a numeric or UUID ID for Qdrant, source_id might be "krisha:123"
            # We'll use uuid5 based on source_id to be deterministic
            import uuid

            point_id = str(uuid.uuid5(uuid.NAMESPACE_OID, apt.source_id))

            point = PointStruct(
                id=point_id,
                vector=vector,
                payload={"source_id": apt.source_id, "text": text, **clean_meta},
            )
            self.client.upsert(collection_name=self.collection_name, points=[point])
        except Exception as e:
            log.error("Failed to upsert to Qdrant: %s", e)

    def semantic_search(
        self, query: str, n_results: int = 10, where: dict | None = None
    ) -> list[str]:
        """Search by natural language query. Returns source_ids."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from apartment_hunter.analysis.embeddings import EmbeddingEngine

        engine = EmbeddingEngine()
        vector = engine.embed_query(query)
        if not vector:
            return []

        query_filter = None
        if where:
            # Simple conversion of Chroma where clauses to Qdrant FieldCondition
            # e.g., {"city": {"$eq": "Алматы"}} -> Filter(must=[FieldCondition(key="city", match=MatchValue(value="Алматы"))])
            # For this basic implementation, we support simple equals matches
            conditions = []
            for key, val in where.items():
                if isinstance(val, dict) and "$eq" in val:
                    conditions.append(
                        FieldCondition(key=key, match=MatchValue(value=val["$eq"]))
                    )
            if conditions:
                query_filter = Filter(must=conditions)

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=vector,
                query_filter=query_filter,
                limit=n_results,
            )
            return [
                hit.payload["source_id"]
                for hit in results
                if hit.payload and "source_id" in hit.payload
            ]
        except Exception as e:
            log.error("Qdrant search failed: %s", e)
            return []

    def delete(self, source_id: str) -> None:
        import uuid

        from qdrant_client.models import PointIdsList

        try:
            point_id = str(uuid.uuid5(uuid.NAMESPACE_OID, source_id))
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=[point_id]),
            )
        except Exception as e:
            log.error("Failed to delete from Qdrant: %s", e)
