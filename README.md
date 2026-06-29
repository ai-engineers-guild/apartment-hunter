# Apartment Hunter

> [!WARNING]
> **Legal Disclaimer:** This is a private automation tool for personal use only. By using this software, you agree to the [Legal Disclaimer and Fair Use Policy](LEGAL.md).

Apartment Hunter is a powerful aggregator and search platform for rental apartments. It automates finding, filtering, and scoring housing options across various sources (like krisha.kz) without manually checking the websites every hour. It supports precise polygon-based geographic search, semantic text search (RAG), and LLM-powered quality scoring.

## Quick Start

```powershell
# 1. Start the MCP server for Codex Desktop / Claude
uv run apartment-hunter-mcp

# 2. Or run the data ingestion pipeline manually
uv run apartment-hunter-ingest
```

## Use Cases

- **Agents / MCP:** Connect it to Codex Desktop to chat with your apartment database ("Show me 2-bedroom apartments near Megapark under 500k, sort by newest").
- **Precise Geography:** Stop relying on inaccurate text search. Draw a polygon on a map, pass the coordinates, and only get apartments strictly within that exact boundary.
- **AI Scoring:** Automatically rate apartments out of 10 based on renovation quality, furniture condition, and specific user preferences using Vision LLMs.
- **Market Monitoring:** Run ingestion periodically (e.g. via cron) to track price drops and immediately catch new listings before they are rented out.

## License

[MIT](LICENSE)
