"""Tests for KrishaAdapter."""

import json
from datetime import datetime
import pytest
import respx
import httpx

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
        "photos": [
            {"src": "http://photo1.jpg"},
            {"src": "http://photo2.jpg"},
        ],
    }
    detail_html = f"""
    <html>
        <body>
            <script>
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
        httpx.Response(200, text='<section class="a-search-list"><div data-id="999"><a class="a-card__title" href="/a/show/999">Title</a></div></section>'),
    ]

    detail_html = """
    <html><body><script>var data = {"advert": {"id": 999, "price": 100}}; </script></body></html>
    """
    respx.get("https://krisha.kz/a/show/999").mock(
        return_value=httpx.Response(200, text=detail_html)
    )

    adapter = KrishaAdapter(delay=0, timeout=1)

    profile = SearchProfile(name="Test", city="алматы")
    
    apartments = await adapter.fetch_listings(profile, max_pages=1)
    assert len(apartments) == 1
    assert apartments[0].source_id == "krisha:999"
