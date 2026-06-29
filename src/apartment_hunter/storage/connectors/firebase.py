"""Firebase Firestore storage backend."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from apartment_hunter.core.interfaces import StorageBackend
from apartment_hunter.core.models import Apartment, SearchProfile

log = logging.getLogger(__name__)


class FirebaseStore(StorageBackend):
    """Firebase Firestore-backed storage."""

    def __init__(self, cred_path: str | None) -> None:
        if not cred_path:
            raise ValueError("firebase_cred_path must be set when using firebase backend")
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
        except ImportError:
            raise ImportError("firebase-admin is required. Run: pip install firebase-admin")

        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()
        log.info("Firebase Firestore initialized.")

    def upsert_apartment(self, apt: Apartment) -> bool:
        doc_ref = self.db.collection("apartments").document(apt.source_id)
        doc = doc_ref.get()
        is_new = not doc.exists

        data = apt.to_dict()
        # Convert datetimes to strings for JSON-like storage
        if data.get("created_at"):
            data["created_at"] = data["created_at"].isoformat()
        if data.get("scraped_at"):
            data["scraped_at"] = data["scraped_at"].isoformat()

        if is_new:
            doc_ref.set(data)
        else:
            # Keep LLM fields
            updates = {k: v for k, v in data.items() if not k.startswith("llm_")}
            doc_ref.update(updates)

        return is_new

    def get_apartment(self, source_id: str) -> Apartment | None:
        doc = self.db.collection("apartments").document(source_id).get()
        if doc.exists:
            d = doc.to_dict()
            if d and d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d and d.get("scraped_at"):
                d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
            return Apartment(**d)
        return None

    def update_analysis(
        self,
        source_id: str,
        summary: str | None,
        score: float | None,
        renovation: str | None,
        pros: list[str] | None,
        cons: list[str] | None,
    ) -> None:
        self.db.collection("apartments").document(source_id).update(
            {
                "llm_summary": summary,
                "llm_score": score,
                "llm_renovation_quality": renovation,
                "llm_pros": pros,
                "llm_cons": cons,
            }
        )

    def search_apartments(self, **filters: Any) -> list[Apartment]:
        # Firestore composite queries are limited, we'll do basic filtering and then in-memory
        query = self.db.collection("apartments")
        if filters.get("city"):
            query = query.where("city", "==", filters["city"])

        docs = query.stream()
        results = []
        for doc in docs:
            d = doc.to_dict()
            if d and d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d and d.get("scraped_at"):
                d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
            results.append(Apartment(**d))

        # Apply rest of filters in memory due to Firestore limits
        filtered = []
        for d in results:
            match = True
            if filters.get("rooms"):
                match = d.rooms in (filters["rooms"] if isinstance(filters["rooms"], list) else [filters["rooms"]])
            if match and filters.get("price_max") and d.price > filters["price_max"]:
                match = False
            if match and filters.get("min_score") and (d.llm_score or 0) < filters["min_score"]:
                match = False
            if match:
                filtered.append(d)

        filtered.sort(key=lambda a: a.scraped_at, reverse=True)
        return filtered[:100]

    def get_new_apartments(self, since_hours: int = 24) -> list[Apartment]:
        cutoff = (datetime.utcnow() - timedelta(hours=since_hours)).isoformat()
        docs = self.db.collection("apartments").where("scraped_at", ">=", cutoff).where("is_new", "==", True).stream()
        results = []
        for doc in docs:
            d = doc.to_dict()
            if d and d.get("created_at"):
                d["created_at"] = datetime.fromisoformat(d["created_at"])
            if d and d.get("scraped_at"):
                d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
            results.append(Apartment(**d))
        results.sort(key=lambda a: a.llm_score or 0, reverse=True)
        return results[:50]

    def record_price(self, source_id: str, price: int) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        doc_id = f"{source_id}_{today}_{price}"
        self.db.collection("price_history").document(doc_id).set(
            {"apartment_id": source_id, "price": price, "recorded_at": today}
        )

    def get_price_history(self, source_id: str) -> list[dict]:
        docs = self.db.collection("price_history").where("apartment_id", "==", source_id).stream()
        history = [{"price": d.to_dict()["price"], "date": d.to_dict()["recorded_at"]} for d in docs]
        history.sort(key=lambda x: x["date"])
        return history

    def save_profile(self, profile: SearchProfile) -> None:
        self.db.collection("search_profiles").document(profile.id).set(profile.to_dict())

    def get_profile(self, profile_id: str) -> SearchProfile | None:
        doc = self.db.collection("search_profiles").document(profile_id).get()
        return SearchProfile.from_dict(doc.to_dict()) if doc.exists else None

    def list_profiles(self, active_only: bool = True) -> list[SearchProfile]:
        query = self.db.collection("search_profiles")
        if active_only:
            query = query.where("active", "==", True)
        docs = query.stream()
        return [SearchProfile.from_dict(d.to_dict()) for d in docs]

    def delete_profile(self, profile_id: str) -> bool:
        self.db.collection("search_profiles").document(profile_id).delete()
        return True

    def mark_notified(self, source_id: str, profile_id: str, channel: str) -> None:
        key = f"{source_id}_{profile_id}_{channel}"
        self.db.collection("notifications_log").document(key).set({"sent_at": datetime.utcnow().isoformat()})

    def was_notified(self, source_id: str, profile_id: str, channel: str) -> bool:
        key = f"{source_id}_{profile_id}_{channel}"
        return self.db.collection("notifications_log").document(key).get().exists

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
