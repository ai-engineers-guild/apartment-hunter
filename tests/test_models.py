"""Tests for core domain models."""

from datetime import UTC, datetime

from apartment_hunter.core.models import Apartment, SearchProfile


def test_apartment_creation_and_card() -> None:
    """Test apartment creation and markdown card generation."""
    apt = Apartment(
        source_id="test:1",
        source="test",
        url="http://test.com/1",
        price=150000,
        rooms=2,
        area_total=50.5,
        city="Алматы",
        address="Абая 1",
        district="Алмалинский",
        scraped_at=datetime(2023, 1, 1, tzinfo=UTC),
    )
    assert apt.source_id == "test:1"
    assert apt.price_per_sqm == int(150000 / 50.5)

    card = apt.to_card()
    assert "150 000" in card
    assert "Алматы" in card or "Абая 1" in card
    assert "2 комн" in card


def test_search_profile_matching() -> None:
    """Test search profile matching logic."""
    profile = SearchProfile(
        name="Test",
        city="Алматы",
        price_max=200000,
        rooms=[1, 2],
        owner_only=True,
        has_photo=False,
    )

    apt_match = Apartment(
        source_id="krisha:1",
        source="krisha",
        url="http://krisha.kz/1",
        price=180000,
        rooms=2,
        city="Алматы",
        scraped_at=datetime.now(UTC),
        owner_type="Хозяин недвижимости",
    )
    assert profile.matches(apt_match) is True

    apt_wrong_city = Apartment(
        source_id="krisha:2",
        source="krisha",
        url="http://krisha.kz/2",
        price=180000,
        rooms=2,
        city="Астана",
        scraped_at=datetime.now(UTC),
        owner_type="Хозяин недвижимости",
    )
    assert profile.matches(apt_wrong_city) is False

    apt_expensive = Apartment(
        source_id="krisha:3",
        source="krisha",
        url="http://krisha.kz/3",
        price=250000,
        rooms=2,
        city="Алматы",
        scraped_at=datetime.now(UTC),
        owner_type="Хозяин недвижимости",
    )
    assert profile.matches(apt_expensive) is False

    apt_agency = Apartment(
        source_id="krisha:4",
        source="krisha",
        url="http://krisha.kz/4",
        price=180000,
        rooms=2,
        city="Алматы",
        scraped_at=datetime.now(UTC),
        owner_type="Крыша Агент",
    )
    assert profile.matches(apt_agency) is False
