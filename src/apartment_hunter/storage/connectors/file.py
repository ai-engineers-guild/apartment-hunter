"""Local JSON file storage backend."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from apartment_hunter.core.interfaces import StorageBackend
from apartment_hunter.core.models import Apartment, SearchProfile

log = logging.getLogger(__name__)


class FileStore(StorageBackend):
    """Stores apartments and profiles in a local JSON file."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.data: dict[str, Any] = {
            "apartments": {},
            "profiles": {},
            "history": {},
            "notified": {},
        }
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, encoding="utf-8") as f:
                    self.data = json.load(f)
            except json.JSONDecodeError:
                log.warning("JSON file corrupted, starting fresh.")
                self._save()
        else:
            self._save()

    def _save(self) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def upsert_apartment(self, apt: Apartment) -> bool:
        sid = apt.source_id
        is_new = sid not in self.data["apartments"]

        apt_data = apt.to_dict()

        # If exists, preserve existing LLM analysis in stored data
        if not is_new:
            existing = self.data["apartments"][sid]
            for llm_key in (
                "llm_score",
                "llm_summary",
                "llm_pros",
                "llm_cons",
                "llm_renovation_quality",
            ):
                if existing.get(llm_key) is not None:
                    apt_data[llm_key] = existing[llm_key]
            apt_data["is_new"] = False

        self.data["apartments"][sid] = apt_data
        self._save()
        return is_new

    def get_apartment(self, source_id: str) -> Apartment | None:
        d_orig = self.data["apartments"].get(source_id)
        if not d_orig:
            return None
        d = dict(d_orig)
        # Convert strings back to datetimes
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        if isinstance(d.get("scraped_at"), str):
            d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
        return Apartment(**d)

    def search_apartments(self, **filters: Any) -> list[Apartment]:
        results = []
        for sid, d in self.data["apartments"].items():
            match = True
            for k, v in filters.items():
                if v is None:
                    continue
                if k == "city" and (
                    not d.get("city") or v.lower() not in d["city"].lower()
                ):
                    match = False
                elif k == "district" and (
                    not d.get("district") or v.lower() not in d["district"].lower()
                ):
                    match = False
                elif k == "rooms" and d.get("rooms") not in (
                    v if isinstance(v, list) else [v]
                ):
                    match = False
                elif k == "price_min" and d.get("price", 0) < v:
                    match = False
                elif k == "price_max" and d.get("price", float("inf")) > v:
                    match = False
                elif k == "area_min" and d.get("area_total", 0) < v:
                    match = False
                elif k == "area_max" and d.get("area_total", float("inf")) > v:
                    match = False
                elif k == "min_score" and (d.get("llm_score") or 0) < v:
                    match = False
                elif (
                    k == "owner_only"
                    and v
                    and "собственник" not in str(d.get("owner_type", "")).lower()
                ):
                    match = False
            if match:
                apt = self.get_apartment(sid)
                if apt:
                    results.append(apt)
        results.sort(key=lambda a: a.scraped_at or datetime.min, reverse=True)
        return results[:100]

    def get_new_apartments(self, since_hours: int = 24) -> list[Apartment]:
        cutoff = datetime.now(UTC) - timedelta(hours=since_hours)
        results = []
        for sid, d in self.data["apartments"].items():
            scraped_at_val = d["scraped_at"]
            if isinstance(scraped_at_val, str):
                scraped = datetime.fromisoformat(scraped_at_val)
            else:
                scraped = scraped_at_val
            if d.get("is_new") and scraped >= cutoff:
                apt = self.get_apartment(sid)
                if apt:
                    results.append(apt)
        results.sort(key=lambda a: a.llm_score or 0, reverse=True)
        return results[:50]

    def record_price(self, source_id: str, price: int) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        history = self.data["history"].setdefault(source_id, [])
        if not any(h["date"] == today and h["price"] == price for h in history):
            history.append({"price": price, "date": today})
            self._save()

    def get_price_history(self, source_id: str) -> list[dict]:  # type: ignore[override]
        return list(self.data["history"].get(source_id, []))

    def get_all_source_ids(self) -> set[str]:
        return set(self.data["apartments"].keys())

    def save_profile(self, profile: SearchProfile) -> None:
        self.data["profiles"][profile.id] = profile.to_dict()
        self._save()

    def get_profile(self, profile_id: str) -> SearchProfile | None:
        d = self.data["profiles"].get(profile_id)
        return SearchProfile.from_dict(d) if d else None

    def list_profiles(self, active_only: bool = True) -> list[SearchProfile]:
        profs = [SearchProfile.from_dict(p) for p in self.data["profiles"].values()]
        if active_only:
            profs = [p for p in profs if p.active]
        return profs

    def delete_profile(self, profile_id: str) -> bool:
        if profile_id in self.data["profiles"]:
            del self.data["profiles"][profile_id]
            self._save()
            return True
        return False

    def mark_notified(self, source_id: str, profile_id: str, channel: str) -> None:
        key = f"{source_id}_{profile_id}_{channel}"
        self.data["notified"][key] = datetime.now(UTC).isoformat()
        self._save()

    def was_notified(self, source_id: str, profile_id: str, channel: str) -> bool:
        key = f"{source_id}_{profile_id}_{channel}"
        return key in self.data["notified"]

    def get_stats(self) -> dict[str, Any]:
        apts = list(self.data["apartments"].values())
        return {
            "total_apartments": len(apts),
            "new_apartments": sum(1 for a in apts if a.get("is_new")),
            "analyzed_apartments": sum(
                1 for a in apts if a.get("llm_score") is not None
            ),
            "active_profiles": len(self.list_profiles(active_only=True)),
            "avg_price": int(
                sum(a["price"] for a in apts if a.get("price")) / max(len(apts), 1)
            ),
            "avg_score": round(
                sum(a["llm_score"] for a in apts if a.get("llm_score"))
                / max(sum(1 for a in apts if a.get("llm_score")), 1),
                1,
            ),
            "top_cities": {},  # Simplified for FileStore
        }
