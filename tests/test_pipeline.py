"""Tests for the IngestPipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from apartment_hunter.ingest.pipeline import IngestPipeline
from apartment_hunter.core.models import SearchProfile, Apartment


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
    
    # Patch the adapter registry in pipeline
    mocker.patch("apartment_hunter.ingest.pipeline._ADAPTERS", {"krisha.kz": lambda delay, timeout: mock_adapter})

    pipeline = IngestPipeline(db=mock_db, vector=mock_vector, notifiers=[mock_notifier], analyze=False)
    
    profile = SearchProfile(name="test", city="Алматы")
    new_apts = await pipeline.run_profile(profile)

    assert len(new_apts) == 1
    
    mock_db.upsert_apartment.assert_called_once()
    mock_vector.upsert.assert_called_once()
    
    # Notify should be called because it matches the empty profile
    mock_notifier.notify.assert_called_once()
    mock_db.mark_notified.assert_called_once()
