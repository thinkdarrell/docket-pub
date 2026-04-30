# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**docket.pub** — a municipal meeting intelligence platform that ingests, parses, and indexes public meeting records from Alabama cities (Birmingham, Mobile, Montgomery). The goal is civic transparency: make local government dockets searchable and link every AI-generated summary back to the original source document.

Domain: `docket.pub` | Status: **Private Development Phase**

This project builds on work from the [al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) repo (Birmingham-focused Granicus scraper with vote OCR). docket.pub generalizes that into a multi-city platform with a public-facing web interface.

## Layout

```
docket-pub/
  web/                 # Flask application + HTMX templates
    __init__.py
  scrapers/            # Per-city scraper modules
    __init__.py
  docs/                # Internal project documentation
    Docket_pub_Project_Plan.md
  requirements.txt     # Python dependencies
  .env.example         # Environment variable template (copy to .env)
  .gitignore           # Excludes .env, venv/, __pycache__/, IDE configs
```

## Tech Stack

- **Language:** Python 3.10+
- **Web Framework:** Flask
- **Frontend:** HTMX for dynamic UI without heavy JS
- **Database:** PostgreSQL for structured meeting metadata + vector storage for semantic search
- **Deployment target:** Hetzner or Railway

## Key Commands

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit with real credentials

# Run development server
flask run
```

## Architecture Principles

- **Data Honesty Protocol:** Every AI-generated summary or insight MUST link directly back to the original source docket on the municipal server. No unsourced claims.
- **Semantic routing:** URLs follow `/{state}/{city}/meetings/{date}-{slug}` pattern.
- **API base:** `https://docket.pub/api/v1/`
- **Silent Break monitoring:** Scrapers must detect and alert when a city website changes its layout, so data collection doesn't silently fail.

## Conventions

- Environment secrets (API keys, DB passwords) go in `.env`, never committed. Only `.env.example` with placeholders is tracked.
- Scraper modules live in `scrapers/`, one module per city or data source.
- Web routes live in `web/`. Keep routes thin — business logic belongs in service modules.
- All Python modules use absolute imports.

## Related Repositories

- [thinkdarrell/al-municipal-meetings](https://github.com/thinkdarrell/al-municipal-meetings) — Birmingham city council scraper with Granicus integration and vote OCR. The upstream data pipeline work that docket.pub builds on.
