"""Krisha.kz source adapter – implements SourceAdapter interface."""

from __future__ import annotations

import logging

from apartment_hunter.adapters.krisha.parser import (
    parse_detail_page,
    parse_listing_page,
)
from apartment_hunter.adapters.krisha.scraper import KrishaScraper
from apartment_hunter.core.interfaces import SourceAdapter
from apartment_hunter.core.models import Apartment, SearchProfile

log = logging.getLogger(__name__)

_BASE = "https://krisha.kz"
_RENT_URL = f"{_BASE}/arenda/kvartiry/"

# City name → URL slug mapping
CITIES: dict[str, str] = {
    "алматы": "almaty/",
    "астана": "astana/",
    "шымкент": "shymkent/",
    "караганда": "karagandinskaja-oblast/",
    "актобе": "aktjubinskaja-oblast/",
    "атырау": "atyrauskaja-oblast/",
    "павлодар": "pavlodarskaja-oblast/",
    "усть-каменогорск": "vostochno-kazahstanskaja-oblast/",
    "костанай": "kostanajskaja-oblast/",
    "тараз": "zhambylskaja-oblast/",
    "кызылорда": "kyzylordinskaja-oblast/",
    "актау": "mangistauskaja-oblast/",
    "петропавловск": "severo-kazahstanskaja-oblast/",
    "туркестан": "juzhno-kazahstanskaja-oblast/",
}

# District name → URL slug mapping (append to city slug)
DISTRICTS: dict[str, str] = {
    "алатауский": "-alatauskij-rajon",
    "алмалинский": "-almalinskij-rajon",
    "ауэзовский": "-aujezovskij-rajon",
    "бостандыкский": "-bostandykskij-rajon",
    "жетысуский": "-zhetysuskij-rajon",
    "медеуский": "-medeuskij-rajon",
    "наурызбайский": "-nauryzbajskij-rajon",
    "турксибский": "-turksibskij-rajon",
    "есильский": "-esilskij-rajon",
    "алматинский": "-almatinskij-rajon",
    "сарыаркинский": "-saryarkinskij-rajon",
    "байконурский": "-bajkonurskij-rajon",
}


class KrishaAdapter(SourceAdapter):
    """Krisha.kz source adapter – fetches apartment listings asynchronously."""

    def __init__(self, delay: float = 2.0, timeout: int = 20) -> None:
        self._scraper = KrishaScraper(delay=delay, timeout=timeout)

    @property
    def source_name(self) -> str:
        return "krisha.kz"

    async def fetch_listings(
        self, profile: SearchProfile, *, max_pages: int = 5
    ) -> list[Apartment]:
        """Fetch listings matching a SearchProfile, up to max_pages."""
        url = self._build_search_url(profile)
        log.info("Krisha: starting fetch from %s (max %d pages)", url, max_pages)

        apartments: list[Apartment] = []
        current_url: str | None = url

        for page_num in range(1, max_pages + 1):
            if not current_url:
                break

            html = await self._scraper.fetch_with_delay(current_url)
            if not html:
                log.warning("Krisha: failed to fetch page %d", page_num)
                break

            ad_urls, total, next_url = parse_listing_page(html)
            if page_num == 1:
                log.info("Krisha: found %d total ads", total)

            if not ad_urls:
                break

            # Fetch detail pages
            for ad_url in ad_urls:
                detail_html = await self._scraper.fetch_with_delay(ad_url)
                if not detail_html:
                    continue
                apt = parse_detail_page(detail_html, ad_url)
                if apt:
                    apartments.append(apt)

            log.info(
                "Krisha: processed page %d/%d (%d apartments so far)",
                page_num,
                max_pages,
                len(apartments),
            )
            current_url = next_url

        await self._scraper.close()
        log.info("Krisha: fetch complete — %d apartments collected", len(apartments))
        return apartments

    async def get_details(self, source_id: str) -> Apartment | None:
        """Fetch a single apartment by krisha ID (e.g. 'krisha:1013405508')."""
        krisha_id = source_id.replace("krisha:", "")
        url = f"{_BASE}/a/show/{krisha_id}"
        html = await self._scraper.fetch(url)
        await self._scraper.close()
        if not html:
            return None
        return parse_detail_page(html, url)

    # ── URL builder ───────────────────────────────────────────────────

    @staticmethod
    def _build_search_url(profile: SearchProfile) -> str:
        """Build a krisha.kz search URL from a SearchProfile."""
        # City slug
        city_slug = ""
        if profile.city:
            city_lower = profile.city.lower().strip()
            city_slug = CITIES.get(city_lower, "")
            if not city_slug and city_lower:
                # Try partial match
                for name, slug in CITIES.items():
                    if city_lower in name or name in city_lower:
                        city_slug = slug
                        break
        
        # District slug
        if profile.districts and city_slug:
            dist_lower = profile.districts[0].lower().strip()
            # Try to match the district
            for name, slug in DISTRICTS.items():
                if dist_lower in name or name in dist_lower:
                    # Krisha uses "almaty--bostandykskij-rajon" format, so we replace trailing slash
                    city_slug = city_slug.rstrip('/') + "-" + slug + "/"
                    break

        base = _RENT_URL + city_slug

        # Query parameters
        parts: list[str] = []
        if profile.has_photo:
            parts.append("das[_sys.hasphoto]=1")
        if profile.furniture is True:
            parts.append("das[live.furniture]=1")
        elif profile.furniture is False:
            parts.append("das[live.furniture]=2")
        if profile.rooms:
            if len(profile.rooms) == 1:
                parts.append(f"das[live.rooms]={profile.rooms[0]}")
            else:
                for r in profile.rooms:
                    val = "5.100" if r >= 5 else str(r)
                    parts.append(f"das[live.rooms][]={val}")
        if profile.price_min is not None:
            parts.append(f"das[price][from]={profile.price_min}")
        if profile.price_max is not None:
            parts.append(f"das[price][to]={profile.price_max}")
        if profile.owner_only:
            parts.append("das[who]=1")
        if profile.bounding_box and len(profile.bounding_box) == 4:
            lat_min, lon_min, lat_max, lon_max = profile.bounding_box
            # Krisha polygon is just a list of points: pLat,Lon,Lat,Lon...
            # We create a rectangle from the bounding box
            points = [
                f"{lat_min},{lon_min}",
                f"{lat_max},{lon_min}",
                f"{lat_max},{lon_max}",
                f"{lat_min},{lon_max}"
            ]
            areas_str = "p" + ",".join(points)
            parts.append(f"areas={areas_str}")

        if parts:
            return base + "?" + "&".join(parts)
        return base
