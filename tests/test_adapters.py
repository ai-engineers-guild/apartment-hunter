import json

import pytest

from apartment_hunter.adapters.krisha.adapter import KrishaAdapter
from apartment_hunter.core.models import SearchProfile


@pytest.mark.asyncio
async def test_krisha_adapter_fetch_listings(mocker) -> None:
    search_html = """
    <html><body>
        <section class="a-search-list">
            <div data-id="12345">
                <a class="a-card__title" href="/a/show/12345">2-комнатная квартира</a>
            </div>
        </section>
    </body></html>
    """
    jsdata = {
        "advert": {"id": 12345, "price": 200000, "rooms": 2, "title": "2-комнатная квартира"},
        "photos": [{"src": "http://photo1.jpg"}, {"src": "http://photo2.jpg"}],
    }
    detail_html = f"""
    <html><body>
    <script id="jsdata">var data = {json.dumps(jsdata)};</script>
    </body></html>
    """

    mock_scraper = mocker.MagicMock()
    mock_scraper.__aenter__ = mocker.AsyncMock(return_value=mock_scraper)
    mock_scraper.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_scraper.fetch = mocker.AsyncMock(return_value=search_html)
    mock_scraper.fetch_with_delay = mocker.AsyncMock(side_effect=[search_html, detail_html])
    mocker.patch("apartment_hunter.adapters.krisha.adapter.KrishaScraper", return_value=mock_scraper)

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
async def test_krisha_adapter_fetch_failure_returns_empty(mocker) -> None:
    """When the scraper fails to fetch the listing page, adapter returns empty list gracefully."""
    mock_scraper = mocker.MagicMock()
    mock_scraper.__aenter__ = mocker.AsyncMock(return_value=mock_scraper)
    mock_scraper.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_scraper.fetch_with_delay = mocker.AsyncMock(return_value=None)
    mocker.patch("apartment_hunter.adapters.krisha.adapter.KrishaScraper", return_value=mock_scraper)

    adapter = KrishaAdapter(delay=0, timeout=1)
    profile = SearchProfile(name="Test", city="алматы")
    apartments = await adapter.fetch_listings(profile, max_pages=1)
    assert apartments == []


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
    assert "areas=p" not in url


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


def test_krisha_adapter_builds_url_with_polygon() -> None:
    polygon = [
        [43.267774, 76.946235],
        [43.263258, 76.947480],
        [43.263258, 76.955891],
        [43.267774, 76.946235],  # closed
    ]
    profile = SearchProfile(
        name="Megapark",
        city="Алматы",
        rooms=[2],
        price_max=300000,
        polygons=[polygon],
    )

    urls = KrishaAdapter._build_search_urls(profile)
    assert len(urls) == 1
    url = urls[0]

    assert "areas=p43.267774,76.946235" in url
    assert "das[live.rooms]=2" in url
    assert "das[price][to]=300000" in url


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


def test_search_profile_with_nl_description() -> None:
    profile = SearchProfile(name="Test NL", city="Алматы", nl_description="светлая квартира с новым ремонтом")
    d = profile.to_dict()
    assert d["nl_description"] == "светлая квартира с новым ремонтом"

    p2 = SearchProfile.from_dict(d)
    assert p2.nl_description == "светлая квартира с новым ремонтом"


def test_url_to_source_id() -> None:
    assert KrishaAdapter._url_to_source_id("https://krisha.kz/a/show/12345") == "krisha:12345"
    assert KrishaAdapter._url_to_source_id("/a/show/999?param=x") == "krisha:999"
    assert KrishaAdapter._url_to_source_id("https://other.com/foo") is None
