---
name: html-report-generator
description: Generates a beautiful HTML report of apartments from a JSON list and serves it on localhost.
---

# HTML Report Generator

Use this skill when the user wants to see a list of apartments visually instead of just reading text in the chat.
This skill will generate a polished HTML page with photos, prices, and links, and start a local HTTP server to display it.

## How to use:
1. Search for the apartments the user requested using your available MCP tools (e.g. vector search, DB query).
2. Save the resulting list of apartments to a JSON file named `apartments.json` in the `.agents/skills/html-report-generator/scripts/` directory. The JSON should be a list of objects with at least: `title`, `price`, `url`, `photos` (list of urls), `description`.
3. Run the python script to generate and serve the report:
   ```bash
   cd .agents/skills/html-report-generator/scripts
   python generate.py
   ```
4. Tell the user that the report is available at `http://localhost:8080/report.html`.
