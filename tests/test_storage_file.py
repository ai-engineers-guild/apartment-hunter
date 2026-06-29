import tempfile
from datetime import UTC, datetime
from pathlib import Path

from apartment_hunter.core.models import Apartment, SearchProfile
from apartment_hunter.storage.connectors.file import FileStore


def test_filestore_upsert_and_get() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_db.json"
        store = FileStore(str(db_path))

        apt = Apartment(
            source_id="test:1",
            source="test",
            url="http://test.com/1",
            price=150000,
            rooms=2,
            area_total=50.5,
            city="Алматы",
            scraped_at=datetime(2023, 1, 1),
        )

        # First insert
        is_new = store.upsert_apartment(apt)
        assert is_new is True

        # Second insert (update)
        is_new_again = store.upsert_apartment(apt)
        assert is_new_again is False

        # Get
        retrieved = store.get_apartment("test:1")
        assert retrieved is not None
        assert retrieved.price == 150000


def test_filestore_search_apartments() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileStore(str(Path(tmpdir) / "test_db.json"))

        for i in range(5):
            apt = Apartment(
                source_id=f"test:{i}",
                source="test",
                url=f"http://test.com/{i}",
                price=100000 + i * 10000,
                rooms=i % 3 + 1,
                city="Алматы" if i % 2 == 0 else "Астана",
                scraped_at=datetime.now(UTC),
            )
            store.upsert_apartment(apt)

        # Search by city
        results_almaty = store.search_apartments(city="Алматы")
        assert len(results_almaty) == 3

        # Search by price and rooms
        results_filtered = store.search_apartments(city="Алматы", price_max=125000, rooms=[1, 2, 3])
        assert len(results_filtered) == 2  # test:0 (100k) and test:2 (120k)


def test_filestore_profiles() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileStore(str(Path(tmpdir) / "test_db.json"))

        profile = SearchProfile(
            name="Almaty Test",
            city="Алматы",
            price_max=200000,
        )

        store.save_profile(profile)

        # Get profile
        retrieved = store.get_profile(profile.id)
        assert retrieved is not None
        assert retrieved.name == "Almaty Test"

        # List profiles
        profiles = store.list_profiles()
        assert len(profiles) == 1

        # Delete profile
        deleted = store.delete_profile(profile.id)
        assert deleted is True
        assert len(store.list_profiles()) == 0


def test_filestore_existing_apartment_is_no_longer_marked_new() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileStore(str(Path(tmpdir) / "test_db.json"))
        apt = Apartment(
            source_id="test:existing",
            source="test",
            url="http://test.com/existing",
            price=150000,
            scraped_at=datetime.now(UTC),
        )

        assert store.upsert_apartment(apt) is True
        assert len(store.get_new_apartments()) == 1
        assert store.upsert_apartment(apt) is False
        assert store.get_apartment("test:existing") is not None
        assert store.get_apartment("test:existing").is_new is False


def test_filestore_upsert_does_not_mutate_apartment_object() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileStore(str(Path(tmpdir) / "test_db.json"))

        # Create an apartment with some initial values
        apt = Apartment(
            source_id="test:mutation",
            source="test",
            url="http://test.com/mutation",
            price=150000,
            scraped_at=datetime.now(UTC),
            is_new=True,
            llm_score=None,
        )

        # Insert first time
        store.upsert_apartment(apt)

        # Modify the DB record directly to simulate LLM analysis
        store.data["apartments"]["test:mutation"]["llm_score"] = 8.5
        store._save()

        # Upsert the same object again (which doesn't have llm_score set and has is_new=True)
        store.upsert_apartment(apt)

        # The original object should remain unmodified
        assert apt.is_new is True
        assert apt.llm_score is None

        # But the DB should have preserved the LLM score and set is_new=False
        db_apt = store.get_apartment("test:mutation")
        assert db_apt is not None
        assert db_apt.is_new is False
        assert db_apt.llm_score == 8.5
