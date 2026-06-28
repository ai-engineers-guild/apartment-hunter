"""Vision-based apartment photo analysis (Phase 2 stub)."""

from __future__ import annotations

import logging

from apartment_hunter.core.models import Apartment

log = logging.getLogger(__name__)


class VisionAnalyzer:
    """Analyze apartment photos to estimate renovation quality.

    Note: This is a placeholder for Phase 2.
    """

    def __init__(self) -> None:
        pass

    async def analyze_photos(self, apt: Apartment) -> str | None:
        """Analyze up to 3 photos and return an estimated renovation quality."""
        if not apt.photo_urls:
            return None

        # Phase 2: Implement multimodal LLM call here (e.g., gpt-4o with image URLs)
        # For now, return a placeholder or None
        log.debug(
            "Vision analysis not yet implemented. Photos: %d", len(apt.photo_urls)
        )
        return None
