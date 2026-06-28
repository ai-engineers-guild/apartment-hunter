"""SQLite storage backend with full-text search."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from apartment_hunter.core.interfaces import StorageBackend
from apartment_hunter.core.models import Apartment, SearchProfile

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS apartments (
    source_id     TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    price         INTEGER NOT NULL,
    currency      TEXT DEFAULT 'KZT',
    rooms         INTEGER,
    area_total    REAL,
    area_living   REAL,
    area_kitchen  REAL,
    floor         INTEGER,
    floor_total   INTEGER,
    building_type TEXT,
    year_built    INTEGER,
    condition     TEXT,
    furniture     TEXT,
    address       TEXT,
    city          TEXT,
    district      TEXT,
    lat           REAL,
    lon           REAL,
    description   TEXT,
    photo_urls    TEXT,
    owner_type    TEXT,
    created_at    TEXT,
    scraped_at    TEXT NOT NULL,
    llm_summary   TEXT,
    llm_score     REAL,
    llm_renovation_quality TEXT,
    llm_pros      TEXT,
    llm_cons      TEXT,
    is_new        INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    apartment_id  TEXT NOT NULL REFERENCES apartments(source_id),
    price         INTEGER NOT NULL,
    recorded_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(apartment_id, price, recorded_at)
);

CREATE TABLE IF NOT EXISTS search_profiles (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    config     TEXT NOT NULL,
    active     INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    apartment_id TEXT NOT NULL,
    profile_id   TEXT NOT NULL,
    channel      TEXT NOT NULL,
    sent_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(apartment_id, profile_id, channel)
);
"""


class SQLiteStore(StorageBackend):
    """SQLite-backed storage with extended apartment schema."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
        log.info("SQLite database initialized at %s", self._db_path)

    # ── Apartments ────────────────────────────────────────────────────

    def _apt_to_row(self, apt: Apartment) -> dict:
        return {
            "source_id": apt.source_id,
            "source": apt.source,
            "url": apt.url,
            "title": apt.title,
            "price": apt.price,
            "currency": apt.currency,
            "rooms": apt.rooms,
            "area_total": apt.area_total,
            "area_living": apt.area_living,
            "area_kitchen": apt.area_kitchen,
            "floor": apt.floor,
            "floor_total": apt.floor_total,
            "building_type": apt.building_type,
            "year_built": apt.year_built,
            "condition": apt.condition,
            "furniture": apt.furniture,
            "address": apt.address,
            "city": apt.city,
            "district": apt.district,
            "lat": apt.lat,
            "lon": apt.lon,
            "description": apt.description,
            "photo_urls": json.dumps(apt.photo_urls, ensure_ascii=False),
            "owner_type": apt.owner_type,
            "created_at": apt.created_at.isoformat() if apt.created_at else None,
            "scraped_at": apt.scraped_at.isoformat(),
            "llm_summary": apt.llm_summary,
            "llm_score": apt.llm_score,
            "llm_renovation_quality": apt.llm_renovation_quality,
            "llm_pros": (
                json.dumps(apt.llm_pros, ensure_ascii=False) if apt.llm_pros else None
            ),
            "llm_cons": (
                json.dumps(apt.llm_cons, ensure_ascii=False) if apt.llm_cons else None
            ),
            "is_new": 1 if apt.is_new else 0,
        }

    def _row_to_apt(self, row: sqlite3.Row) -> Apartment:
        d = dict(row)
        d["photo_urls"] = json.loads(d["photo_urls"]) if d["photo_urls"] else []
        d["llm_pros"] = json.loads(d["llm_pros"]) if d["llm_pros"] else None
        d["llm_cons"] = json.loads(d["llm_cons"]) if d["llm_cons"] else None
        d["is_new"] = bool(d["is_new"])
        for key in ("created_at", "scraped_at"):
            if d.get(key) and isinstance(d[key], str):
                try:
                    d[key] = datetime.fromisoformat(d[key])
                except ValueError:
                    d[key] = None
        return Apartment(**d)

    def upsert_apartment(self, apt: Apartment) -> bool:
        row = self._apt_to_row(apt)
        cols = ", ".join(row.keys())
        placeholders = ", ".join(f":{k}" for k in row.keys())
        # Check if already exists
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT source_id FROM apartments WHERE source_id = ?",
                (apt.source_id,),
            ).fetchone()
            if existing:
                # Update non-LLM fields only (preserve analysis)
                update_fields = [
                    k
                    for k in row.keys()
                    if k
                    not in (
                        "source_id",
                        "llm_summary",
                        "llm_score",
                        "llm_renovation_quality",
                        "llm_pros",
                        "llm_cons",
                    )
                ]
                set_clause = ", ".join(f"{k} = :{k}" for k in update_fields)
                conn.execute(
                    f"UPDATE apartments SET {set_clause} WHERE source_id = :source_id",
                    row,
                )
                return False
            else:
                conn.execute(
                    f"INSERT INTO apartments ({cols}) VALUES ({placeholders})",
                    row,
                )
                return True

    def update_analysis(
        self,
        source_id: str,
        llm_summary: str | None,
        llm_score: float | None,
        llm_renovation_quality: str | None,
        llm_pros: list[str] | None,
        llm_cons: list[str] | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE apartments SET
                   llm_summary = ?, llm_score = ?, llm_renovation_quality = ?,
                   llm_pros = ?, llm_cons = ?
                   WHERE source_id = ?""",
                (
                    llm_summary,
                    llm_score,
                    llm_renovation_quality,
                    json.dumps(llm_pros, ensure_ascii=False) if llm_pros else None,
                    json.dumps(llm_cons, ensure_ascii=False) if llm_cons else None,
                    source_id,
                ),
            )

    def get_apartment(self, source_id: str) -> Apartment | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM apartments WHERE source_id = ?", (source_id,)
            ).fetchone()
            return self._row_to_apt(row) if row else None

    def search_apartments(self, **filters: Any) -> list[Apartment]:
        clauses: list[str] = []
        params: list[Any] = []
        for key, val in filters.items():
            if val is None:
                continue
            if key == "city":
                clauses.append("city LIKE ?")
                params.append(f"%{val}%")
            elif key == "rooms":
                if isinstance(val, list):
                    placeholders = ",".join("?" * len(val))
                    clauses.append(f"rooms IN ({placeholders})")
                    params.extend(val)
                else:
                    clauses.append("rooms = ?")
                    params.append(val)
            elif key == "price_min":
                clauses.append("price >= ?")
                params.append(val)
            elif key == "price_max":
                clauses.append("price <= ?")
                params.append(val)
            elif key == "area_min":
                clauses.append("area_total >= ?")
                params.append(val)
            elif key == "area_max":
                clauses.append("area_total <= ?")
                params.append(val)
            elif key == "min_score":
                clauses.append("llm_score >= ?")
                params.append(val)
            elif key == "district":
                clauses.append("district LIKE ?")
                params.append(f"%{val}%")
            elif key == "owner_only" and val:
                clauses.append("owner_type LIKE '%собственник%'")

        where = " AND ".join(clauses) if clauses else "1=1"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM apartments WHERE {where} ORDER BY scraped_at DESC LIMIT 100",
                params,
            ).fetchall()
            return [self._row_to_apt(r) for r in rows]

    def get_new_apartments(self, since_hours: int = 24) -> list[Apartment]:
        cutoff = (datetime.utcnow() - timedelta(hours=since_hours)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM apartments WHERE scraped_at >= ? AND is_new = 1 "
                "ORDER BY llm_score DESC NULLS LAST, scraped_at DESC LIMIT 50",
                (cutoff,),
            ).fetchall()
            return [self._row_to_apt(r) for r in rows]

    def get_top_apartments(self, limit: int = 10, **filters: Any) -> list[Apartment]:
        base = self.search_apartments(**filters)
        scored = [a for a in base if a.llm_score is not None]
        scored.sort(key=lambda a: a.llm_score or 0, reverse=True)
        return scored[:limit]

    # ── Price History ─────────────────────────────────────────────────

    def record_price(self, source_id: str, price: int) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO price_history (apartment_id, price, recorded_at) "
                "VALUES (?, ?, ?)",
                (source_id, price, today),
            )

    def get_price_history(self, source_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT price, recorded_at FROM price_history "
                "WHERE apartment_id = ? ORDER BY recorded_at",
                (source_id,),
            ).fetchall()
            return [{"price": r["price"], "date": r["recorded_at"]} for r in rows]

    # ── Search Profiles ───────────────────────────────────────────────

    def save_profile(self, profile: SearchProfile) -> None:
        config_json = json.dumps(profile.to_dict(), ensure_ascii=False)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO search_profiles (id, name, config, active) "
                "VALUES (?, ?, ?, ?)",
                (profile.id, profile.name, config_json, 1 if profile.active else 0),
            )

    def get_profile(self, profile_id: str) -> SearchProfile | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT config FROM search_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if row:
                return SearchProfile.from_dict(json.loads(row["config"]))
        return None

    def list_profiles(self, active_only: bool = True) -> list[SearchProfile]:
        with self._conn() as conn:
            q = "SELECT config FROM search_profiles"
            if active_only:
                q += " WHERE active = 1"
            rows = conn.execute(q).fetchall()
            return [SearchProfile.from_dict(json.loads(r["config"])) for r in rows]

    def delete_profile(self, profile_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM search_profiles WHERE id = ?", (profile_id,)
            )
            return cursor.rowcount > 0

    # ── Notifications ─────────────────────────────────────────────────

    def mark_notified(self, source_id: str, profile_id: str, channel: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO notifications_log "
                "(apartment_id, profile_id, channel) VALUES (?, ?, ?)",
                (source_id, profile_id, channel),
            )

    def was_notified(self, source_id: str, profile_id: str, channel: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM notifications_log "
                "WHERE apartment_id = ? AND profile_id = ? AND channel = ?",
                (source_id, profile_id, channel),
            ).fetchone()
            return row is not None

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM apartments").fetchone()["c"]
            new = conn.execute(
                "SELECT COUNT(*) c FROM apartments WHERE is_new = 1"
            ).fetchone()["c"]
            analyzed = conn.execute(
                "SELECT COUNT(*) c FROM apartments WHERE llm_score IS NOT NULL"
            ).fetchone()["c"]
            avg_price = conn.execute(
                "SELECT AVG(price) a FROM apartments WHERE price > 0"
            ).fetchone()["a"]
            avg_score = conn.execute(
                "SELECT AVG(llm_score) a FROM apartments WHERE llm_score IS NOT NULL"
            ).fetchone()["a"]
            profiles = conn.execute(
                "SELECT COUNT(*) c FROM search_profiles WHERE active = 1"
            ).fetchone()["c"]
            cities = conn.execute(
                "SELECT city, COUNT(*) c FROM apartments GROUP BY city ORDER BY c DESC LIMIT 5"
            ).fetchall()
        return {
            "total_apartments": total,
            "new_apartments": new,
            "analyzed_apartments": analyzed,
            "active_profiles": profiles,
            "avg_price": round(avg_price) if avg_price else 0,
            "avg_score": round(avg_score, 1) if avg_score else None,
            "top_cities": {r["city"]: r["c"] for r in cities if r["city"]},
        }
