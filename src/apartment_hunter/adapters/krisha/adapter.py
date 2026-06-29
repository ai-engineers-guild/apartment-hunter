"""Krisha.kz source adapter – implements SourceAdapter interface."""

from __future__ import annotations

import asyncio
import logging
import re

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
        self._delay = delay
        self._timeout = timeout

    @property
    def source_name(self) -> str:
        return "krisha.kz"

    async def fetch_listings(
        self,
        profile: SearchProfile,
        *,
        max_pages: int = 5,
        known_ids: set[str] | None = None,
    ) -> list[Apartment]:
        """Fetch listings matching a SearchProfile, up to max_pages.

        When the profile specifies multiple districts, a separate paginated
        crawl is issued per district and results are merged (deduplicated by
        ``source_id``).
        """
        urls = self._build_search_urls(profile)

        seen: set[str] = set()
        apartments: list[Apartment] = []

        async with KrishaScraper(delay=self._delay, timeout=self._timeout) as scraper:
            for url in urls:
                page_apts = await self._fetch_pages(scraper, url, max_pages, known_ids=known_ids)
                for apt in page_apts:
                    if apt.source_id not in seen:
                        seen.add(apt.source_id)
                        apartments.append(apt)

        log.info("Krisha: fetch complete — %d apartments collected", len(apartments))

        # Post-filter by polygons if provided
        if profile.polygons:
            filtered_apartments = []
            for apt in apartments:
                if apt.lat is not None and apt.lon is not None:
                    # Keep if it is inside ANY of the provided polygons
                    in_any = any(
                        KrishaAdapter._is_point_in_polygon(apt.lat, apt.lon, poly) for poly in profile.polygons
                    )
                    if in_any:
                        filtered_apartments.append(apt)
            log.info("Krisha: %d apartments remained after polygon filter", len(filtered_apartments))
            return filtered_apartments

        # Fallback to deprecated bounding_box filter
        if profile.bounding_box and len(profile.bounding_box) == 4:
            lat_min, lon_min, lat_max, lon_max = profile.bounding_box
            filtered_apartments = []
            for apt in apartments:
                if apt.lat is not None and apt.lon is not None:
                    if lat_min <= apt.lat <= lat_max and lon_min <= apt.lon <= lon_max:
                        filtered_apartments.append(apt)
            log.info("Krisha: %d apartments remained after bounding box filter", len(filtered_apartments))
            return filtered_apartments

        return apartments

    async def get_details(self, source_id: str) -> Apartment | None:
        """Fetch a single apartment by krisha ID (e.g. 'krisha:1013405508')."""
        krisha_id = source_id.replace("krisha:", "")
        url = f"{_BASE}/a/show/{krisha_id}"
        async with KrishaScraper(delay=self._delay, timeout=self._timeout) as scraper:
            html = await scraper.fetch(url)
        if not html:
            return None
        return parse_detail_page(html, url)

    # ── Pagination engine ─────────────────────────────────────────────

    async def _fetch_pages(
        self,
        scraper: KrishaScraper,
        start_url: str,
        max_pages: int,
        known_ids: set[str] | None = None,
    ) -> list[Apartment]:
        """Paginate through listings starting from *start_url*."""
        log.info("Krisha: starting fetch from %s (max %s pages)", start_url, max_pages or "∞")

        apartments: list[Apartment] = []
        current_url: str | None = start_url
        page_num = 1

        while current_url and (max_pages == 0 or page_num <= max_pages):
            html = await scraper.fetch_with_delay(current_url)
            if not html:
                log.warning("Krisha: failed to fetch page %d", page_num)
                break

            ad_urls, total, next_url = parse_listing_page(html)
            if page_num == 1:
                log.info("Krisha: found %d total ads", total)

            if not ad_urls:
                break

            # Extract source_id from each URL and filter known
            page_ids = [self._url_to_source_id(u) for u in ad_urls]
            new_urls = [u for u, sid in zip(ad_urls, page_ids) if sid and (known_ids is None or sid not in known_ids)]

            # Detail pages are independent; bounded fan-out keeps fetches polite.
            sem = asyncio.Semaphore(10)

            async def _fetch_detail(detail_url: str) -> Apartment | None:
                async with sem:
                    detail_html = await scraper.fetch_with_delay(detail_url)
                    if not detail_html:
                        return None
                    return parse_detail_page(detail_html, detail_url)

            if known_ids is not None:
                new_count = len(new_urls)
                log.info("Krisha: page %d — %d new / %d total ads", page_num, new_count, len(ad_urls))
                if new_count == 0:
                    log.info("Krisha: all ads on this page already known — stopping early")
                    break
                # Only fetch details for new ones
                tasks = [_fetch_detail(u) for u in new_urls]
            else:
                tasks = [_fetch_detail(u) for u in ad_urls]
            results = await asyncio.gather(*tasks)

            for apt in results:
                if apt:
                    apartments.append(apt)

            max_str = str(max_pages) if max_pages > 0 else "∞"
            log.info(
                "Krisha: processed page %d/%s (%d apartments so far)",
                page_num,
                max_str,
                len(apartments),
            )
            current_url = next_url
            page_num += 1

        return apartments

    @staticmethod
    def _url_to_source_id(url: str) -> str | None:
        m = re.search(r"/a/show/(\d+)", url)
        return f"krisha:{m.group(1)}" if m else None

    # ── URL builder ───────────────────────────────────────────────────

    @staticmethod
    def _build_search_urls(profile: SearchProfile) -> list[str]:
        """Build one or more krisha.kz search URLs from a SearchProfile.

        When multiple districts are specified, a separate URL is generated for
        each district (Krisha does not support multi-district in a single
        query).  Returns a list with at least one URL.
        """
        raw = profile.districts or []
        districts: list[str | None] = list(raw) if raw else [None]
        urls: list[str] = []
        for district in districts:
            url = KrishaAdapter._build_search_url(profile, district_override=district)
            urls.append(url)
        return urls

    @staticmethod
    def _build_search_url(profile: SearchProfile, *, district_override: str | None = None) -> str:
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
        district_name = district_override
        if district_name and city_slug:
            dist_lower = district_name.lower().strip()
            # Try to match the district
            for name, slug in DISTRICTS.items():
                if dist_lower in name or name in dist_lower:
                    # Krisha uses "almaty--bostandykskij-rajon" format.
                    city_slug = city_slug.rstrip("/") + "-" + slug + "/"
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
        # Pass the first polygon as a server-side geographic filter.
        # Krisha accepts areas=p{lat1},{lon1},{lat2},{lon2},... and returns only
        # listings within that polygon, which avoids fetching thousands of
        # city-wide ads and then post-filtering them.
        if profile.polygons:
            poly = profile.polygons[0]
            coords = ",".join(f"{pt[0]},{pt[1]}" for pt in poly)
            # Ensure closed polygon (Krisha expects first == last point)
            first, last = poly[0], poly[-1]
            if first[0] != last[0] or first[1] != last[1]:
                coords += f",{first[0]},{first[1]}"
            parts.append(f"areas=p{coords}")

        if parts:
            return base + "?" + "&".join(parts)
        return base

    @staticmethod
    def _is_point_in_polygon(x: float, y: float, poly: list[list[float]]) -> bool:
        """
        Ray-casting algorithm to determine if a point (x, y) is inside a polygon.
        x corresponds to latitude, y corresponds to longitude.
        poly is a list of [lat, lon] points.
        """
        n = len(poly)
        inside = False
        p1x, p1y = poly[0]
        for i in range(1, n + 1):
            p2x, p2y = poly[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside
