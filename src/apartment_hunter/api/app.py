"""FastAPI standalone server for Apartment Hunter.

Run with:
    python -m apartment_hunter.api.app
"""

from __future__ import annotations

import logging
from typing import Any

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from pydantic import BaseModel

from apartment_hunter.analysis.llm_analyzer import LLMAnalyzer
from apartment_hunter.config import get_settings
from apartment_hunter.core.models import SearchProfile
from apartment_hunter.ingest.pipeline import IngestPipeline
from apartment_hunter.notifications.telegram import TelegramNotifier
from apartment_hunter.storage.factory import get_storage, get_vector_store

log = logging.getLogger(__name__)

# ── Dependencies ──────────────────────────────────────────────────────────────

_settings = get_settings()
_db = get_storage()
_vector = get_vector_store()
_analyzer = LLMAnalyzer()


def _get_pipeline() -> IngestPipeline:
    notifiers = []
    if _settings.telegram_bot_token:
        notifiers.append(TelegramNotifier())
    return IngestPipeline(db=_db, vector=_vector, notifiers=notifiers)


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Apartment Hunter API",
    description="REST API for apartment search, tracking, and analysis.",
    version="0.1.0",
)

# ── Schemas ───────────────────────────────────────────────────────────────────


class SemanticSearchRequest(BaseModel):
    query: str
    n_results: int = 10
    city: str | None = None
    price_max: int | None = None
    rooms: int | None = None


class ProfileCreateRequest(BaseModel):
    name: str
    city: str | None = None
    districts: list[str] | None = None
    rooms: list[int] | None = None
    price_min: int | None = None
    price_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    owner_only: bool = False
    has_photo: bool = True
    bounding_box: list[float] | None = None
    furniture: bool | None = None
    keywords: list[str] | None = None
    min_score: float | None = None


class IngestResponse(BaseModel):
    message: str
    results: dict[str, int]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok", "service": "Apartment Hunter API"}


@app.get("/stats")
def get_stats() -> dict[str, Any]:
    stats = _db.get_stats()
    stats["vector_documents"] = _vector.count
    return stats


@app.get("/apartments")
def search_apartments(
    city: str | None = Query(None),
    rooms: list[int] | None = Query(None),
    price_min: int | None = Query(None),
    price_max: int | None = Query(None),
    min_score: float | None = Query(None),
    district: str | None = Query(None),
):
    filters = {
        "city": city,
        "rooms": rooms,
        "price_min": price_min,
        "price_max": price_max,
        "min_score": min_score,
        "district": district,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}

    results = _db.search_apartments(**filters)
    return [a.to_dict() for a in results]


@app.get("/apartments/new")
def get_new_apartments(since_hours: int = 24):
    results = _db.get_new_apartments(since_hours)
    return [a.to_dict() for a in results]


@app.get("/apartments/top")
def get_top_apartments(limit: int = 10, city: str | None = Query(None)):
    filters = {"city": city} if city else {}
    results = _db.get_top_apartments(limit=limit, **filters)
    return [a.to_dict() for a in results]


@app.get("/apartments/{source_id}")
def get_apartment(source_id: str):
    apt = _db.get_apartment(source_id)
    if not apt:
        raise HTTPException(status_code=404, detail="Apartment not found")
    data = apt.to_dict()
    data["price_history"] = _db.get_price_history(source_id)
    return data


@app.post("/apartments/{source_id}/analyze")
async def analyze_apartment(source_id: str):
    apt = _db.get_apartment(source_id)
    if not apt:
        raise HTTPException(status_code=404, detail="Apartment not found")

    result = await _analyzer.analyze(apt)

    _db.update_analysis(
        source_id,
        result.summary,
        result.score,
        result.renovation_quality,
        result.pros,
        result.cons,
    )
    return {"status": "success", "score": result.score, "summary": result.summary}


@app.post("/search/semantic")
def semantic_search(req: SemanticSearchRequest):
    where = None
    conditions = []
    if req.city:
        conditions.append({"city": {"$eq": req.city}})
    if req.price_max:
        conditions.append({"price": {"$lte": req.price_max}})
    if req.rooms:
        conditions.append({"rooms": {"$eq": req.rooms}})

    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    source_ids = _vector.semantic_search(
        req.query, n_results=req.n_results, where=where
    )
    apartments = [_db.get_apartment(sid) for sid in source_ids]
    return [a.to_dict() for a in apartments if a]


@app.get("/profiles")
def list_profiles():
    profiles = _db.list_profiles()
    return [p.to_dict() for p in profiles]


@app.post("/profiles")
async def create_profile(req: ProfileCreateRequest):
    profile = SearchProfile(
        name=req.name,
        city=req.city,
        districts=req.districts,
        rooms=req.rooms,
        price_min=req.price_min,
        price_max=req.price_max,
        area_min=req.area_min,
        area_max=req.area_max,
        owner_only=req.owner_only,
        has_photo=req.has_photo,
        bounding_box=req.bounding_box,
        furniture=req.furniture,
        keywords=req.keywords,
        min_score=req.min_score,
    )
    _db.save_profile(profile)
    return profile.to_dict()


@app.delete("/profiles/{profile_id}")
def delete_profile(profile_id: str):
    if _db.delete_profile(profile_id):
        return {"status": "success", "message": f"Profile {profile_id} deleted"}
    raise HTTPException(status_code=404, detail="Profile not found")


@app.post("/ingest/run", response_model=IngestResponse)
async def run_ingestion(
    background_tasks: BackgroundTasks, profile_id: str | None = Query(None)
):
    """Run ingestion either synchronously or in background."""
    pipeline = _get_pipeline()

    if profile_id:
        profile = _db.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        new = await pipeline.run_profile(profile)
        return IngestResponse(
            message=f"Ingestion completed for profile {profile.name}",
            results={profile.name: len(new)},
        )
    else:
        results = await pipeline.run_all_profiles()
        return IngestResponse(
            message="Ingestion completed for all active profiles", results=results
        )


# ── Entry Point ───────────────────────────────────────────────────────────────


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    uvicorn.run(
        "apartment_hunter.api.app:app",
        host=_settings.api_host,
        port=_settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    main()
