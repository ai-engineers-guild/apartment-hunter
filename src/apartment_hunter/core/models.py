"""Domain models – source-agnostic data structures.

Every adapter maps its raw data into these models so the rest of the system
never needs to know where the data came from.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

# ── Apartment ──────────────────────────────────────────────────────────────────


@dataclass
class Apartment:
    """Canonical apartment representation used across the entire system."""

    # Identity
    source_id: str  # e.g. "krisha:1013405508"
    source: str  # e.g. "krisha.kz"
    url: str

    # Price
    price: int  # in local currency (KZT for Kazakhstan)
    currency: str = "KZT"

    # Core characteristics
    title: str | None = None
    rooms: int | None = None
    area_total: float | None = None
    area_living: float | None = None
    area_kitchen: float | None = None
    floor: int | None = None
    floor_total: int | None = None

    # Building
    building_type: str | None = None  # "панельный", "кирпичный", "монолитный"
    year_built: int | None = None

    # Condition
    condition: str | None = None  # "евроремонт", "хорошее", "среднее"
    furniture: str | None = None  # "да", "частично", "нет"

    # Location
    address: str | None = None
    city: str | None = None
    district: str | None = None
    lat: float | None = None
    lon: float | None = None

    # Content
    description: str | None = None
    photo_urls: list[str] = field(default_factory=list)

    # Author
    owner_type: str | None = None  # "собственник", "агентство", "риэлтор"

    # Timestamps
    created_at: datetime | None = None
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # LLM-enriched fields (filled after analysis)
    llm_summary: str | None = None
    llm_score: float | None = None  # 0.0 – 10.0
    llm_renovation_quality: str | None = None
    llm_pros: list[str] | None = None
    llm_cons: list[str] | None = None

    # Tracking
    is_new: bool = True

    # ── Helpers ────────────────────────────────────────────────────────

    @property
    def price_per_sqm(self) -> float | None:
        if self.price and self.area_total and self.area_total > 0:
            return round(self.price / self.area_total, 0)
        return None

    def to_embedding_text(self) -> str:
        """Build a rich text string for embedding generation."""
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        if self.rooms:
            parts.append(f"{self.rooms}-комнатная квартира")
        if self.area_total:
            parts.append(f"{self.area_total} м²")
        if self.price:
            parts.append(f"{self.price:,} {self.currency}".replace(",", " "))
        if self.address:
            parts.append(self.address)
        if self.district:
            parts.append(f"район {self.district}")
        if self.city:
            parts.append(self.city)
        if self.condition:
            parts.append(f"состояние: {self.condition}")
        if self.furniture:
            parts.append(f"мебель: {self.furniture}")
        if self.building_type:
            parts.append(f"дом: {self.building_type}")
        if self.floor and self.floor_total:
            parts.append(f"этаж {self.floor}/{self.floor_total}")
        if self.description:
            # Truncate very long descriptions for embedding
            desc = self.description[:500]
            parts.append(desc)
        return ". ".join(parts)

    def to_search_metadata(self) -> dict[str, Any]:
        """Metadata dict for ChromaDB filtering."""
        meta: dict[str, Any] = {"source": self.source}
        if self.price is not None:
            meta["price"] = self.price
        if self.rooms is not None:
            meta["rooms"] = self.rooms
        if self.area_total is not None:
            meta["area_total"] = self.area_total
        if self.city:
            meta["city"] = self.city
        if self.district:
            meta["district"] = self.district
        if self.llm_score is not None:
            meta["llm_score"] = self.llm_score
        if self.floor is not None:
            meta["floor"] = self.floor
        return meta

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Serialize datetimes
        for key in ("created_at", "scraped_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    def to_card(self) -> str:
        """Human-readable card for display (Telegram, CLI, etc.)."""
        lines = []
        if self.title:
            lines.append(f"🏠 **{self.title}**")
        if self.rooms and self.area_total:
            lines.append(f"📐 {self.rooms} комн. · {self.area_total} м²")
        lines.append(f"💰 {self.price:,} {self.currency}".replace(",", " "))
        if self.price_per_sqm:
            lines.append(
                f"   ({self.price_per_sqm:,.0f} {self.currency}/м²)".replace(",", " ")
            )
        if self.floor and self.floor_total:
            lines.append(f"🏢 Этаж {self.floor}/{self.floor_total}")
        if self.address:
            lines.append(f"📍 {self.address}")
        if self.condition:
            lines.append(f"🔧 {self.condition}")
        if self.furniture:
            lines.append(f"🪑 Мебель: {self.furniture}")
        if self.llm_score is not None:
            stars = "⭐" * int(round(self.llm_score / 2))
            lines.append(f"📊 Оценка: {self.llm_score:.1f}/10 {stars}")
        if self.llm_summary:
            lines.append(f"💡 {self.llm_summary}")
        if self.llm_pros:
            lines.append("✅ " + " · ".join(self.llm_pros[:3]))
        if self.llm_cons:
            lines.append("⚠️ " + " · ".join(self.llm_cons[:3]))
        lines.append(f"🔗 {self.url}")
        return "\n".join(lines)


# ── Search Profile ─────────────────────────────────────────────────────────────


@dataclass
class SearchProfile:
    """User-defined search criteria + notification preferences."""

    name: str
    sources: list[str] = field(default_factory=lambda: ["krisha.kz"])

    # Filters
    city: str | None = None
    districts: list[str] | None = None
    rooms: list[int] | None = None
    price_min: int | None = None
    price_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    floor_min: int | None = None
    floor_max: int | None = None
    furniture: bool | None = None
    owner_only: bool = False
    has_photo: bool = True
    bounding_box: list[float] | None = None

    # Semantic / keyword filters
    keywords: list[str] | None = None
    description_must_contain: list[str] | None = None
    description_must_not_contain: list[str] | None = None

    # Notifications
    min_score: float | None = None  # minimum LLM score to notify
    notify_telegram: bool = True
    active: bool = True

    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: datetime = field(default_factory=datetime.utcnow)

    def matches(self, apt: Apartment) -> bool:
        """Check if an apartment matches this profile's hard filters."""
        if self.city and apt.city and self.city.lower() not in apt.city.lower():
            return False
        if self.rooms and apt.rooms and apt.rooms not in self.rooms:
            return False
        if self.price_min is not None and apt.price < self.price_min:
            return False
        if self.price_max is not None and apt.price > self.price_max:
            return False
        if (
            self.area_min is not None
            and apt.area_total
            and apt.area_total < self.area_min
        ):
            return False
        if (
            self.area_max is not None
            and apt.area_total
            and apt.area_total > self.area_max
        ):
            return False
        if self.floor_min is not None and apt.floor and apt.floor < self.floor_min:
            return False
        if self.floor_max is not None and apt.floor and apt.floor > self.floor_max:
            return False
        if (
            self.owner_only
            and apt.owner_type
            and "собственник" not in apt.owner_type.lower()
        ):
            return False
        if self.min_score is not None and (
            apt.llm_score is None or apt.llm_score < self.min_score
        ):
            return False
        # Keyword exclusions
        if self.description_must_not_contain and apt.description:
            desc_lower = apt.description.lower()
            for kw in self.description_must_not_contain:
                if kw.lower() in desc_lower:
                    return False
        if self.description_must_contain and apt.description:
            desc_lower = apt.description.lower()
            for kw in self.description_must_contain:
                if kw.lower() not in desc_lower:
                    return False
        return True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(d.get("created_at"), datetime):
            d["created_at"] = d["created_at"].isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SearchProfile:
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Analysis Result ────────────────────────────────────────────────────────────


@dataclass
class AnalysisResult:
    """Output of LLM analysis for a single apartment."""

    score: float  # 0.0 – 10.0
    summary: str
    pros: list[str]
    cons: list[str]
    renovation_quality: str | None = None  # from photo analysis
    raw_response: str | None = None
