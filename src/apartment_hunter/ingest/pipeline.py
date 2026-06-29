"""Ingestion pipeline: fetch → deduplicate → store → embed → analyze → notify."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apartment_hunter.adapters import AdapterFactory, get_default_adapters
from apartment_hunter.analysis.llm_analyzer import LLMAnalyzer
from apartment_hunter.analysis.vision_analyzer import VisionAnalyzer
from apartment_hunter.config import get_settings
from apartment_hunter.core.interfaces import StorageBackend, VectorStore
from apartment_hunter.core.models import Apartment, SearchProfile
from apartment_hunter.storage.factory import get_storage, get_vector_store

if TYPE_CHECKING:
    from apartment_hunter.core.interfaces import Notifier

log = logging.getLogger(__name__)


class IngestPipeline:
    """Orchestrates the full ingestion flow for all active search profiles."""

    def __init__(
        self,
        db: StorageBackend | None = None,
        vector: VectorStore | None = None,
        notifiers: list[Notifier] | None = None,
        analyze: bool = True,
        adapters: dict[str, AdapterFactory] | None = None,
    ) -> None:
        settings = get_settings()
        self.db = db or get_storage()
        self.vector = vector or get_vector_store()
        self.notifiers = notifiers or []
        self.analyzer = LLMAnalyzer() if analyze else None
        self.vision_analyzer = VisionAnalyzer() if analyze else None
        self.adapters = adapters if adapters is not None else get_default_adapters()
        self._settings = settings

    async def run_profile(self, profile: SearchProfile) -> list[Apartment]:
        """Run the pipeline for a single search profile. Returns new apartments."""
        new_apartments: list[Apartment] = []

        source_results = await asyncio.gather(
            *[
                self._fetch_source_apartments(source_name, profile)
                for source_name in self._get_sources_for_profile(profile)
            ]
        )

        for apartments in source_results:
            for apt in apartments:
                if self._persist_apartment(apt):
                    apt.is_new = True
                    new_apartments.append(apt)

        # 3. Analyze new apartments
        await self._analyze_apartments(new_apartments)

        # 4. Notify about matching new apartments
        await self._notify_new_apartments(profile, new_apartments)

        return new_apartments

    async def run_all_profiles(self) -> dict[str, int]:
        """Run pipeline for all active profiles. Returns {profile_name: new_count}."""
        profiles = self.db.list_profiles(active_only=True)
        if not profiles:
            log.info("No active search profiles found")
            return {}

        results: dict[str, int] = {}
        for profile in profiles:
            log.info("Running profile: %s", profile.name)
            new = await self.run_profile(profile)
            results[profile.name] = len(new)
            log.info("Profile '%s': %d new apartments", profile.name, len(new))

        return results

    def _get_sources_for_profile(self, profile: SearchProfile) -> list[str]:
        """Resolve sources, defaulting to all registered adapters."""
        return profile.sources or list(self.adapters.keys())

    async def _fetch_source_apartments(self, source_name: str, profile: SearchProfile) -> list[Apartment]:
        adapter_factory = self.adapters.get(source_name)
        if not adapter_factory:
            log.warning("No adapter for source '%s'", source_name)
            return []

        adapter = adapter_factory(
            delay=self._settings.scrape_delay_seconds,
            timeout=self._settings.scrape_timeout,
        )

        try:
            known_ids = self.db.get_all_source_ids()
            return await adapter.fetch_listings(profile, max_pages=0, known_ids=known_ids)
        except Exception as exc:
            log.error("Fetch failed for %s: %s", source_name, exc)
            return []

    def _persist_apartment(self, apt: Apartment) -> bool:
        """Store apartment state and push it to vector search."""
        is_new = self.db.upsert_apartment(apt)
        self.db.record_price(apt.source_id, apt.price)

        try:
            self.vector.upsert(apt)
        except Exception as exc:
            log.warning("Vector upsert failed for %s: %s", apt.source_id, exc)

        return is_new

    async def _analyze_apartments(self, apartments: list[Apartment]) -> None:
        """Run structured text and optional photo analysis concurrently."""
        if not self.analyzer or not apartments:
            return

        analyzer = self.analyzer
        log.info("Analyzing %d new apartments...", len(apartments))
        sem = asyncio.Semaphore(self._settings.max_pages_per_run or 5)

        async def _analyze_one(apt: Apartment) -> None:
            async with sem:
                try:
                    result = await analyzer.analyze(apt)
                    apt.llm_score = result.score
                    apt.llm_summary = result.summary
                    apt.llm_pros = result.pros
                    apt.llm_cons = result.cons
                    apt.llm_renovation_quality = result.renovation_quality

                    if self.vision_analyzer and apt.photo_urls:
                        try:
                            vision_desc = await self.vision_analyzer.analyze_photos(apt)
                            apt.llm_visual_description = vision_desc
                        except Exception as exc:
                            log.warning("Vision analysis failed for %s: %s", apt.source_id, exc)

                    self.db.upsert_apartment(apt)
                    self.vector.upsert(apt)
                except Exception as exc:
                    log.warning("Analysis failed for %s: %s", apt.source_id, exc)

        await asyncio.gather(*[_analyze_one(apt) for apt in apartments])

    async def _notify_new_apartments(self, profile: SearchProfile, new_apartments: list[Apartment]) -> None:
        """Notify matching apartments through configured notifiers."""
        if not new_apartments or not self.notifiers:
            return

        matching = [a for a in new_apartments if profile.matches(a)]
        log.info(
            "%d new, %d matching profile '%s'",
            len(new_apartments),
            len(matching),
            profile.name,
        )
        for apt in matching:
            for notifier in self.notifiers:
                if self.db.was_notified(apt.source_id, profile.id, notifier.channel_name):
                    continue
                try:
                    sent = await notifier.notify(apt, profile)
                    if sent:
                        self.db.mark_notified(apt.source_id, profile.id, notifier.channel_name)
                except Exception as exc:
                    log.warning("Notification failed: %s", exc)


# ── CLI entry point ────────────────────────────────────────────────────────────


def run_once_cli() -> None:
    """CLI entry point: run all profiles once and exit."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async def _run() -> None:
        pipeline = IngestPipeline()
        results = await pipeline.run_all_profiles()
        for name, count in results.items():
            print(f"  {name}: {count} new apartments")
        if not results:
            print("No active profiles. Create one first via MCP or API.")

    asyncio.run(_run())
