# Docket.pub Platform

An internal intelligence platform and data pipeline designed to automate the collection, parsing, and indexing of municipal meeting records.

## Project Vision
To provide a centralized, searchable portal for local government transparency, mapping "public dockets" to a structured, accessible format.

## Current Phase: [Private Development]
The project is currently in the **Build & Hardening** phase.

### Internal Tech Stack
- **Language:** Python 3.10+
- **Framework:** Flask + HTMX
- **Database:** PostgreSQL (Internal)
- **Deployment:** [Hetzner / Railway]

## Local Setup
1. **Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configuration:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```
3. **Run:**
   ```bash
   flask run
   ```
