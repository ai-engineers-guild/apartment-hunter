"""Tests for KrishaScraper async context manager and resource cleanup."""

import pytest

from apartment_hunter.adapters.krisha.scraper import KrishaScraper


@pytest.mark.asyncio
async def test_scraper_context_manager_closes_client() -> None:
    """Verify that async-with pattern properly closes the underlying browser."""
    async with KrishaScraper(delay=0, timeout=5) as scraper:
        # Force client creation
        await scraper._init_browser()
        assert scraper._playwright is not None
        assert scraper._browser is not None

    # After exiting, the resources should be closed
    assert scraper._playwright is None
    assert scraper._browser is None


@pytest.mark.asyncio
async def test_scraper_context_manager_closes_on_exception() -> None:
    """Browser must be closed even when an exception propagates out."""
    scraper = KrishaScraper(delay=0, timeout=5)
    try:
        async with scraper:
            await scraper._init_browser()  # force creation
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert scraper._playwright is None
    assert scraper._browser is None


@pytest.mark.asyncio
async def test_scraper_close_is_idempotent() -> None:
    """Calling close() multiple times should not raise."""
    scraper = KrishaScraper(delay=0, timeout=5)
    await scraper.close()  # no client created yet
    await scraper.close()  # still no-op

    async with scraper:
        await scraper._init_browser()

    await scraper.close()  # already closed by __aexit__
