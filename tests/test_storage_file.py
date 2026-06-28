"""Tests for the local JSON FileStore."""

import tempfile
from pathlib import Path
from datetime import datetime

from apartment_hunter.storage.connectors.file import FileStore
from apartment_hunter.core.models import Apartment, SearchProfile


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
                scraped_at=datetime.utcnow(),
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
