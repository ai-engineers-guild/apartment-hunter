"""Tests for KrishaScraper async context manager and resource cleanup."""

import pytest

from apartment_hunter.adapters.krisha.scraper import KrishaScraper


@pytest.mark.asyncio
async def test_scraper_context_manager_closes_client() -> None:
    """Verify that async-with pattern properly closes the underlying client."""
    async with KrishaScraper(delay=0, timeout=5) as scraper:
        # Force client creation
        client = await scraper._get_client()
        assert not client.is_closed

    # After exiting, the client should be closed
    assert scraper._client is None


@pytest.mark.asyncio
async def test_scraper_context_manager_closes_on_exception() -> None:
    """Client must be closed even when an exception propagates out."""
    scraper = KrishaScraper(delay=0, timeout=5)
    try:
        async with scraper:
            await scraper._get_client()  # force creation
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert scraper._client is None


@pytest.mark.asyncio
async def test_scraper_close_is_idempotent() -> None:
    """Calling close() multiple times should not raise."""
    scraper = KrishaScraper(delay=0, timeout=5)
    await scraper.close()  # no client created yet
    await scraper.close()  # still no-op

    async with scraper:
        await scraper._get_client()

    await scraper.close()  # already closed by __aexit__
