"""Parse Krisha.kz listing and detail pages.

Extracts the full set of apartment fields from the embedded ``<script id="jsdata">``
block rather than scraping fragile HTML selectors.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup

from apartment_hunter.core.models import Apartment

log = logging.getLogger(__name__)


# ── Detail page parser ─────────────────────────────────────────────────────────


def parse_detail_page(html: str, url: str) -> Apartment | None:
    """Parse a single apartment detail page and return an Apartment model.

    The page embeds a ``<script id="jsdata">`` tag containing a JSON object
    with all structured data for the listing.
    """
    soup = BeautifulSoup(html, "html.parser")
    jsdata = _extract_jsdata(soup)
    if jsdata is None:
        log.warning("jsdata not found on %s", url)
        return None

    advert: dict = jsdata.get("advert", {})
    adverts_list: list = jsdata.get("adverts", [])
    adverts: dict = (
        adverts_list[0] if adverts_list and isinstance(adverts_list[0], dict) else {}
    )

    raw_id = advert.get("id")
    if not raw_id:
        log.warning("No advert id found on %s", url)
        return None

    source_id = f"krisha:{raw_id}"

    # Photos – collect all, not just the first
    photos_raw = advert.get("photos") or jsdata.get("photos") or []
    photo_urls = []
    for p in photos_raw:
        src = p.get("src") if isinstance(p, dict) else None
        if src:
            if src.startswith("//"):
                src = "https:" + src
            photo_urls.append(src)

    # Map / coordinates
    map_data = advert.get("map", {}) or {}

    # Full address
    full_address = adverts.get("fullAddress", "")
    city = full_address.split(",")[0].strip() if full_address else None

    # Parse extended attributes from the 'params' section if available
    params = _parse_params(adverts)

    # Title from advert or build from rooms/area
    rooms = _safe_int(advert.get("rooms"))
    square = _safe_float(advert.get("square"))
    title = adverts.get("title") or _build_title(rooms, square, city)

    return Apartment(
        source_id=source_id,
        source="krisha.kz",
        url=url,
        title=title,
        price=_safe_int(advert.get("price")) or 0,
        currency="KZT",
        rooms=rooms,
        area_total=square,
        area_living=params.get("area_living"),
        area_kitchen=params.get("area_kitchen"),
        floor=params.get("floor"),
        floor_total=params.get("floor_total"),
        building_type=params.get("building_type"),
        year_built=params.get("year_built"),
        condition=params.get("condition"),
        furniture=params.get("furniture"),
        address=full_address or None,
        city=city,
        district=params.get("district"),
        lat=_safe_float(map_data.get("lat")),
        lon=_safe_float(map_data.get("lon")),
        description=adverts.get("description"),
        photo_urls=photo_urls,
        owner_type=params.get("owner_type"),
        created_at=_parse_datetime(adverts.get("createdAt")),
        scraped_at=datetime.now(UTC),
    )


# ── Listing page parser ───────────────────────────────────────────────────────


def parse_listing_page(html: str) -> tuple[list[str], int, str | None]:
    """Parse a search results page.

    Returns:
        (ad_urls, total_count, next_page_url)
    """
    soup = BeautifulSoup(html, "html.parser")

    # Total count
    total_count = 0
    subtitle = soup.find("div", class_="a-search-subtitle")
    if subtitle:
        digits = re.findall(r"\d+", subtitle.text.strip())
        total_count = int("".join(digits)) if digits else 0

    # Empty results
    if soup.find("div", class_="a-search-empty"):
        return [], 0, None

    # Ad URLs
    ad_urls: list[str] = []
    section = soup.find("section", class_="a-search-list")
    if section:
        for div in section.find_all("div", attrs={"data-id": True}):
            link = div.find("a", class_="a-card__title")
            if link and link.get("href"):
                href = link["href"]
                if not href.startswith("http"):
                    href = "https://krisha.kz" + href
                ad_urls.append(href)

    # Next page
    next_url: str | None = None
    next_btn = soup.find("a", class_="paginator__btn--next")
    if next_btn and next_btn.get("href"):
        href = next_btn["href"]
        if not href.startswith("http"):
            href = "https://krisha.kz" + href
        next_url = href

    return ad_urls, total_count, next_url


# ── Internals ──────────────────────────────────────────────────────────────────


def _extract_jsdata(soup: BeautifulSoup) -> dict | None:
    script = soup.find("script", id="jsdata")
    if not script:
        return None
    text = script.text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        log.warning("Failed to parse jsdata JSON: %s", exc)
        return None


def _parse_params(adverts: dict) -> dict[str, Any]:
    """Extract structured parameters from the adverts dictionary.

    Krisha.kz embeds apartment attributes in different nested structures
    depending on the page version. We try to extract as much as possible.
    """
    result: dict[str, Any] = {}

    # Some fields sit directly on the adverts dict
    for raw_key, mapped_key in [
        ("flat.floor", "floor"),
        ("flat.floor_total", "floor_total"),
        ("house.year", "year_built"),
    ]:
        if raw_key in adverts:
            result[mapped_key] = _safe_int(adverts[raw_key])

    # Parameters list (array of {title, value} dicts)
    params_list = adverts.get("params") or adverts.get("parameters") or []
    if isinstance(params_list, list):
        for item in params_list:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").lower().strip()
            value = item.get("value", "")
            if isinstance(value, dict):
                value = value.get("text", str(value))
            value = str(value).strip()

            if "жилая" in title:
                result["area_living"] = _safe_float(value)
            elif "кухн" in title:
                result["area_kitchen"] = _safe_float(value)
            elif "этаж" in title and "этажн" not in title:
                parts = re.findall(r"\d+", value)
                if len(parts) >= 2:
                    result["floor"] = int(parts[0])
                    result["floor_total"] = int(parts[1])
                elif len(parts) == 1:
                    result.setdefault("floor", int(parts[0]))
            elif "этажн" in title:
                result["floor_total"] = _safe_int(value)
            elif "тип стро" in title or "серия" in title:
                result["building_type"] = value
            elif "год" in title and "постр" in title:
                result["year_built"] = _safe_int(value)
            elif "состояние" in title or "ремонт" in title:
                result["condition"] = value
            elif "мебел" in title:
                result["furniture"] = value
            elif "район" in title:
                result["district"] = value

    # Owner type from a 'who' field or 'owner' flag
    who = adverts.get("who") or adverts.get("owner")
    if who:
        if isinstance(who, dict):
            result["owner_type"] = who.get("text") or who.get("name") or str(who)
        else:
            result["owner_type"] = str(who)

    return result


def _build_title(rooms: int | None, area: float | None, city: str | None) -> str:
    parts: list[str] = []
    if rooms:
        parts.append(f"{rooms}-комнатная квартира")
    if area:
        parts.append(f"{area} м²")
    if city:
        parts.append(city)
    return ", ".join(parts) if parts else "Квартира"


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(float(str(val).replace(" ", "")))
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def _parse_datetime(val: Any) -> datetime | None:
    if not val:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=UTC)
        except (OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(val))
    except ValueError:
        return None
