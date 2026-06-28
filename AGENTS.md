# Apartment Hunter Agent Rules

- User-facing conversation is Russian by default.
- Keep `apartment_hunter` as the reusable library. Do not move source-specific logic into core.
- Put site-specific parsing, URL building, and source quirks only into `src/apartment_hunter/adapters/<source>`.
- Prefer adding capabilities through `SourceAdapter`, `StorageBackend`, `VectorStore`, and MCP composition instead of special cases.
- `src/krisha` is legacy compatibility code. Do not let it drive new architecture.
- `is_new` means first discovery of an apartment only. Current-run deltas should come from pipeline results.
- When extending monitoring, prefer explicit run history or event logs over heuristic DB diffs.
- When adding search semantics, keep canonical fields generic and put vocabulary mapping into skills or adapter-specific translation layers unless it is cross-source.
- Skills live under `.agents/skills`. Keep `SKILL.md` concise and move long domain notes into `references/`.
- For project validation run:
  `uv run ruff check .`
  `uv run pytest`
  `uv run pytest --cov`
