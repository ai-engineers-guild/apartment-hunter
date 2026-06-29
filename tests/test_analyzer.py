from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from apartment_hunter.analysis.llm_analyzer import LLMAnalysisResponse, LLMAnalyzer
from apartment_hunter.core.models import Apartment


@pytest.fixture
def sample_apt() -> Apartment:
    return Apartment(
        source_id="krisha:123",
        source="krisha",
        url="http://test.com/123",
        price=150000,
        rooms=2,
        area_total=55.0,
        city="Алматы",
        scraped_at=datetime.now(UTC),
        description="Хорошая квартира, евроремонт",
        condition="Евроремонт",
    )


@pytest.mark.asyncio
async def test_llm_analyzer_success(mocker, sample_apt) -> None:
    # Mock the LLM client response
    mock_response = LLMAnalysisResponse(
        score=8.5,
        summary="Отличная квартира",
        pros=["Хороший ремонт"],
        cons=["Нет метро рядом"],
        renovation_quality="Евроремонт",
    )

    analyzer = LLMAnalyzer()
    analyzer._provider = "openai"  # Force provider for test

    mock_client = mocker.MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    # Mock _init_client to return our mock client
    mocker.patch.object(analyzer, "_init_client", return_value=mock_client)

    result = await analyzer.analyze(sample_apt)

    assert result.score == 8.5
    assert result.summary == "Отличная квартира"
    assert result.pros == ["Хороший ремонт"]
    assert result.cons == ["Нет метро рядом"]


@pytest.mark.asyncio
async def test_llm_analyzer_fallback(mocker, sample_apt) -> None:
    analyzer = LLMAnalyzer()
    analyzer._provider = "openai"

    # Force _call_llm to raise Exception to trigger fallback
    mocker.patch.object(analyzer, "_call_llm", side_effect=Exception("API Error"))

    # Test the fallback heuristic
    # Price per sqm is 150000 / 55 = 2727 (< 4000) -> should get pros
    result = await analyzer.analyze(sample_apt)

    assert result.score > 5.0  # baseline is 5.0, low price per sqm adds 1.5
    assert "Цена ниже средней" in result.pros[0]
    assert result.summary == "Автоматическая оценка на основе базовых параметров (LLM недоступна)."
