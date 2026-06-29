from unittest.mock import AsyncMock

import pytest

from apartment_hunter.core.models import Apartment, SearchProfile
from apartment_hunter.ingest.pipeline import IngestPipeline


@pytest.fixture
def mock_db(mocker):
    db = mocker.MagicMock()
    # Mock upsert_apartment to always return True (new apartment)
    db.upsert_apartment.return_value = True
    db.was_notified.return_value = False
    return db


@pytest.fixture
def mock_vector(mocker):
    return mocker.MagicMock()


@pytest.fixture
def mock_notifier(mocker):
    notifier = mocker.MagicMock()
    notifier.channel_name = "test_channel"
    notifier.notify = AsyncMock(return_value=True)
    return notifier


@pytest.mark.asyncio
async def test_pipeline_run_profile(mocker, mock_db, mock_vector, mock_notifier):
    # Mock the adapter to return 1 apartment
    mock_adapter = mocker.MagicMock()
    apt = Apartment(source_id="krisha:1", source="krisha", price=100, rooms=1, url="http://x")
    mock_adapter.fetch_listings = AsyncMock(return_value=[apt])

    pipeline = IngestPipeline(
        db=mock_db,
        vector=mock_vector,
        notifiers=[mock_notifier],
        analyze=False,
        adapters={"krisha.kz": lambda delay, timeout: mock_adapter},
    )

    profile = SearchProfile(name="test", city="Алматы")
    new_apts = await pipeline.run_profile(profile)

    assert len(new_apts) == 1

    mock_db.upsert_apartment.assert_called_once()
    mock_vector.upsert.assert_called_once()

    # Notify should be called because it matches the empty profile
    mock_notifier.notify.assert_called_once()
    mock_db.mark_notified.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_handles_missing_and_failing_sources(mocker, mock_db, mock_vector) -> None:
    ok_adapter = mocker.MagicMock()
    ok_adapter.fetch_listings = AsyncMock(
        return_value=[Apartment(source_id="krisha:2", source="krisha", price=100, url="http://x")]
    )
    bad_adapter = mocker.MagicMock()
    bad_adapter.fetch_listings = AsyncMock(side_effect=RuntimeError("boom"))

    pipeline = IngestPipeline(
        db=mock_db,
        vector=mock_vector,
        analyze=False,
        adapters={
            "krisha.kz": lambda delay, timeout: ok_adapter,
            "other": lambda delay, timeout: bad_adapter,
        },
    )

    profile = SearchProfile(name="test", sources=["krisha.kz", "missing", "other"])

    new_apts = await pipeline.run_profile(profile)

    assert len(new_apts) == 1
    ok_adapter.fetch_listings.assert_awaited_once()
    bad_adapter.fetch_listings.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_analysis_and_notifications_are_resilient(mocker, mock_db, mock_vector, mock_notifier) -> None:
    first = Apartment(
        source_id="krisha:10",
        source="krisha",
        price=120000,
        rooms=2,
        url="http://x/10",
        photo_urls=["http://img/1.jpg"],
    )
    second = Apartment(
        source_id="krisha:11",
        source="krisha",
        price=130000,
        rooms=2,
        url="http://x/11",
    )

    adapter = mocker.MagicMock()
    adapter.fetch_listings = AsyncMock(return_value=[first, second])
    mock_db.upsert_apartment.side_effect = [True, True, False, False]
    mock_vector.upsert.side_effect = [
        RuntimeError("vector insert"),
        None,
        None,
        RuntimeError("vector reindex"),
    ]

    analyzer = mocker.MagicMock()
    analyzer.analyze = AsyncMock(
        side_effect=[
            mocker.MagicMock(
                score=8.0,
                summary="good",
                pros=["ремонт"],
                cons=["шум"],
                renovation_quality="fresh",
            ),
            RuntimeError("llm"),
        ]
    )
    vision = mocker.MagicMock()
    vision.analyze_photos = AsyncMock(side_effect=[RuntimeError("vision")])
    mock_db.was_notified.side_effect = [False, True]

    pipeline = IngestPipeline(
        db=mock_db,
        vector=mock_vector,
        notifiers=[mock_notifier],
        analyze=False,
        adapters={"krisha.kz": lambda delay, timeout: adapter},
    )
    pipeline.analyzer = analyzer
    pipeline.vision_analyzer = vision

    profile = SearchProfile(name="test", min_score=7)
    new_apts = await pipeline.run_profile(profile)

    assert [apt.source_id for apt in new_apts] == ["krisha:10", "krisha:11"]
    assert first.llm_score == 8.0
    assert first.llm_summary == "good"
    assert second.llm_score is None
    assert mock_db.record_price.call_count == 2
    assert mock_vector.upsert.call_count == 3
    mock_notifier.notify.assert_called_once_with(first, profile)
    mock_db.mark_notified.assert_called_once_with("krisha:10", profile.id, "test_channel")


@pytest.mark.asyncio
async def test_pipeline_run_all_profiles_returns_counts(mocker, mock_db, mock_vector) -> None:
    profiles = [SearchProfile(name="A"), SearchProfile(name="B")]
    mock_db.list_profiles.return_value = profiles

    pipeline = IngestPipeline(db=mock_db, vector=mock_vector, analyze=False, adapters={})
    mocker.patch.object(
        pipeline,
        "run_profile",
        side_effect=[[Apartment(source_id="1", source="s", price=1, url="u")], []],
    )

    results = await pipeline.run_all_profiles()

    assert results == {"A": 1, "B": 0}
