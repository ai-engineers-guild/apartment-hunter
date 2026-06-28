"""Abstract interfaces that adapters, storage backends, and notifiers implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from apartment_hunter.core.models import AnalysisResult, Apartment, SearchProfile


class SourceAdapter(ABC):
    """Pluggable data source (krisha.kz, olx, threads, etc.)."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique name for this source, e.g. 'krisha.kz'."""

    @abstractmethod
    async def fetch_listings(
        self, profile: SearchProfile, *, max_pages: int = 5
    ) -> list[Apartment]:
        """Fetch apartment listings matching the given profile."""

    @abstractmethod
    async def get_details(self, source_id: str) -> Apartment | None:
        """Fetch full details for a single apartment by its source-specific ID."""


class StorageBackend(ABC):
    """Persistent storage for apartments and profiles."""

    @abstractmethod
    def upsert_apartment(self, apt: Apartment) -> bool:
        """Insert or update. Returns True if this is a newly inserted apartment."""

    @abstractmethod
    def get_apartment(self, source_id: str) -> Apartment | None: ...

    @abstractmethod
    def search_apartments(self, **filters: Any) -> list[Apartment]: ...

    @abstractmethod
    def get_new_apartments(self, since_hours: int = 24) -> list[Apartment]: ...

    @abstractmethod
    def record_price(self, source_id: str, price: int) -> None: ...

    @abstractmethod
    def get_price_history(self, source_id: str) -> list[dict]: ...

    @abstractmethod
    def save_profile(self, profile: SearchProfile) -> None: ...

    @abstractmethod
    def get_profile(self, profile_id: str) -> SearchProfile | None: ...

    @abstractmethod
    def list_profiles(self, active_only: bool = True) -> list[SearchProfile]: ...

    @abstractmethod
    def delete_profile(self, profile_id: str) -> bool: ...

    @abstractmethod
    def mark_notified(self, source_id: str, profile_id: str, channel: str) -> None: ...

    @abstractmethod
    def was_notified(self, source_id: str, profile_id: str, channel: str) -> bool: ...

    @abstractmethod
    def get_stats(self) -> dict[str, Any]: ...


class VectorStore(ABC):
    """Vector database for semantic search."""

    @abstractmethod
    def upsert(self, apt: Apartment) -> None: ...

    @abstractmethod
    def semantic_search(
        self,
        query: str,
        n_results: int = 10,
        where: dict | None = None,
    ) -> list[str]:
        """Returns list of source_ids ordered by relevance."""

    @abstractmethod
    def delete(self, source_id: str) -> None: ...


class Notifier(ABC):
    """Notification channel (Telegram, webhook, etc.)."""

    @property
    @abstractmethod
    def channel_name(self) -> str: ...

    @abstractmethod
    async def notify(self, apartment: Apartment, profile: SearchProfile) -> bool:
        """Send notification. Returns True on success."""


class Analyzer(ABC):
    """LLM-powered apartment analysis."""

    @abstractmethod
    async def analyze(self, apartment: Apartment) -> AnalysisResult: ...
