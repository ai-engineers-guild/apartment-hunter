"""Async HTTP client for Krisha.kz using CloakBrowser and Playwright to bypass Cloudflare."""

from __future__ import annotations

import asyncio
import logging
import random

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

log = logging.getLogger(__name__)

_RETRY_DELAYS = (5, 15, 60, 300)

class KrishaScraper:
    """Async scraper using CloakBrowser to bypass Cloudflare rate-limiting.

    Supports ``async with`` for automatic resource cleanup::

        async with KrishaScraper() as scraper:
            html = await scraper.fetch(url)
    """

    def __init__(
        self,
        delay: float = 2.0,
        timeout: int = 30000,
        max_retries: int = 3,
    ) -> None:
        self._delay = delay
        self._timeout = int(timeout * 1000)
        self._max_retries = max_retries

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def _init_browser(self) -> None:
        if self._playwright is not None:
            return

        try:
            import cloakbrowser
        except ImportError:
            raise RuntimeError("cloakbrowser is required. Run: uv add cloakbrowser playwright")

        exe_path = cloakbrowser.ensure_binary()
        self._playwright = await async_playwright().start()

        args = cloakbrowser.get_default_stealth_args()
        if "--humanize=true" not in args:
            args.append("--humanize=true")

        self._browser = await self._playwright.chromium.launch(
            executable_path=exe_path,
            headless=True,
            args=args
        )
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        self._context = await self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1920, "height": 1080}
        )

    async def fetch(self, url: str) -> str | None:
        """Fetch a URL and return the response text, or None on failure."""
        await self._init_browser()
        assert self._context is not None

        page = await self._context.new_page()
        try:
            for attempt in range(self._max_retries):
                try:
                    log.debug("GET %s (attempt %d)", url, attempt + 1)

                    # Navigate to the page
                    response = await page.goto(url, timeout=self._timeout, wait_until="domcontentloaded")

                    if response is None:
                        log.error("No response from %s", url)
                        return None

                    status = response.status
                    log.debug("Response %d for %s", status, url)

                    if status in (403, 429, 503):
                        delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                        log.warning(
                            "Rate-limited (%d) on %s, sleeping %ds",
                            status,
                            url,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue

                    if status >= 400:
                        log.error("HTTP %d on %s", status, url)
                        return None

                    # Cloudflare check might still happen via JS. Wait a bit for JS to settle.
                    try:
                        await page.wait_for_timeout(2000)
                    except Exception:
                        pass

                    content = await page.content()

                    # Double check if we hit cloudflare
                    if "Just a moment..." in content or "Please wait..." in content:
                        log.warning("Cloudflare challenge detected, waiting longer...")
                        await page.wait_for_timeout(5000)
                        content = await page.content()

                    return content

                except Exception as exc:
                    log.error("Request error on %s: %s", url, exc)
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(
                            _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                        )

            log.error("Max retries exceeded for %s", url)
            return None
        finally:
            await page.close()

    async def fetch_with_delay(self, url: str) -> str | None:
        """Fetch with a polite random delay to avoid rate-limiting."""
        result = await self.fetch(url)
        jitter = random.uniform(self._delay * 0.5, self._delay * 1.5)
        await asyncio.sleep(jitter)
        return result

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def __aenter__(self) -> KrishaScraper:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
