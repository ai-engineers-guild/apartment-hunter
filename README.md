# Apartment Hunter

Apartment Hunter is a reusable apartment-search library and MCP service for rental
search workflows. The core library is source-agnostic; site-specific behavior lives
in adapters such as `krisha.kz`.

## What it does

- Ingests apartment listings from source adapters
- Normalizes them into a shared `Apartment` domain model
- Stores listings, profiles, notifications, and price history
- Runs semantic search and optional LLM analysis
- Exposes the workflow through an MCP server for Codex Desktop or other MCP clients

## Architecture

`src/apartment_hunter/core`
- Canonical models and abstract interfaces

`src/apartment_hunter/adapters`
- Source-specific adapters and parsers

`src/apartment_hunter/ingest`
- Fetch, deduplicate, analyze, index, notify

`src/apartment_hunter/storage`
- Storage backends and vector stores

`src/apartment_hunter/mcp`
- MCP tools for search, ingestion, monitoring, and analysis

`src/krisha`
- Legacy project code preserved separately from the reusable library

## Local commands

```powershell
uv run pytest
uv run pytest --cov
uv run ruff check .
uv run apartment-hunter-mcp
uv run apartment-hunter-ingest
```

## Codex Desktop integration

Apartment Hunter is designed to work as a Codex Desktop MCP service.

Typical workflow:

1. Start the MCP server with `uv run apartment-hunter-mcp`
2. Create or update search profiles through MCP tools
3. Run ingestion for the current profile set
4. Ask for:
   new apartments,
   changed prices,
   top-rated apartments,
   semantic matches,
   apartment comparisons

The project also includes local skills in `.agents/skills`:

- `apartment_search`
  Domain workflow for apartment search, ingestion, monitoring, and translating
  listing jargon into agent-friendly meaning.
- `city-district-context-kz`
  City and district context research for Kazakhstan: district quality, transport,
  pricing, livability, construction, and neighborhood tradeoffs.

## Design rules

- Core remains source-agnostic
- Source-specific logic belongs in adapters
- MCP should compose the core library rather than embed scraper-specific logic
- `is_new` means first discovery, not "seen again in the latest run"
- The current-ingest delta should come from pipeline results, not from naive DB scans

## Current source support

- `krisha.kz` via `src/apartment_hunter/adapters/krisha`

The codebase is intentionally structured so additional sources can be added by
implementing `SourceAdapter` and registering the adapter.

## License

[MIT](LICENSE)
