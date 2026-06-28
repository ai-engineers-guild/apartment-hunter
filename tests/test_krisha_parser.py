import json
from datetime import UTC, datetime

from apartment_hunter.adapters.krisha.parser import (
    _build_title,
    _extract_jsdata,
    _parse_datetime,
    _parse_params,
    _safe_float,
    _safe_int,
    parse_detail_page,
    parse_listing_page,
)


def test_parse_listing_page_handles_pagination_and_total() -> None:
    html = """
    <div class="a-search-subtitle">Найдено 1 245 объявлений</div>
    <section class="a-search-list">
      <div data-id="1"><a class="a-card__title" href="/a/show/1">One</a></div>
      <div data-id="2"><a class="a-card__title" href="https://krisha.kz/a/show/2">Two</a></div>
    </section>
    <a class="paginator__btn--next" href="/arenda/kvartiry/?page=2">next</a>
    """

    urls, total, next_url = parse_listing_page(html)

    assert urls == ["https://krisha.kz/a/show/1", "https://krisha.kz/a/show/2"]
    assert total == 1245
    assert next_url == "https://krisha.kz/arenda/kvartiry/?page=2"


def test_parse_listing_page_handles_empty_results() -> None:
    urls, total, next_url = parse_listing_page(
        '<div class="a-search-empty">Nothing</div>'
    )

    assert urls == []
    assert total == 0
    assert next_url is None


def test_parse_detail_page_extracts_extended_fields() -> None:
    jsdata = {
        "advert": {
            "id": 12345,
            "price": "250000",
            "rooms": "3",
            "square": "67.5",
            "map": {"lat": "43.2389", "lon": "76.8897"},
            "photos": [{"src": "//img1.jpg"}],
        },
        "adverts": [
            {
                "title": "3-комнатная квартира",
                "fullAddress": "Алматы, Бостандыкский р-н, ул. Тестовая",
                "description": "Свежий ремонт",
                "createdAt": "2024-01-02T03:04:05+00:00",
                "params": [
                    {"title": "Жилая площадь", "value": "45.3"},
                    {"title": "Площадь кухни", "value": "12,1"},
                    {"title": "Этаж", "value": "7 из 9"},
                    {"title": "Тип строения", "value": "монолитный"},
                    {"title": "Год постройки", "value": "2019"},
                    {"title": "Состояние", "value": "евроремонт"},
                    {"title": "Мебель", "value": "полностью"},
                    {"title": "Район", "value": "Бостандыкский"},
                ],
                "who": {"text": "Собственник"},
            }
        ],
    }

    apt = parse_detail_page(
        f'<script id="jsdata">window.data = {json.dumps(jsdata, ensure_ascii=False)};</script>',
        "https://krisha.kz/a/show/12345",
    )

    assert apt is not None
    assert apt.source_id == "krisha:12345"
    assert apt.photo_urls == ["https://img1.jpg"]
    assert apt.area_living == 45.3
    assert apt.area_kitchen == 12.1
    assert apt.floor == 7
    assert apt.floor_total == 9
    assert apt.building_type == "монолитный"
    assert apt.year_built == 2019
    assert apt.condition == "евроремонт"
    assert apt.owner_type == "Собственник"
    assert apt.city == "Алматы"
    assert apt.created_at == datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert apt.scraped_at is not None


def test_parse_detail_page_returns_none_without_id() -> None:
    apt = parse_detail_page(
        '<script id="jsdata">{"advert": {"price": 1}}</script>',
        "https://krisha.kz/a/show/no-id",
    )
    assert apt is None


def test_parse_params_and_helpers_cover_edge_cases() -> None:
    params = _parse_params(
        {
            "flat.floor": "2",
            "flat.floor_total": "16",
            "house.year": "2004",
            "parameters": [
                {"title": "Этажность", "value": "16"},
                {"title": "Серия", "value": "кирпичный"},
                {"title": "Ремонт", "value": {"text": "хорошее"}},
                {"title": "Район", "value": "Алмалинский"},
            ],
            "owner": "Хозяин",
        }
    )

    assert params["floor"] == 2
    assert params["floor_total"] == 16
    assert params["year_built"] == 2004
    assert params["building_type"] == "кирпичный"
    assert params["condition"] == "хорошее"
    assert params["district"] == "Алмалинский"
    assert params["owner_type"] == "Хозяин"
    assert _safe_int(" 45 ") == 45
    assert _safe_int("oops") is None
    assert _safe_float("12,5") == 12.5
    assert _safe_float("oops") is None
    assert _parse_datetime(1710000000) is not None
    assert _parse_datetime("2024-01-02T03:04:05+00:00") is not None
    assert _parse_datetime("bad") is None
    assert _build_title(2, 55.0, "Алматы").startswith("2-комнатная квартира")


def test_extract_jsdata_returns_none_for_invalid_payload() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<script id="jsdata">var x = not-json;</script>', "html.parser")

    assert _extract_jsdata(soup) is None
