"""PostgreSQL storage backend using psycopg 3."""

from __future__ import annotations

import importlib.util
import json
import logging
from datetime import UTC, datetime, timedelta
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
    photo_urls    JSONB DEFAULT '[]'::jsonb,
    owner_type    TEXT,
    created_at    TIMESTAMP WITH TIME ZONE,
    scraped_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    llm_summary   TEXT,
    llm_score     REAL,
    llm_renovation_quality TEXT,
    llm_pros      JSONB,
    llm_cons      JSONB,
    is_new        BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS price_history (
    id            SERIAL PRIMARY KEY,
    apartment_id  TEXT NOT NULL REFERENCES apartments(source_id) ON DELETE CASCADE,
    price         INTEGER NOT NULL,
    recorded_at   DATE DEFAULT CURRENT_DATE,
    UNIQUE(apartment_id, price, recorded_at)
);

CREATE TABLE IF NOT EXISTS search_profiles (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    config     JSONB NOT NULL,
    active     BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications_log (
    id           SERIAL PRIMARY KEY,
    apartment_id TEXT NOT NULL,
    profile_id   TEXT NOT NULL,
    channel      TEXT NOT NULL,
    sent_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(apartment_id, profile_id, channel)
);
"""


class PostgresStore(StorageBackend):
    """PostgreSQL-backed storage for apartments."""

    def __init__(self, dsn: str | None) -> None:
        if not dsn:
            raise ValueError("postgres_dsn must be set when using postgres backend")
        if importlib.util.find_spec("psycopg") is None:
            raise ImportError(
                "psycopg[binary] is required for PostgresStore. Run: pip install psycopg[binary]"
            )

        self.dsn = dsn
        self._init_db()

    def _conn(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(_SCHEMA)
            conn.commit()
        log.info("PostgreSQL database initialized.")

    def _row_to_apt(self, row: dict) -> Apartment:
        row["is_new"] = bool(row["is_new"])
        # psycopg usually decodes JSONB automatically; normalize only the bool flag here.
        return Apartment(**row)

    def upsert_apartment(self, apt: Apartment) -> bool:
        row = apt.to_dict()
        # Convert lists to JSON strings for JSONB if needed, or psycopg handles lists directly
        row["photo_urls"] = json.dumps(row["photo_urls"], ensure_ascii=False)
        row["llm_pros"] = (
            json.dumps(row["llm_pros"], ensure_ascii=False) if row["llm_pros"] else None
        )
        row["llm_cons"] = (
            json.dumps(row["llm_cons"], ensure_ascii=False) if row["llm_cons"] else None
        )
        if not self.get_apartment(apt.source_id):
            row["is_new"] = True
        else:
            row["is_new"] = False

        keys = list(row.keys())
        cols = ", ".join(keys)
        placeholders = ", ".join(f"%({k})s" for k in keys)
        updates = ", ".join(
            f"{k} = EXCLUDED.{k}"
            for k in keys
            if k
            not in (
                "source_id",
                "llm_summary",
                "llm_score",
                "llm_renovation_quality",
                "llm_pros",
                "llm_cons",
            )
        )

        query = f"""
            INSERT INTO apartments ({cols})
            VALUES ({placeholders})
            ON CONFLICT (source_id) DO UPDATE SET {updates}
            RETURNING (xmax = 0) AS is_inserted
        """
        with self._conn() as conn:
            result = conn.execute(query, row).fetchone()
            conn.commit()
            return result["is_inserted"] if result else False

    def update_analysis(
        self,
        source_id: str,
        summary: str | None,
        score: float | None,
        renovation: str | None,
        pros: list[str] | None,
        cons: list[str] | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE apartments SET
                   llm_summary = %s, llm_score = %s, llm_renovation_quality = %s,
                   llm_pros = %s, llm_cons = %s
                   WHERE source_id = %s""",
                (
                    summary,
                    score,
                    renovation,
                    json.dumps(pros, ensure_ascii=False) if pros else None,
                    json.dumps(cons, ensure_ascii=False) if cons else None,
                    source_id,
                ),
            )
            conn.commit()

    def get_apartment(self, source_id: str) -> Apartment | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM apartments WHERE source_id = %s", (source_id,)
            ).fetchone()
            return self._row_to_apt(row) if row else None

    def search_apartments(self, **filters: Any) -> list[Apartment]:
        clauses = []
        params = []
        for key, val in filters.items():
            if val is None:
                continue
            if key == "city":
                clauses.append("city ILIKE %s")
                params.append(f"%{val}%")
            elif key == "rooms":
                if isinstance(val, list):
                    clauses.append("rooms = ANY(%s)")
                    params.append(val)
                else:
                    clauses.append("rooms = %s")
                    params.append(val)
            elif key == "price_min":
                clauses.append("price >= %s")
                params.append(val)
            elif key == "price_max":
                clauses.append("price <= %s")
                params.append(val)
            elif key == "min_score":
                clauses.append("llm_score >= %s")
                params.append(val)
            elif key == "owner_only" and val:
                clauses.append("owner_type ILIKE '%собственник%'")

        where = " AND ".join(clauses) if clauses else "1=1"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM apartments WHERE {where} ORDER BY scraped_at DESC LIMIT 100",
                params,
            ).fetchall()
            return [self._row_to_apt(r) for r in rows]

    def get_new_apartments(self, since_hours: int = 24) -> list[Apartment]:
        cutoff = datetime.now(UTC) - timedelta(hours=since_hours)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM apartments WHERE scraped_at >= %s AND is_new = TRUE "
                "ORDER BY llm_score DESC NULLS LAST, scraped_at DESC LIMIT 50",
                (cutoff,),
            ).fetchall()
            return [self._row_to_apt(r) for r in rows]

    def record_price(self, source_id: str, price: int) -> None:
        with self._conn() as conn:
            conn.execute(
                (
                    "INSERT INTO price_history (apartment_id, price) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING"
                ),
                (source_id, price),
            )
            conn.commit()

    def get_price_history(self, source_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                (
                    "SELECT price, recorded_at FROM price_history "
                    "WHERE apartment_id = %s ORDER BY recorded_at"
                ),
                (source_id,),
            ).fetchall()
            return [{"price": r["price"], "date": str(r["recorded_at"])} for r in rows]

    def save_profile(self, profile: SearchProfile) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO search_profiles (id, name, config, active)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE
                   SET name = EXCLUDED.name,
                       config = EXCLUDED.config,
                       active = EXCLUDED.active""",
                (
                    profile.id,
                    profile.name,
                    json.dumps(profile.to_dict(), ensure_ascii=False),
                    profile.active,
                ),
            )
            conn.commit()

    def get_profile(self, profile_id: str) -> SearchProfile | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT config FROM search_profiles WHERE id = %s", (profile_id,)
            ).fetchone()
            if row:
                return SearchProfile.from_dict(
                    row["config"]
                    if isinstance(row["config"], dict)
                    else json.loads(row["config"])
                )
        return None

    def list_profiles(self, active_only: bool = True) -> list[SearchProfile]:
        with self._conn() as conn:
            q = "SELECT config FROM search_profiles"
            if active_only:
                q += " WHERE active = TRUE"
            rows = conn.execute(q).fetchall()
            return [
                SearchProfile.from_dict(
                    r["config"]
                    if isinstance(r["config"], dict)
                    else json.loads(r["config"])
                )
                for r in rows
            ]

    def delete_profile(self, profile_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM search_profiles WHERE id = %s", (profile_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_notified(self, source_id: str, profile_id: str, channel: str) -> None:
        with self._conn() as conn:
            conn.execute(
                (
                    "INSERT INTO notifications_log "
                    "(apartment_id, profile_id, channel) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"
                ),
                (source_id, profile_id, channel),
            )
            conn.commit()

    def was_notified(self, source_id: str, profile_id: str, channel: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                (
                    "SELECT 1 FROM notifications_log "
                    "WHERE apartment_id = %s AND profile_id = %s AND channel = %s"
                ),
                (source_id, profile_id, channel),
            ).fetchone()
            return row is not None

    def get_stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM apartments").fetchone()["c"]
            new = conn.execute(
                "SELECT COUNT(*) as c FROM apartments WHERE is_new = TRUE"
            ).fetchone()["c"]
            analyzed = conn.execute(
                "SELECT COUNT(*) as c FROM apartments WHERE llm_score IS NOT NULL"
            ).fetchone()["c"]
            avg_price = conn.execute(
                "SELECT AVG(price) as a FROM apartments WHERE price > 0"
            ).fetchone()["a"]
            avg_score = conn.execute(
                "SELECT AVG(llm_score) as a FROM apartments WHERE llm_score IS NOT NULL"
            ).fetchone()["a"]
            return {
                "total_apartments": total,
                "new_apartments": new,
                "analyzed_apartments": analyzed,
                "avg_price": int(avg_price) if avg_price else 0,
                "avg_score": round(avg_score, 1) if avg_score else None,
                "top_cities": {},
            }
