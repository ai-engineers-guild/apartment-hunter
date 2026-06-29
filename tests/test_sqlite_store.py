from datetime import UTC, datetime, timedelta

from apartment_hunter.core.models import Apartment, SearchProfile
from apartment_hunter.storage.sqlite_store import SQLiteStore


def _apt(source_id: str, **overrides) -> Apartment:
    base = {
        "source_id": source_id,
        "source": "krisha.kz",
        "url": f"http://example/{source_id}",
        "price": 200000,
        "rooms": 2,
        "city": "Алматы",
        "district": "Бостандыкский",
        "area_total": 50.0,
        "owner_type": "собственник",
        "scraped_at": datetime.now(UTC),
    }
    base.update(overrides)
    return Apartment(**base)


def test_sqlite_store_roundtrip_and_filters(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "apartments.db"))
    first = _apt("krisha:1", llm_score=8.4, llm_pros=["ремонт"], llm_cons=["шум"])
    second = _apt("krisha:2", price=260000, rooms=3, city="Астана", owner_type="агент")

    assert store.upsert_apartment(first) is True
    assert store.upsert_apartment(first) is False
    assert store.upsert_apartment(second) is True

    loaded = store.get_apartment("krisha:1")
    assert loaded is not None
    assert loaded.llm_pros == ["ремонт"]
    assert loaded.is_new is False

    results = store.search_apartments(
        city="Алматы",
        rooms=[2],
        price_max=220000,
        area_min=45,
        area_max=60,
        min_score=8,
        district="Бостандык",
        owner_only=True,
    )
    assert [apt.source_id for apt in results] == ["krisha:1"]

    top = store.get_top_apartments(limit=1, city="Алматы")
    assert [apt.source_id for apt in top] == ["krisha:1"]


def test_sqlite_store_profiles_history_notifications_and_stats(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "apartments.db"))
    apt = _apt(
        "krisha:3",
        scraped_at=datetime.now(UTC) - timedelta(hours=1),
        llm_score=7.5,
        city="Алматы",
    )
    store.upsert_apartment(apt)
    store.record_price("krisha:3", 200000)
    store.record_price("krisha:3", 200000)
    history = store.get_price_history("krisha:3")
    assert len(history) == 1

    profile = SearchProfile(name="Almaty", city="Алматы", created_at=datetime.now(UTC))
    store.save_profile(profile)
    assert store.get_profile(profile.id) is not None
    assert len(store.list_profiles()) == 1
    assert len(store.get_new_apartments(since_hours=24)) == 1

    store.mark_notified("krisha:3", profile.id, "telegram")
    assert store.was_notified("krisha:3", profile.id, "telegram") is True

    store.update_analysis(
        "krisha:3",
        llm_summary="good",
        llm_score=9.1,
        llm_renovation_quality="fresh",
        llm_pros=["вид"],
        llm_cons=["дорого"],
        llm_visual_description="светло",
    )
    updated = store.get_apartment("krisha:3")
    assert updated is not None
    assert updated.llm_visual_description == "светло"

    stats = store.get_stats()
    assert stats["total_apartments"] == 1
    assert stats["active_profiles"] == 1
    assert stats["top_cities"] == {"Алматы": 1}

    assert store.delete_profile(profile.id) is True
    assert store.delete_profile(profile.id) is False


def test_sqlite_store_existing_apartment_is_marked_not_new(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "apartments.db"))
    apt = _apt("krisha:repeat")

    assert store.upsert_apartment(apt) is True
    assert [row.source_id for row in store.get_new_apartments()] == ["krisha:repeat"]
    assert store.upsert_apartment(apt) is False

    loaded = store.get_apartment("krisha:repeat")
    assert loaded is not None
    assert loaded.is_new is False


def test_sqlite_store_parameterized_limits(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "apartments.db"))

    # Insert 10 apartments
    for i in range(10):
        store.upsert_apartment(_apt(f"krisha:{i}", price=100000 + i * 1000))

    # search_apartments limit
    results_limit_3 = store.search_apartments(limit=3)
    assert len(results_limit_3) == 3

    results_limit_all = store.search_apartments(limit=20)
    assert len(results_limit_all) == 10

    # get_new_apartments limit
    new_limit_2 = store.get_new_apartments(limit=2)
    assert len(new_limit_2) == 2

    new_limit_all = store.get_new_apartments(limit=20)
    assert len(new_limit_all) == 10
