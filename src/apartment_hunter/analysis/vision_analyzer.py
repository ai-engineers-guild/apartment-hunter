"""Vision-based apartment photo analysis using Gemini."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from apartment_hunter.config import get_settings
from apartment_hunter.core.models import Apartment

log = logging.getLogger(__name__)


class VisionAnalyzer:
    """Analyze apartment photos to extract visual aesthetics using Gemini."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None

    def _init_client(self) -> Any:
        if self._model is not None:
            return self._model

        import google.generativeai as genai

        if not self.settings.gemini_api_key:
            raise ValueError("gemini_api_key is required for VisionAnalyzer (ensure it is in .env)")

        genai.configure(api_key=self.settings.gemini_api_key)

        # Keep the implementation on Gemini even if the generic vision model points elsewhere.
        model_name = self.settings.vision_model
        if "gemini" not in model_name.lower():
            model_name = "gemini-1.5-flash"

        self._model = genai.GenerativeModel(model_name=model_name)
        return self._model

    async def _download_image(self, url: str) -> bytes | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Some sites require user agent
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.content
        except Exception as e:
            log.warning("Failed to download image %s: %s", url, e)
            return None

    async def analyze_photos(self, apt: Apartment) -> str | None:
        """Analyze up to 3 photos and return a visual description."""
        if not apt.photo_urls:
            return None

        # Take up to 3 photos to save context window and time
        urls = apt.photo_urls[:3]
        images = []
        for url in urls:
            img_bytes = await self._download_image(url)
            if img_bytes:
                # Krisha typically uses JPEGs, but MIME can be inferred or hardcoded as image/jpeg
                # as Gemini API is flexible enough if it's actually png
                images.append({"mime_type": "image/jpeg", "data": img_bytes})

        if not images:
            return None

        try:
            model = self._init_client()
            prompt = (
                "Ты профессиональный дизайнер интерьеров и риэлтор. "
                "Опиши визуальный стиль этой квартиры по фотографиям. "
                "Укажи цвета (светлые, темные, пастельные, яркие), "
                "тип ремонта (современный, свежий, советский/бабушкин ремонт, требующий ремонта), "
                "и общую эстетику (минимализм, уютно, захламлено). "
                "Будь краток, верни только описание на русском языке в 2-3 предложениях."
            )

            contents = [prompt] + images

            response = await model.generate_content_async(contents)

            if response.text:
                return response.text.strip()
            return None

        except Exception as exc:
            log.error("Vision analysis failed for %s: %s", apt.source_id, exc)
            return None
