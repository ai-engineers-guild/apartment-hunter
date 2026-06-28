import json

import httpx
import pytest
import respx

from apartment_hunter.adapters.krisha.adapter import KrishaAdapter
from apartment_hunter.core.models import SearchProfile


@pytest.mark.asyncio
@respx.mock
async def test_krisha_adapter_fetch_listings() -> None:
    # Mock search page response
    search_html = """
    <html>
        <body>
            <section class="a-search-list">
                <div data-id="12345">
                    <div class="a-card__header-left">
                        <a class="a-card__title" href="/a/show/12345">2-комнатная квартира</a>
                    </div>
                    <div class="a-card__price">200 000 〒</div>
                </div>
            </section>
        </body>
    </html>
    """
    respx.get(url__startswith="https://krisha.kz/arenda/kvartiry/").mock(
        return_value=httpx.Response(200, text=search_html)
    )

    # Mock detail page response with jsdata
    jsdata = {
        "advert": {
            "id": 12345,
            "price": 200000,
            "rooms": 2,
            "title": "2-комнатная квартира",
        },
        "photos": [{"src": "http://photo1.jpg"}, {"src": "http://photo2.jpg"}],
    }
    detail_html = f"""
    <html>
        <body>
            <script id="jsdata">
                var data = {json.dumps(jsdata)};
            </script>
        </body>
    </html>
    """
    respx.get("https://krisha.kz/a/show/12345").mock(
        return_value=httpx.Response(200, text=detail_html)
    )

    adapter = KrishaAdapter(delay=0)
    profile = SearchProfile(name="Test", city="алматы")

    apartments = await adapter.fetch_listings(profile, max_pages=1)

    assert len(apartments) == 1
    apt = apartments[0]
    assert apt.source_id == "krisha:12345"
    assert apt.price == 200000
    assert apt.rooms == 2
    assert len(apt.photo_urls) == 2


@pytest.mark.asyncio
@respx.mock
async def test_krisha_adapter_rate_limit() -> None:
    # Mock a 429 response then a 200 response
    route = respx.get(url__startswith="https://krisha.kz/arenda/kvartiry/")
    route.side_effect = [
        httpx.Response(429, text="Too Many Requests"),
        httpx.Response(
            200,
            text=(
                '<section class="a-search-list"><div data-id="999">'
                '<a class="a-card__title" href="/a/show/999">Title</a>'
                "</div></section>"
            ),
        ),
    ]

    detail_html = """
    <html><body>
    <script id="jsdata">var data = {"advert": {"id": 999, "price": 100}};</script>
    </body></html>
    """
    respx.get("https://krisha.kz/a/show/999").mock(
        return_value=httpx.Response(200, text=detail_html)
    )

    adapter = KrishaAdapter(delay=0, timeout=1)

    profile = SearchProfile(name="Test", city="алматы")

    apartments = await adapter.fetch_listings(profile, max_pages=1)
    assert len(apartments) == 1
    assert apartments[0].source_id == "krisha:999"


def test_krisha_adapter_builds_search_url_with_district_and_bbox() -> None:
    profile = SearchProfile(
        name="Test",
        city="Алматы",
        districts=["Бостандыкский"],
        rooms=[2, 5],
        furniture=False,
        owner_only=True,
        has_photo=True,
        price_min=150000,
        price_max=300000,
        bounding_box=[43.2, 76.8, 43.3, 76.9],
    )

    urls = KrishaAdapter._build_search_urls(profile)
    assert len(urls) == 1
    url = urls[0]

    assert "almaty--bostandykskij-rajon/" in url
    assert "das[_sys.hasphoto]=1" in url
    assert "das[live.furniture]=2" in url
    assert "das[live.rooms][]=2" in url
    assert "das[live.rooms][]=5.100" in url
    assert "das[who]=1" in url
    assert "areas=p43.2,76.8,43.3,76.8,43.3,76.9,43.2,76.9" in url


def test_krisha_adapter_builds_multiple_urls_for_multiple_districts() -> None:
    profile = SearchProfile(
        name="Test",
        city="Алматы",
        districts=["Алмалинский", "Медеуский"],
        rooms=[1],
        price_max=300000,
    )

    urls = KrishaAdapter._build_search_urls(profile)
    assert len(urls) == 2
    assert "almalinskij-rajon" in urls[0]
    assert "medeuskij-rajon" in urls[1]
    # Both should share the same query params
    for url in urls:
        assert "das[live.rooms]=1" in url
        assert "das[price][to]=300000" in url


def test_krisha_adapter_builds_single_url_when_no_districts() -> None:
    profile = SearchProfile(name="Test", city="Алматы", rooms=[2])

    urls = KrishaAdapter._build_search_urls(profile)
    assert len(urls) == 1
    assert "almaty/" in urls[0]
    assert "rajon" not in urls[0]


@pytest.mark.asyncio
async def test_krisha_adapter_get_details_returns_none_when_not_found(mocker) -> None:
    mock_scraper = mocker.MagicMock()
    mock_scraper.fetch = mocker.AsyncMock(return_value=None)
    mock_scraper.close = mocker.AsyncMock()
    mock_scraper.__aenter__ = mocker.AsyncMock(return_value=mock_scraper)
    mock_scraper.__aexit__ = mocker.AsyncMock(return_value=False)

    mocker.patch(
        "apartment_hunter.adapters.krisha.adapter.KrishaScraper",
        return_value=mock_scraper,
    )

    adapter = KrishaAdapter(delay=0)
    result = await adapter.get_details("krisha:404")

    assert result is None
    mock_scraper.fetch.assert_awaited_once()
