---
name: apartment-search
description: >
  Search and analyze rental apartments in Kazakhstan via the Apartment Hunter MCP server.
  Supports structured filtering, semantic/vector search, LLM-powered scoring and analysis,
  price tracking, photo quality assessment, and Telegram notifications.
  Data sources: krisha.kz (primary), extensible to other platforms.
---

# Apartment Search Skill

## Overview
You have access to the **Apartment Hunter** MCP server which provides tools for searching,
analyzing, and monitoring rental apartments in Kazakhstan. The primary data source is **krisha.kz**.

## Workflow

### 1. Setting Up Search Profiles
Before searching, the user should create a **search profile** that defines their criteria:
```
Use create_search_profile with parameters like:
- city: "Алматы" or "Астана"
- rooms: [1, 2] for 1-2 room apartments
- price_min / price_max: in KZT (tenge)
- area_min / area_max: in m²
- owner_only: true to exclude agencies
- min_score: minimum LLM quality score (0-10)
- bounding_box: [lat_min, lon_min, lat_max, lon_max] if the user asks for a specific custom area (e.g. "Золотой квадрат", "рядом с Абая-Правды"). AS AN AI, YOU MUST GENERATE THESE COORDINATES YOURSELF based on your geographical knowledge of Kazakhstan and pass them to the tool.
```

### 2. Running Data Collection
Use `run_ingestion` to fetch new apartments from krisha.kz based on active profiles.
This scrapes listing pages, extracts full apartment details, generates embeddings
for semantic search, and runs LLM analysis.

### 3. Searching Apartments

**Structured search** — use `search_apartments` with specific filters:
- city, rooms, price range, area range, district, minimum score

**Semantic search** — use `semantic_search` with natural language:
- "уютная квартира с евроремонтом рядом с метро"
- "большая квартира для семьи с детьми в тихом районе"

### 4. Analyzing Apartments
- `analyze_apartment` — runs LLM analysis on a specific apartment
- `compare_apartments` — side-by-side comparison of 2-5 apartments
- `get_apartment_details` — full info including price history and photos

### 5. Monitoring
- `get_new_apartments` — see what's new in the last 24 hours
- `get_top_apartments` — highest-rated apartments
- `get_stats` — database overview

## Key Notes
- All prices are in **KZT (Kazakhstan Tenge)**
- The `source_id` format is `krisha:XXXXXXX` (e.g., `krisha:1013405508`)
- LLM scores range from **0.0 to 10.0** (higher is better)
- Semantic search works best with Russian-language queries
- Ingestion takes time (~2-5 minutes per page of 20 apartments)
