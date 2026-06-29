---
name: apartment-search
description: >
  Search and analyze rental apartments in Kazakhstan via the Apartment Hunter MCP server.
  Supports structured filtering, semantic/vector search, LLM-powered scoring and analysis,
  price tracking, photo quality assessment, run-to-run monitoring, and domain jargon
  translation for real-estate listings. Data sources: krisha.kz (primary),
  extensible to other platforms.
---

# Apartment Search Skill

## Overview
You have access to the **Apartment Hunter** MCP server which provides tools for searching,
analyzing, and monitoring rental apartments in Kazakhstan. The primary data source is
**krisha.kz**, but the library is designed for additional sources too.

## When to use

Use this skill when the user:

- wants apartments found by natural-language preferences;
- asks what changed since the latest ingestion run;
- describes listing jargon in plain language;
- needs help turning fuzzy preferences into profile filters;
- asks whether a listing phrase is good, bad, neutral, or ambiguous.

## Workflow

### 1. Setting Up Search Profiles
Before searching, the user should create a **search profile** that defines their criteria:
```
Use create_search_profile with parameters like:
- sources: ["krisha.kz"] unless the user requests another enabled source
- city: "Алматы" or "Астана"
- districts: ["Бостандыкский"] if the user clearly names districts
- rooms: [1, 2] for 1-2 room apartments
- price_min / price_max: in KZT (tenge)
- area_min / area_max: in m²
- owner_only: true to exclude agencies
- min_score: minimum LLM quality score (0-10)
- polygons: list of polygons, where each polygon is a list of [lat, lon] points.
### CRITICAL RULE FOR KRISHA.KZ: Always Use Polygons for Location-Based Search
Text search on krisha.kz for specific streets or landmarks is highly inaccurate and returns false positives from other districts.
When a user asks for a specific street (e.g. "Makataeva") or landmark (e.g. "Megapark"):
1. First, find the coordinates using a web search or maps tool.
2. Draw a closed polygon around the target area. A polygon is a list of `[lat, lon]` points forming a closed loop (first point must equal last point, or the system closes it automatically).
3. Pass `polygons` to `create_search_profile`. The polygon is sent directly to krisha.kz as a server-side geographic filter (`areas=p...`), so only listings physically located inside the polygon are returned.
   - Do NOT rely on `keywords` for geographic filtering — krisha.kz text search returns false positives from apartments that merely mention the street/landmark in their description ("10 minutes from Megapark", etc.).
   - `keywords` are only appropriate when the user explicitly wants to filter by text in the listing description (e.g., specific amenities or building name).
```

### 2. Running Data Collection
Use `run_ingestion` to fetch new apartments from krisha.kz based on active profiles.
This scrapes listing pages, extracts full apartment details, generates embeddings
for semantic search, and runs LLM analysis.

When the user asks "what is new" or "what changed from the last run", prefer:

1. run `run_ingestion` for the relevant profile;
2. use the returned current-run delta as the authoritative answer;
3. optionally enrich with `get_price_history` or `get_apartment_details`.

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
- `download_apartment_photos` — downloads photos locally so you (the AI) can use `view_file` to "look" at the interior visually and answer specific visual questions (e.g. "what color are the walls?", "does it look like a grandma's repair?").

### 5. Monitoring
- `get_new_apartments` — see what's new in the last 24 hours
- `get_top_apartments` — highest-rated apartments
- `get_stats` — database overview

### 6. Natural Language (Prompt) Profiles
- Use `nl_description` when creating profile for semantic preferences
- Use `search_by_profile(profile_id, hours=48)` to get ranked new apartments
- Explain that hard filters run first, then semantic re-ranking
- Give example: "новый ремонт не бабушкин, светлая, вся техника, тихий двор"
- Note: nl_description is NOT passed to Krisha URL — it's purely for post-ranking

## Domain translation rules

Translate listing jargon into agent-friendly meaning before deciding whether it is positive.
Do not treat marketing phrases as facts.

Read [references/domain-glossary-kz.md](references/domain-glossary-kz.md) when the user:

- mentions repair quality or interior style;
- uses phrases like "студия", "совмещенный санузел", "светлая", "инфраструктура";
- wants you to interpret whether the ad language hides a drawback.

Quick heuristics:

- `совмещенный санузел`: combined bathroom; space-efficient, but usually a downside for families.
- `студия` / `комната-студия`: open-plan living; good for one person, weak privacy and cooking separation.
- `бабушкин ремонт`: dated interior, likely old finishes and future update cost.
- `дизайнерский ремонт`: premium positioning claim; verify through photos because it is often overstated.
- `светлая квартира`: good natural light claim; verify from photos, window orientation, and room depth.
- `хорошая инфраструктура`: vague marketing shorthand; unpack into transport, groceries, schools, clinics, noise, and walkability.

## Key Notes
- All prices are in **KZT (Kazakhstan Tenge)**
- The `source_id` format is `krisha:XXXXXXX` (e.g., `krisha:1013405508`)
- LLM scores range from **0.0 to 10.0** (higher is better)
- Semantic search works best with Russian-language queries
- Ingestion takes time (~2-5 minutes per page of 20 apartments)
