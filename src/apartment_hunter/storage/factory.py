"""Factory to instantiate storage and vector backends based on configuration."""

from __future__ import annotations

import logging

from apartment_hunter.config import get_settings
from apartment_hunter.core.interfaces import StorageBackend, VectorStore
from apartment_hunter.storage.connectors.file import FileStore
from apartment_hunter.storage.connectors.firebase import FirebaseStore
from apartment_hunter.storage.connectors.postgres import PostgresStore
from apartment_hunter.storage.connectors.qdrant import QdrantVectorStore
from apartment_hunter.storage.connectors.supabase_store import SupabaseStore
from apartment_hunter.storage.sqlite_store import SQLiteStore
from apartment_hunter.storage.vector_store import ChromaVectorStore

log = logging.getLogger(__name__)


def get_storage() -> StorageBackend:
    """Instantiate the primary storage backend."""
    settings = get_settings()
    backend = settings.storage_backend.lower()

    if backend == "sqlite":
        return SQLiteStore(settings.db_path)
    elif backend == "file":
        return FileStore(settings.json_path)
    elif backend == "postgres":
        return PostgresStore(settings.postgres_dsn)
    elif backend == "supabase":
        return SupabaseStore(settings.supabase_url, settings.supabase_key)
    elif backend == "firebase":
        return FirebaseStore(settings.firebase_cred_path)
    else:
        log.warning("Unknown storage backend '%s', falling back to SQLite", backend)
        return SQLiteStore(settings.db_path)


def get_vector_store() -> VectorStore:
    """Instantiate the vector storage backend."""
    settings = get_settings()
    backend = settings.vector_backend.lower()

    if backend == "qdrant":
        return QdrantVectorStore(settings.qdrant_url, settings.qdrant_api_key)
    elif backend == "chroma":
        return ChromaVectorStore(settings.chroma_path)
    else:
        log.warning("Unknown vector backend '%s', falling back to ChromaDB", backend)
        return ChromaVectorStore(settings.chroma_path)
