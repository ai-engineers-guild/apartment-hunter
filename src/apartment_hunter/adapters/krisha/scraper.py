"""Async HTTP client for Krisha.kz with retry logic and rate limiting."""

from __future__ import annotations

import asyncio
import logging
import random

import httpx

log = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
}

_RETRY_DELAYS = (5, 15, 60, 300)


class KrishaScraper:
    """Async HTTP scraper with retry, rate-limiting, and jitter."""

    def __init__(
        self,
        delay: float = 2.0,
        timeout: int = 20,
        max_retries: int = 3,
    ) -> None:
        self._delay = delay
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_DEFAULT_HEADERS,
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True,
            )
        return self._client

    async def fetch(self, url: str) -> str | None:
        """Fetch a URL and return the response text, or None on failure."""
        client = await self._get_client()
        for attempt in range(self._max_retries):
            try:
                log.debug("GET %s (attempt %d)", url, attempt + 1)
                resp = await client.get(url)
                resp.raise_for_status()
                log.debug("Response %d for %s", resp.status_code, url)
                return resp.text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 429, 503):
                    delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                    log.warning(
                        "Rate-limited (%d) on %s, sleeping %ds",
                        exc.response.status_code,
                        url,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    log.error("HTTP %d on %s", exc.response.status_code, url)
                    return None
            except httpx.RequestError as exc:
                log.error("Request error on %s: %s", url, exc)
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(
                        _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                    )

        log.error("Max retries exceeded for %s", url)
        return None

    async def fetch_with_delay(self, url: str) -> str | None:
        """Fetch with a polite random delay to avoid rate-limiting."""
        result = await self.fetch(url)
        jitter = random.uniform(self._delay * 0.5, self._delay * 1.5)
        await asyncio.sleep(jitter)
        return result

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
