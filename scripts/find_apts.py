import asyncio
import os
import sys

# Ensure module is in path
sys.path.insert(0, os.path.abspath("src"))

from apartment_hunter.core.interfaces import VectorStore
from apartment_hunter.core.models import SearchProfile
from apartment_hunter.ingest.pipeline import IngestPipeline
from apartment_hunter.storage.factory import get_storage


class MockVectorStore(VectorStore):
    def upsert(self, apt): pass
    def semantic_search(self, query, n_results=10, where=None): return []
    def delete(self, source_id): pass

async def main():
    # Force use of SQLite for the script if no Postgres
    os.environ["STORAGE_BACKEND"] = "sqlite"

    from apartment_hunter.config import get_settings
    settings = get_settings()
    settings.max_pages_per_run = 1
    settings.scrape_delay_seconds = 0.5

    db = get_storage()
    vector = MockVectorStore()

    profile = SearchProfile(
        name="Almaty Bostandyk",
        city="Алматы",
        has_photo=False,
    )

    pipeline = IngestPipeline(db, vector, analyze=False)

    print("Running pipeline...")
    apts = await pipeline.run_profile(profile)

    print(f"\n--- Found {len(apts)} NEW apartments overall ---\n")

    bostandyk_apts = [a for a in apts if a.district and "бостандыкский" in a.district.lower()]

    print(f"Found {len(bostandyk_apts)} in Bostandyk district published today!")
    for apt in bostandyk_apts:
        print(apt.to_card())
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())
