# Docket.pub: Alabama Municipal Meeting Intelligence
**Engineering Strategy & Project Plan | Internal Document**
**Domain:** docket.pub | **Platform:** Municipal Intelligence

## 1. Executive Summary
Docket.pub is an automated intelligence platform designed to ingest, parse, and index municipal meeting records. By centralizing disparate local government data, the platform provides a unified search interface for civic transparency. The project is currently in a **Private Development Phase** to ensure data integrity and system hardening before a public release.

## 2. Technical Architecture

### Backend Infrastructure
* **Core Logic:** Python-based scrapers tailored for municipal document structures (PDF, HTML, and DocumentCloud).
* **Web Framework:** Flask for routing and API management.
* **Frontend:** HTMX for dynamic, low-latency UI updates without heavy JavaScript overhead.
* **Storage:** PostgreSQL for structured meeting metadata and vector storage for semantic search capabilities.

> **Data Honesty Protocol:** Every AI-generated summary or insight is linked directly back to the original source docket hosted on municipal servers.

## 3. Domain Integration (docket.pub)
The acquisition of *docket.pub* transitions the project from a local scraper tool to a centralized service. The following updates are integrated into the build:

| Component | Update Specification |
| :--- | :--- |
| **API Base** | `https://docket.pub/api/v1/` |
| **Semantic Routing** | `/{state}/{city}/meetings/{date}-{slug}` |
| **Security** | Automated TLS/SSL via Let's Encrypt for all subdomains. |
| **Branding** | Unified "Docket.pub" header with high-contrast, accessible UI. |

## 4. Implementation Roadmap

### Phase 1: Ingestion & Scraper Hardening (Current)
Development of robust scrapers for key Alabama municipalities (Birmingham, Mobile, Montgomery). Focus on handling "Silent Breaks" where site structures change without notice.

### Phase 2: Semantic Indexing
Implementation of the parsing engine to extract "Consent Agenda" items and high-value meeting topics into a searchable vector database.

### Phase 3: Frontend & API Deployment
Deploying the Flask/HTMX interface to production via Hetzner or Railway, utilizing the docket.pub domain.

### Phase 4: Public Utility Release
Transition from Private to Public repository status, including a public API for civic researchers and developers.

---
*Confidential Proprietary Document - 2026 Docket.pub Project*
