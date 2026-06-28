from types import SimpleNamespace

from apartment_hunter.core.models import Apartment
from apartment_hunter.storage import factory
from apartment_hunter.storage.vector_store import ChromaVectorStore


def test_storage_factory_selects_backends(mocker) -> None:
    mocker.patch("apartment_hunter.storage.sqlite_store.SQLiteStore", side_effect=lambda path: ("sqlite", path))
    mocker.patch("apartment_hunter.storage.connectors.file.FileStore", side_effect=lambda path: ("file", path))
    mocker.patch(
        "apartment_hunter.storage.connectors.postgres.PostgresStore", side_effect=lambda dsn: ("postgres", dsn)
    )
    mocker.patch(
        "apartment_hunter.storage.connectors.supabase_store.SupabaseStore",
        side_effect=lambda url, key: ("supabase", url, key),
    )
    mocker.patch("apartment_hunter.storage.connectors.firebase.FirebaseStore", side_effect=lambda path: ("firebase", path))
    mocker.patch(
        "apartment_hunter.storage.connectors.qdrant.QdrantVectorStore",
        side_effect=lambda url, key: ("qdrant", url, key),
    )
    mocker.patch("apartment_hunter.storage.vector_store.ChromaVectorStore", side_effect=lambda path: ("chroma", path))

    settings = SimpleNamespace(
        storage_backend="sqlite",
        vector_backend="qdrant",
        db_path="db.sqlite",
        json_path="data.json",
        postgres_dsn="postgres://dsn",
        supabase_url="url",
        supabase_key="key",
        firebase_cred_path="cred.json",
        qdrant_url="qdrant",
        qdrant_api_key="secret",
        chroma_path="chroma",
    )
    mocker.patch.object(factory, "get_settings", return_value=settings)
    assert factory.get_storage() == ("sqlite", "db.sqlite")
    assert factory.get_vector_store() == ("qdrant", "qdrant", "secret")

    settings.storage_backend = "unknown"
    settings.vector_backend = "unknown"
    assert factory.get_storage() == ("sqlite", "db.sqlite")
    assert factory.get_vector_store() == ("chroma", "chroma")


def test_chroma_vector_store_behaviour(mocker) -> None:
    collection = mocker.MagicMock()
    collection.count.return_value = 2
    client = mocker.MagicMock()
    client.get_or_create_collection.return_value = collection
    mocker.patch(
        "apartment_hunter.storage.vector_store.chromadb.PersistentClient",
        return_value=client,
    )

    store = ChromaVectorStore("tmp/chroma")
    apt = Apartment(
        source_id="krisha:1",
        source="krisha.kz",
        url="http://x",
        price=100000,
        title="Title",
        area_total=40,
        city="Алматы",
    )
    store.upsert(apt)
    collection.upsert.assert_called_once()

    collection.query.return_value = {"ids": [["krisha:1"]]}
    assert store.semantic_search("nice", n_results=10, where={"city": "Алматы"}) == ["krisha:1"]

    collection.query.side_effect = RuntimeError("boom")
    assert store.semantic_search("nice") == []

    store.delete("krisha:1")
    collection.delete.assert_called_once_with(ids=["krisha:1"])
    assert store.count == 2
