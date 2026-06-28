import types

import httpx
import pytest

from apartment_hunter.analysis.vision_analyzer import VisionAnalyzer
from apartment_hunter.core.models import Apartment


@pytest.mark.asyncio
async def test_vision_analyzer_returns_none_without_photos() -> None:
    analyzer = VisionAnalyzer()
    apt = Apartment(source_id="x", source="krisha", url="http://x", price=1)

    assert await analyzer.analyze_photos(apt) is None


@pytest.mark.asyncio
async def test_vision_analyzer_download_failure_returns_none(mocker) -> None:
    analyzer = VisionAnalyzer()
    apt = Apartment(
        source_id="x",
        source="krisha",
        url="http://x",
        price=1,
        photo_urls=["http://img/1.jpg"],
    )
    download_mock = mocker.AsyncMock(return_value=None)
    mocker.patch.object(analyzer, "_download_image", download_mock)

    assert await analyzer.analyze_photos(apt) is None
    download_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_vision_analyzer_happy_path_uses_first_three_images(mocker) -> None:
    analyzer = VisionAnalyzer()
    apt = Apartment(
        source_id="x",
        source="krisha",
        url="http://x",
        price=1,
        photo_urls=["1", "2", "3", "4"],
    )
    mocker.patch.object(
        analyzer,
        "_download_image",
        side_effect=[b"a", b"b", b"c"],
    )
    model = mocker.MagicMock()
    model.generate_content_async = mocker.AsyncMock(
        return_value=types.SimpleNamespace(text=" Светло и аккуратно ")
    )
    mocker.patch.object(analyzer, "_init_client", return_value=model)

    result = await analyzer.analyze_photos(apt)

    assert result == "Светло и аккуратно"
    model.generate_content_async.assert_awaited_once()
    contents = model.generate_content_async.await_args.args[0]
    assert len(contents) == 4
    assert contents[1]["data"] == b"a"
    assert contents[3]["data"] == b"c"


@pytest.mark.asyncio
async def test_vision_analyzer_download_image_handles_http_errors(mocker) -> None:
    analyzer = VisionAnalyzer()

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            raise httpx.RequestError("bad", request=httpx.Request("GET", url))

    mocker.patch(
        "apartment_hunter.analysis.vision_analyzer.httpx.AsyncClient",
        return_value=DummyClient(),
    )

    assert await analyzer._download_image("http://img") is None
