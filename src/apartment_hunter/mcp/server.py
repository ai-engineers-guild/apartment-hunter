"""FastMCP server exposing apartment search, analysis, and management tools.

Run with:
    python -m apartment_hunter.mcp.server          # stdio (Claude Desktop)
    fastmcp dev src/apartment_hunter/mcp/server.py  # dev inspector
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP

from apartment_hunter.config import get_settings
from apartment_hunter.core.models import Apartment, SearchProfile
from apartment_hunter.storage.factory import get_storage, get_vector_store

log = logging.getLogger(__name__)

# ── Lazy singleton accessors ───────────────────────────────────────────────────

_settings = get_settings()
_db = None
_vector = None
_analyzer = None


def _get_db():
    global _db
    if _db is None:
        _db = get_storage()
    return _db


def _get_vector():
    global _vector
    if _vector is None:
        _vector = get_vector_store()
    return _vector


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        from apartment_hunter.analysis.llm_analyzer import LLMAnalyzer

        _analyzer = LLMAnalyzer()
    return _analyzer


def _pipeline():
    from apartment_hunter.ingest.pipeline import IngestPipeline
    from apartment_hunter.notifications.telegram import TelegramNotifier

    settings = get_settings()
    notifiers = []
    if settings.telegram_bot_token:
        notifiers.append(TelegramNotifier())
    return IngestPipeline(db=_get_db(), vector=_get_vector(), notifiers=notifiers)


# ── MCP Server ─────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="apartment-hunter",
    instructions=(
        "Apartment Hunter MCP server for searching, analyzing, and tracking "
        "rental apartments in Kazakhstan. Supports krisha.kz as a data source. "
        "Use search_apartments for filter-based search, semantic_search for "
        "natural language queries, and create_search_profile to set up ongoing monitoring. "
        "All text is in Russian. Prices are in KZT (Kazakhstani tenge)."
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
#  TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def search_apartments(
    city: str | None = None,
    rooms: list[int] | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    area_min: float | None = None,
    area_max: float | None = None,
    district: str | None = None,
    min_score: float | None = None,
    owner_only: bool = False,
) -> str:
    """Search apartments by structured filters.

    Returns a list of apartments matching the given criteria.
    Use this for precise filtering by price, rooms, area, district, etc.
    For free-text queries like 'cozy apartment near park', use semantic_search instead.
    """
    filters: dict[str, Any] = {}
    if city:
        filters["city"] = city
    if rooms:
        filters["rooms"] = rooms
    if price_min is not None:
        filters["price_min"] = price_min
    if price_max is not None:
        filters["price_max"] = price_max
    if area_min is not None:
        filters["area_min"] = area_min
    if area_max is not None:
        filters["area_max"] = area_max
    if district:
        filters["district"] = district
    if min_score is not None:
        filters["min_score"] = min_score
    if owner_only:
        filters["owner_only"] = True

    results = _get_db().search_apartments(**filters)
    if not results:
        return "Квартиры по заданным фильтрам не найдены."
    return _format_apartments(results)


@mcp.tool()
async def semantic_search(
    query: str,
    n_results: int = 10,
    city: str | None = None,
    price_max: int | None = None,
    rooms: int | None = None,
) -> str:
    """Search apartments by natural language query using semantic/vector search.

    Examples: 'уютная квартира с видом на горы рядом с метро',
    'большая квартира с евроремонтом в центре'.
    Optionally filter by city, max price, or room count.
    """
    where: dict | None = None
    if city or price_max or rooms:
        conditions: list[dict] = []
        if city:
            conditions.append({"city": {"$eq": city}})
        if price_max:
            conditions.append({"price": {"$lte": price_max}})
        if rooms:
            conditions.append({"rooms": {"$eq": rooms}})
        if len(conditions) == 1:
            where = conditions[0]
        elif conditions:
            where = {"$and": conditions}

    source_ids = _get_vector().semantic_search(query, n_results=n_results, where=where)
    if not source_ids:
        return "Ничего не найдено по вашему запросу."

    apartments = [_get_db().get_apartment(sid) for sid in source_ids]
    apartments = [a for a in apartments if a is not None]
    return _format_apartments(apartments)


@mcp.tool()
async def get_apartment_details(source_id: str) -> str:
    """Get full details for a specific apartment by its source_id (e.g. 'krisha:1013405508').

    Returns all available fields including LLM analysis, price history, and photos.
    """
    apt = _get_db().get_apartment(source_id)
    if not apt:
        return f"Квартира {source_id} не найдена."

    history = _get_db().get_price_history(source_id)
    card = apt.to_card()
    if history and len(history) > 1:
        card += "\n\n📈 История цен:"
        for h in history:
            card += f"\n  {h['date']}: {h['price']:,} KZT".replace(",", " ")
    if apt.description:
        card += f"\n\n📝 Описание:\n{apt.description[:1500]}"
    if apt.photo_urls:
        card += f"\n\n📸 Фото ({len(apt.photo_urls)}):"
        for i, url in enumerate(apt.photo_urls[:5], 1):
            card += f"\n  {i}. {url}"
    return card


@mcp.tool()
async def analyze_apartment(source_id: str) -> str:
    """Run LLM analysis on a specific apartment.

    Scores the apartment 0-10 based on price/quality ratio, condition,
    location, and other factors. Returns score, pros, cons, and summary.
    Forces re-analysis even if already analyzed.
    """
    apt = _get_db().get_apartment(source_id)
    if not apt:
        return f"Квартира {source_id} не найдена."

    result = await _get_analyzer().analyze(apt)

    # Update in-memory object
    apt.llm_score = result.score
    apt.llm_summary = result.summary
    apt.llm_pros = result.pros
    apt.llm_cons = result.cons
    apt.llm_renovation_quality = result.renovation_quality

    # Save updated apartment and refresh vector metadata.
    _get_db().upsert_apartment(apt)
    _get_vector().upsert(apt)

    lines = [
        f"📊 Анализ квартиры {source_id}",
        f"⭐ Оценка: {result.score:.1f}/10",
        f"💡 {result.summary}",
    ]
    if result.pros:
        lines.append("✅ Плюсы: " + ", ".join(result.pros))
    if result.cons:
        lines.append("⚠️ Минусы: " + ", ".join(result.cons))
    if result.renovation_quality:
        lines.append(f"🔧 Ремонт: {result.renovation_quality}")
    return "\n".join(lines)


@mcp.tool()
async def download_apartment_photos(source_id: str, limit: int = 3) -> str:
    """Download apartment photos locally so the AI agent can inspect them.

    Returns the absolute paths of the downloaded images. You (the AI) can then
    use your `view_file` tool on these paths to visually analyze the apartment.
    """
    apt = _get_db().get_apartment(source_id)
    if not apt:
        return f"Квартира {source_id} не найдена."

    if not apt.photo_urls:
        return f"У квартиры {source_id} нет фотографий."

    # Create scratch directory
    scratch_dir = (
        Path(_settings.db_path).parent.parent
        / "scratch"
        / "photos"
        / source_id.replace(":", "_")
    )
    scratch_dir.mkdir(parents=True, exist_ok=True)

    urls = apt.photo_urls[:limit]
    downloaded_paths: list[str] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        for i, url in enumerate(urls, 1):
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()

                # Determine extension or default to jpg
                ext = ".jpg"
                if ".png" in url.lower():
                    ext = ".png"
                if ".webp" in url.lower():
                    ext = ".webp"

                filepath = scratch_dir / f"photo_{i}{ext}"
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                downloaded_paths.append(str(filepath.absolute()))
            except Exception as e:
                log.warning("Failed to download %s: %s", url, e)

    if not downloaded_paths:
        return "Не удалось скачать фотографии."

    lines = [
        "✅ Фотографии успешно скачаны. "
        "Абсолютные пути для использования в view_file:\n"
    ]
    for path in downloaded_paths:
        lines.append(f"- {path}")

    return "\n".join(lines)


@mcp.tool()
async def get_top_apartments(
    limit: int = 10,
    city: str | None = None,
    rooms: list[int] | None = None,
    price_max: int | None = None,
) -> str:
    """Get top-rated apartments sorted by LLM score.

    Returns the highest-scored apartments, optionally filtered by city, rooms, or price.
    Only returns apartments that have been analyzed.
    """
    filters: dict[str, Any] = {"min_score": 0.1}
    if city:
        filters["city"] = city
    if rooms:
        filters["rooms"] = rooms
    if price_max is not None:
        filters["price_max"] = price_max

    results = _get_db().get_top_apartments(limit=limit, **filters)
    if not results:
        return "Нет проанализированных квартир. Запустите run_ingestion сначала."
    return _format_apartments(results)


@mcp.tool()
async def get_new_apartments(since_hours: int = 24) -> str:
    """Get apartments discovered in the last N hours (default: 24).

    Shows the most recent apartments sorted by score.
    """
    results = _get_db().get_new_apartments(since_hours=since_hours)
    if not results:
        return f"Новых квартир за последние {since_hours}ч не найдено."
    return f"Найдено {len(results)} новых квартир:\n\n" + _format_apartments(results)


@mcp.tool()
async def compare_apartments(source_ids: list[str]) -> str:
    """Compare 2-5 apartments side by side.

    Provide a list of source_ids to compare their key characteristics.
    """
    if len(source_ids) < 2:
        return "Укажите минимум 2 квартиры для сравнения."
    if len(source_ids) > 5:
        source_ids = source_ids[:5]

    apartments = [_get_db().get_apartment(sid) for sid in source_ids]
    apartments = [a for a in apartments if a is not None]
    if len(apartments) < 2:
        return "Недостаточно квартир найдено для сравнения."

    lines = ["📊 Сравнение квартир\n"]
    header = f"{'Параметр':<20}"
    for i, a in enumerate(apartments, 1):
        header += f" | {'#' + str(i):<20}"
    lines.append(header)
    lines.append("-" * len(header))

    fields = [
        ("Цена (KZT)", lambda a: f"{a.price:,}".replace(",", " ")),
        ("Комнат", lambda a: str(a.rooms or "—")),
        ("Площадь (м²)", lambda a: str(a.area_total or "—")),
        (
            "Цена/м²",
            lambda a: (
                f"{a.price_per_sqm:,.0f}".replace(",", " ") if a.price_per_sqm else "—"
            ),
        ),
        ("Этаж", lambda a: f"{a.floor}/{a.floor_total}" if a.floor else "—"),
        ("Тип дома", lambda a: a.building_type or "—"),
        ("Год", lambda a: str(a.year_built or "—")),
        ("Состояние", lambda a: a.condition or "—"),
        ("Мебель", lambda a: a.furniture or "—"),
        ("Район", lambda a: a.district or "—"),
        ("Оценка", lambda a: f"{a.llm_score:.1f}" if a.llm_score else "—"),
        ("Фото", lambda a: str(len(a.photo_urls))),
    ]

    for name, getter in fields:
        row = f"{name:<20}"
        for a in apartments:
            row += f" | {getter(a):<20}"
        lines.append(row)

    lines.append("")
    for i, a in enumerate(apartments, 1):
        lines.append(f"#{i} 🔗 {a.url}")

    return "\n".join(lines)


@mcp.tool()
async def get_price_history(source_id: str) -> str:
    """Get price change history for an apartment."""
    history = _get_db().get_price_history(source_id)
    if not history:
        return f"История цен для {source_id} не найдена."
    lines = [f"📈 История цен для {source_id}:"]
    for h in history:
        lines.append(f"  {h['date']}: {h['price']:,} KZT".replace(",", " "))
    if len(history) > 1:
        diff = history[-1]["price"] - history[0]["price"]
        pct = (diff / history[0]["price"]) * 100 if history[0]["price"] else 0
        sign = "+" if diff >= 0 else ""
        lines.append(
            f"\nИзменение: {sign}{diff:,} KZT ({sign}{pct:.1f}%)".replace(",", " ")
        )
    return "\n".join(lines)


# ── Profile Management ─────────────────────────────────────────────────────────


@mcp.tool()
async def create_search_profile(
    name: str,
    sources: list[str] | None = None,
    city: str | None = None,
    districts: list[str] | None = None,
    rooms: list[int] | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    area_min: float | None = None,
    area_max: float | None = None,
    owner_only: bool = False,
    has_photo: bool = True,
    furniture: bool | None = None,
    keywords: list[str] | None = None,
    min_score: float | None = None,
    bounding_box: list[float] | None = None,
) -> str:
    """Create a search profile for ongoing apartment monitoring.

    The profile defines filters and preferences. The ingestion pipeline will
    use these profiles to fetch new apartments and send notifications.

    Args:
        name: Human-readable profile name, e.g. 'Алматы 2к до 300т'
        sources: Source names, e.g. ['krisha.kz']; defaults to all registered adapters
        city: City name in Russian, e.g. 'Алматы', 'Астана'
        districts: Optional list of district names
        rooms: List of room counts, e.g. [1, 2]
        price_min/price_max: Price range in KZT
        area_min/area_max: Area range in m²
        owner_only: Only from owners (no agencies)
        has_photo: Only with photos
        furniture: True=with furniture, False=without, None=any
        keywords: Semantic search keywords for RAG matching
        min_score: Minimum LLM score for notifications (0.0-10.0)
        bounding_box: [lat_min, lon_min, lat_max, lon_max] list of floats for map bounding box
    """
    profile = SearchProfile(
        name=name,
        sources=sources or [],
        city=city,
        districts=districts,
        rooms=rooms,
        price_min=price_min,
        price_max=price_max,
        area_min=area_min,
        area_max=area_max,
        owner_only=owner_only,
        has_photo=has_photo,
        furniture=furniture,
        keywords=keywords,
        min_score=min_score,
        bounding_box=bounding_box,
    )
    _get_db().save_profile(profile)
    profile_json = json.dumps(profile.to_dict(), indent=2, ensure_ascii=False)
    return (
        f"✅ Профиль '{name}' создан (ID: {profile.id})\n\n"
        f"Параметры:\n{profile_json}"
    )


@mcp.tool()
async def list_search_profiles() -> str:
    """List all active search profiles."""
    profiles = _get_db().list_profiles(active_only=True)
    if not profiles:
        return "Нет активных профилей поиска. Создайте один с помощью create_search_profile."
    lines = ["📋 Активные профили поиска:\n"]
    for p in profiles:
        lines.append(f"  ID: {p.id}")
        lines.append(f"  Имя: {p.name}")
        if p.city:
            lines.append(f"  Город: {p.city}")
        if p.rooms:
            lines.append(f"  Комнат: {p.rooms}")
        if p.price_min or p.price_max:
            price_range = f"{p.price_min or 0:,} – {p.price_max or '∞':,}".replace(
                ",", " "
            )
            lines.append(f"  Цена: {price_range} KZT")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def delete_search_profile(profile_id: str) -> str:
    """Delete a search profile by ID."""
    if _get_db().delete_profile(profile_id):
        return f"✅ Профиль {profile_id} удалён."
    return f"❌ Профиль {profile_id} не найден."


# ── Ingestion ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def run_ingestion(profile_id: str | None = None) -> str:
    """Run the data ingestion pipeline.

    Fetches new apartments from all sources for the specified profile
    (or all active profiles if none specified), analyzes them, and sends notifications.
    This may take several minutes depending on the number of pages to scrape.
    """
    pipeline = _pipeline()

    if profile_id:
        profile = _get_db().get_profile(profile_id)
        if not profile:
            return f"Профиль {profile_id} не найден."
        new = await pipeline.run_profile(profile)
        return _format_ingestion_result(profile.name, new)
    else:
        results = await pipeline.run_all_profiles()
        if not results:
            return (
                "Нет активных профилей. Создайте профиль через create_search_profile."
            )
        lines = ["✅ Сбор данных завершён:\n"]
        for name, count in results.items():
            lines.append(f"  {name}: {count} новых квартир")
        return "\n".join(lines)


# ── Stats ──────────────────────────────────────────────────────────────────────


@mcp.tool()
async def get_stats() -> str:
    """Get statistics about the apartment database.

    Shows total apartments, new apartments, analyzed count, average prices, scores, etc.
    """
    stats = _get_db().get_stats()
    lines = [
        "📊 Статистика Apartment Hunter\n",
        f"  Всего квартир: {stats['total_apartments']}",
        f"  Новых: {stats['new_apartments']}",
        f"  Проанализировано: {stats['analyzed_apartments']}",
        f"  Активных профилей: {stats['active_profiles']}",
        (
            f"  Средняя цена: {stats['avg_price']:,} KZT".replace(",", " ")
            if stats["avg_price"]
            else "  Средняя цена: —"
        ),
    ]
    if stats["avg_score"]:
        lines.append(f"  Средняя оценка: {stats['avg_score']}/10")
    if stats["top_cities"]:
        lines.append("\n  🏙️ Города:")
        for city, count in stats["top_cities"].items():
            lines.append(f"    {city}: {count}")
    lines.append(f"\n  🗂️ Вектор-хранилище: {_get_vector().count} документов")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  RESOURCES
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.resource("apartment://{source_id}")
def apartment_resource(source_id: str) -> str:
    """Full apartment data as a resource."""
    apt = _get_db().get_apartment(source_id)
    if not apt:
        return f"Apartment {source_id} not found."
    return json.dumps(apt.to_dict(), indent=2, ensure_ascii=False)


@mcp.resource("stats://overview")
def stats_resource() -> str:
    """Database statistics as a resource."""
    return json.dumps(_get_db().get_stats(), indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
#  PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.prompt()
def apartment_review(source_id: str) -> str:
    """Generate a detailed apartment review prompt."""
    apt = _get_db().get_apartment(source_id)
    if not apt:
        return f"Квартира {source_id} не найдена."
    card = apt.to_card()
    return (
        f"Проанализируй эту квартиру для долгосрочной аренды и дай развёрнутую оценку:\n\n"
        f"{card}\n\n"
        f"Описание: {apt.description or 'Не указано'}\n\n"
        f"Оцени: соотношение цена/качество, расположение, состояние, "
        f"пригодность для проживания. Укажи на что обратить внимание "
        f"при просмотре. Дай итоговую рекомендацию: снимать или нет."
    )


@mcp.prompt()
def market_analysis(city: str = "Алматы", rooms: int = 2) -> str:
    """Generate a market analysis prompt for a specific city/room count."""
    apartments = _get_db().search_apartments(city=city, rooms=[rooms])
    if not apartments:
        return f"Нет данных по {rooms}-комн. квартирам в {city}."

    prices = [a.price for a in apartments if a.price > 0]
    avg_price = sum(prices) / len(prices) if prices else 0
    min_price = min(prices) if prices else 0
    max_price = max(prices) if prices else 0

    return (
        f"Проанализируй рынок аренды {rooms}-комнатных квартир в {city} "
        f"на основе {len(apartments)} объявлений:\n\n"
        f"Средняя цена: {avg_price:,.0f} KZT\n"
        f"Минимум: {min_price:,} KZT\n"
        f"Максимум: {max_price:,} KZT\n\n"
        f"Дай рекомендации по оптимальному бюджету и на что обращать внимание."
    ).replace(",", " ")


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _format_apartments(apartments: list[Apartment]) -> str:
    cards = [apt.to_card() for apt in apartments[:20]]
    return f"Найдено {len(apartments)} квартир:\n\n" + "\n\n---\n\n".join(cards)


def _format_ingestion_result(profile_name: str, apartments: list[Apartment]) -> str:
    """Render current-ingest delta for a single profile."""
    lines = [
        f"✅ Сбор данных завершён для профиля '{profile_name}'",
        f"Найдено новых квартир: {len(apartments)}",
    ]
    if apartments:
        lines.append("")
        lines.append(_format_apartments(apartments[:5]))
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    """Run the MCP server."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    mcp.run()


if __name__ == "__main__":
    main()
