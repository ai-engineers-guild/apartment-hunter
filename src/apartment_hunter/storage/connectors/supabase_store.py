"""Supabase storage backend."""

from __future__ import annotations

import logging
from typing import Any

from apartment_hunter.core.interfaces import StorageBackend
from apartment_hunter.core.models import Apartment, SearchProfile

log = logging.getLogger(__name__)


class SupabaseStore(StorageBackend):
    """Supabase-backed storage for apartments."""

    def __init__(self, url: str | None, key: str | None) -> None:
        if not url or not key:
            raise ValueError("supabase_url and supabase_key must be set when using supabase backend")
        try:
            from supabase import Client, create_client
        except ImportError:
            raise ImportError("supabase is required for SupabaseStore. Run: pip install supabase")

        self.client: Client = create_client(url, key)
        log.info("Supabase client initialized.")

    def upsert_apartment(self, apt: Apartment) -> bool:
        row = apt.to_dict()
        try:
            # Check if exists
            res = self.client.table("apartments").select("source_id").eq("source_id", apt.source_id).execute()
            if res.data:
                # Exists, do not overwrite LLM fields
                updates = {
                    k: v
                    for k, v in row.items()
                    if k
                    not in (
                        "source_id",
                        "llm_summary",
                        "llm_score",
                        "llm_renovation_quality",
                        "llm_pros",
                        "llm_cons",
                    )
                }
                self.client.table("apartments").update(updates).eq("source_id", apt.source_id).execute()
                return False
            else:
                self.client.table("apartments").insert(row).execute()
                return True
        except Exception as e:
            log.error("Supabase upsert failed: %s", e)
            return False

    def get_apartment(self, source_id: str) -> Apartment | None:
        res = self.client.table("apartments").select("*").eq("source_id", source_id).execute()
        if res.data:
            return Apartment(**res.data[0])
        return None

    def search_apartments(self, **filters: Any) -> list[Apartment]:
        query = self.client.table("apartments").select("*")
        for k, v in filters.items():
            if v is None:
                continue
            if k == "city":
                query = query.ilike("city", f"%{v}%")
            elif k == "district":
                query = query.ilike("district", f"%{v}%")
            elif k == "rooms":
                if isinstance(v, list):
                    query = query.in_("rooms", v)
                else:
                    query = query.eq("rooms", v)
            elif k == "price_min":
                query = query.gte("price", v)
            elif k == "price_max":
                query = query.lte("price", v)
            elif k == "area_min":
                query = query.gte("area_total", v)
            elif k == "area_max":
                query = query.lte("area_total", v)
            elif k == "min_score":
                query = query.gte("llm_score", v)
            elif k == "owner_only" and v:
                query = query.ilike("owner_type", "%собственник%")

        res = query.order("scraped_at", desc=True).limit(100).execute()
        return [Apartment(**row) for row in res.data]

    def get_new_apartments(self, since_hours: int = 24) -> list[Apartment]:
        import datetime

        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=since_hours)).isoformat()
        res = (
            self.client.table("apartments")
            .select("*")
            .gte("scraped_at", cutoff)
            .eq("is_new", True)
            .order("scraped_at", desc=True)
            .limit(50)
            .execute()
        )
        return [Apartment(**row) for row in res.data]

    def record_price(self, source_id: str, price: int) -> None:
        import datetime

        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        try:
            self.client.table("price_history").insert(
                {"apartment_id": source_id, "price": price, "recorded_at": today}
            ).execute()
        except Exception:
            pass  # Probably already exists

    def get_price_history(self, source_id: str) -> list[dict]:
        res = (
            self.client.table("price_history").select("*").eq("apartment_id", source_id).order("recorded_at").execute()
        )
        return [{"price": r["price"], "date": str(r["recorded_at"])} for r in res.data]

    def save_profile(self, profile: SearchProfile) -> None:
        self.client.table("search_profiles").upsert(
            {
                "id": profile.id,
                "name": profile.name,
                "config": profile.to_dict(),
                "active": profile.active,
            }
        ).execute()

    def get_profile(self, profile_id: str) -> SearchProfile | None:
        res = self.client.table("search_profiles").select("config").eq("id", profile_id).execute()
        if res.data:
            return SearchProfile.from_dict(res.data[0]["config"])
        return None

    def list_profiles(self, active_only: bool = True) -> list[SearchProfile]:
        query = self.client.table("search_profiles").select("config")
        if active_only:
            query = query.eq("active", True)
        res = query.execute()
        return [SearchProfile.from_dict(row["config"]) for row in res.data]

    def delete_profile(self, profile_id: str) -> bool:
        res = self.client.table("search_profiles").delete().eq("id", profile_id).execute()
        return len(res.data) > 0

    def mark_notified(self, source_id: str, profile_id: str, channel: str) -> None:
        try:
            self.client.table("notifications_log").insert(
                {
                    "apartment_id": source_id,
                    "profile_id": profile_id,
                    "channel": channel,
                }
            ).execute()
        except Exception:
            pass

    def was_notified(self, source_id: str, profile_id: str, channel: str) -> bool:
        res = (
            self.client.table("notifications_log")
            .select("id")
            .eq("apartment_id", source_id)
            .eq("profile_id", profile_id)
            .eq("channel", channel)
            .execute()
        )
        return len(res.data) > 0

    def update_analysis(
        self,
        source_id: str,
        summary: str | None,
        score: float | None,
        renovation: str | None,
        pros: list[str] | None,
        cons: list[str] | None,
    ) -> None:
        self.client.table("apartments").update(
            {
                "llm_summary": summary,
                "llm_score": score,
                "llm_renovation_quality": renovation,
                "llm_pros": pros,
                "llm_cons": cons,
            }
        ).eq("source_id", source_id).execute()

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_apartments": 0,
            "new_apartments": 0,
            "analyzed_apartments": 0,
            "active_profiles": 0,
            "avg_price": 0,
            "avg_score": None,
            "top_cities": {},
        }
