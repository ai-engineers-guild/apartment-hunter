"""Centralized configuration via pydantic-settings.

All settings can be overridden via environment variables or a `.env` file.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings – loaded from env / .env automatically."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Backends ───────────────────────────────────────────────────────
    storage_backend: str = "sqlite"  # "sqlite" | "postgres" | "supabase" | "firebase" | "file"
    vector_backend: str = "chroma"  # "chroma" | "qdrant"

    # ── Paths & Local DBs ──────────────────────────────────────────────
    db_path: str = str(_PROJECT_ROOT / "data" / "apartments.db")
    chroma_path: str = str(_PROJECT_ROOT / "data" / "chroma")
    json_path: str = str(_PROJECT_ROOT / "data" / "apartments.json")

    # ── External DB Connections ────────────────────────────────────────
    postgres_dsn: str | None = None
    supabase_url: str | None = None
    supabase_key: str | None = None
    firebase_cred_path: str | None = None
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None

    # ── LLM ────────────────────────────────────────────────────────────
    llm_provider: str = "openai"  # "openai" | "anthropic" | "gemini" | "openrouter"
    llm_model: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None

    # ── Embeddings ─────────────────────────────────────────────────────
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # ── Scraping ───────────────────────────────────────────────────────
    scrape_interval_minutes: int = 30
    scrape_delay_seconds: float = 2.0
    scrape_timeout: int = 20
    max_pages_per_run: int = 5  # limit pages per ingestion run

    # ── Telegram ───────────────────────────────────────────────────────
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # ── Server ─────────────────────────────────────────────────────────
    mcp_transport: str = "stdio"  # "stdio" | "http"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Derived helpers ────────────────────────────────────────────────
    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.chroma_path, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor for settings."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
