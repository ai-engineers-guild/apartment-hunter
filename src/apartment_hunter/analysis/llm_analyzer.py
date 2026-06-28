"""LLM-based apartment analysis using instructor for structured outputs."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from apartment_hunter.config import get_settings
from apartment_hunter.core.interfaces import Analyzer
from apartment_hunter.core.models import AnalysisResult, Apartment

log = logging.getLogger(__name__)


class LLMAnalysisResponse(BaseModel):
    """Structured response required from the LLM."""

    score: float = Field(
        ..., description="Оценка квартиры от 0.0 до 10.0 (где 10 - идеальный вариант)"
    )
    summary: str = Field(
        ...,
        description=(
            "Краткое резюме по квартире: стоит ли рассматривать, "
            "какие главные особенности (2-3 предложения)"
        ),
    )
    pros: list[str] = Field(..., description="Список плюсов квартиры")
    cons: list[str] = Field(..., description="Список минусов или рисков квартиры")
    renovation_quality: str | None = Field(
        None,
        description=(
            "Оценка состояния ремонта "
            "(например: 'Евроремонт', 'Требует ремонта', 'Бабушкин вариант')"
        ),
    )


class LLMAnalyzer(Analyzer):
    """Analyzes apartments using LLMs via the instructor library."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._provider = self.settings.llm_provider.lower()
        self._model = self.settings.llm_model

    def _init_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import instructor
        except ImportError:
            raise ImportError(
                "instructor is required for LLMAnalyzer. Run: pip install instructor"
            )

        if self._provider == "openai":
            import openai

            if not self.settings.openai_api_key:
                raise ValueError("openai_api_key is required for OpenAI")
            self._client = instructor.from_openai(
                openai.AsyncOpenAI(api_key=self.settings.openai_api_key)
            )

        elif self._provider == "anthropic":
            import anthropic

            if not self.settings.anthropic_api_key:
                raise ValueError("anthropic_api_key is required for Anthropic")
            self._client = instructor.from_anthropic(
                anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)
            )

        elif self._provider == "openrouter":
            import openai

            if not self.settings.openrouter_api_key:
                raise ValueError("openrouter_api_key is required for OpenRouter")
            self._client = instructor.from_openai(
                openai.AsyncOpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=self.settings.openrouter_api_key,
                )
            )

        elif self._provider == "gemini":
            import google.generativeai as genai

            if not self.settings.gemini_api_key:
                raise ValueError("gemini_api_key is required for Gemini")
            genai.configure(api_key=self.settings.gemini_api_key)
            # Instructor has a Gemini client
            self._client = instructor.from_gemini(
                client=genai.GenerativeModel(model_name=self._model)
            )

        else:
            raise ValueError(f"Unsupported LLM provider: {self._provider}")

        return self._client

    async def analyze(self, apt: Apartment) -> AnalysisResult:
        """Run LLM analysis on the apartment to extract pros, cons, and a score."""
        try:
            client = self._init_client()
            return await self._call_llm(client, apt)
        except Exception as exc:
            log.warning(
                "LLM analysis failed (%s): %s. Using fallback logic.",
                self._provider,
                exc,
            )
            return self._fallback_analysis(apt)

    async def _call_llm(self, client: Any, apt: Apartment) -> AnalysisResult:
        """Make the actual call using instructor."""
        sys_prompt = (
            "Ты — опытный риэлтор в Казахстане. Твоя задача: объективно оценить квартиру "
            "для долгосрочной аренды по ее параметрам и тексту объявления. "
            "Цены указаны в тенге (KZT). Верни строго JSON со структурой LLMAnalysisResponse."
        )

        user_prompt = (
            f"Оцени квартиру:\n"
            f"Цена: {apt.price} KZT\n"
            f"Комнат: {apt.rooms}\n"
            f"Площадь: {apt.area_total} кв.м.\n"
            f"Этаж: {apt.floor} из {apt.floor_total}\n"
            f"Дом: {apt.building_type}, {apt.year_built} года\n"
            f"Состояние: {apt.condition}\n"
            f"Город: {apt.city}, Район: {apt.district}\n"
            f"Тип владельца: {apt.owner_type}\n\n"
            f"Описание автора:\n{apt.description}"
        )

        # Handle Gemini differently if instructor API for Gemini expects different args
        if self._provider == "gemini":
            # instructor.from_gemini usually expects chat.send_message style or create
            response = await client.messages.create(
                messages=[
                    {"role": "user", "content": f"{sys_prompt}\n\n{user_prompt}"}
                ],
                response_model=LLMAnalysisResponse,
            )
        elif self._provider == "anthropic":
            response = await client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=sys_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                response_model=LLMAnalysisResponse,
            )
        else:  # openai, openrouter
            response = await client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=LLMAnalysisResponse,
            )

        return AnalysisResult(
            score=response.score,
            summary=response.summary,
            pros=response.pros,
            cons=response.cons,
            renovation_quality=response.renovation_quality,
        )

    def _fallback_analysis(self, apt: Apartment) -> AnalysisResult:
        """Simple rule-based fallback if LLM is unavailable."""
        score = 5.0
        pros = []
        cons = []

        if apt.price_per_sqm and apt.price_per_sqm < 4000:
            score += 1.5
            pros.append("Цена ниже средней по рынку")
        elif apt.price_per_sqm and apt.price_per_sqm > 8000:
            score -= 1.0
            cons.append("Высокая цена за квадратный метр")

        if apt.year_built and apt.year_built >= 2015:
            score += 1.0
            pros.append("Относительно новый дом")
        elif apt.year_built and apt.year_built < 1980:
            score -= 0.5
            cons.append("Старый жилой фонд")

        if apt.floor == 1:
            score -= 0.5
            cons.append("Первый этаж")
        elif apt.floor == apt.floor_total and apt.floor_total and apt.floor_total > 5:
            pros.append("Последний этаж (меньше соседей сверху)")

        if apt.owner_type and "крыша агент" in apt.owner_type.lower():
            score -= 0.5
            cons.append("Комиссия агентству")

        score = max(0.0, min(10.0, score))

        return AnalysisResult(
            score=score,
            summary="Автоматическая оценка на основе базовых параметров (LLM недоступна).",
            pros=pros,
            cons=cons,
            renovation_quality=apt.condition or "Неизвестно",
        )
