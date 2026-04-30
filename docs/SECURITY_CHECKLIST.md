# Security Checklist — docket.pub

Pre-deployment security requirements and ongoing concerns. Nothing here is urgent while in private development, but everything must be addressed before any public-facing deployment.

---

## Pre-Deployment (Must Do)

### Flask Application Security

- [ ] **Set `SECRET_KEY` from environment** — never use the placeholder from `.env.example`
- [ ] **`DEBUG=False` in production** — debug pages leak environment variables, DB credentials, and stack traces
- [ ] **CSRF protection** — enable `flask-wtf` CSRFProtect on all forms
- [ ] **Secure headers** — add via `flask-talisman` or middleware:
  - `Strict-Transport-Security` (HSTS)
  - `Content-Security-Policy`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- [ ] **HTTPS only** — redirect all HTTP to HTTPS, set `SESSION_COOKIE_SECURE=True`
- [ ] **Separate admin from public** — different Flask blueprints, admin routes behind authentication

### Rate Limiting

- [ ] **Add `flask-limiter`** on all public endpoints
- [ ] **Aggressive limits on search** — FTS queries with GIN indexes are CPU-intensive
- [ ] **Per-IP and global limits** — prevent a single bot from exhausting DB connections
- [ ] **429 response with `Retry-After` header** — be polite about rejecting

### Input Sanitization

- [ ] **Search input** — wrap `to_tsquery()` calls to prevent malformed syntax errors. Use `plainto_tsquery()` or `websearch_to_tsquery()` for user input instead of raw `to_tsquery()`
- [ ] **Pagination parameters** — validate `limit` and `offset` are positive integers with sane maximums (e.g., limit <= 100)
- [ ] **Municipality slug** — validate against known slugs, don't pass raw input to SQL

### Output Escaping

- [ ] **Jinja2 autoescaping** — enabled by default, but verify all HTMX partial responses also escape
- [ ] **Agenda item titles/descriptions** — contain text scraped from city websites, treat as untrusted. The CivicClerk adapter strips HTML, but Granicus stores raw text
- [ ] **URL attributes** — any `href` or `src` built from DB data must be validated (no `javascript:` URIs)

### Dependency Management

- [ ] **Pin exact versions** — generate `requirements.lock` or use `pip freeze` for reproducible builds
- [ ] **Audit dependencies** — `civic-scraper` pulls in scrapelib, lxml, feedparser, demjson3 — review for known CVEs
- [ ] **Dependabot or similar** — automated alerts for vulnerable dependencies
- [ ] **Minimize production deps** — `civic-scraper` is only needed for the ingest pipeline, not the web server. Consider separating worker and web dependencies.

---

## Infrastructure (Deploy Time)

### Docker / PostgreSQL

- [ ] **Don't expose PostgreSQL port to the internet** — bind to `127.0.0.1` or use Docker internal networking only
- [ ] **Separate DB credentials** — web app gets read-only credentials, ingest pipeline gets read-write
- [ ] **Connection pooling** — use PgBouncer or connection limits to prevent pool exhaustion from request spikes
- [ ] **Database backups** — automated, tested restores
- [ ] **Container base images** — use slim/distroless images, scan for CVEs

### Environment

- [ ] **Never commit `.env`** — `.gitignore` covers this, but verify in CI
- [ ] **Rotate secrets** — `SECRET_KEY`, `DATABASE_URL` credentials
- [ ] **Logging** — structured logs, no credentials or PII in log output

---

## Ongoing Concerns

### Upstream Scraping

- [ ] **Respect rate limits** — adapters have `delay` config (0.5-1.0s), but nothing enforces this at the service layer. A loop calling `ingest_municipality()` repeatedly could hammer a city's servers
- [ ] **User-Agent identification** — GenericCMSAdapter sends `"Mozilla/5.0 (docket.pub civic data scraper)"`. All adapters should identify themselves honestly
- [ ] **Circuit breaker** — if a city's server returns errors, stop retrying. Currently adapters will raise exceptions but could be retried indefinitely by a caller
- [ ] **IP blocking risk** — if a city blocks our scraping IP, we need fallback plans (different IP, slower rate, reaching out to city IT)

### Data Integrity

- [ ] **Stale data detection** — `ON CONFLICT DO NOTHING` on agenda item inserts means upstream edits are never reflected. Consider `ON CONFLICT DO UPDATE` or a freshness check
- [ ] **Source verification** — no checksums or versioning on scraped data. If a city retroactively edits an agenda, we show stale data with no indication
- [ ] **Data Honesty Protocol enforcement** — every displayed data point must link to its original source. If `source_url` is NULL, the UI should indicate "Source unavailable" rather than hiding the gap

### SSRF (Server-Side Request Forgery)

- [ ] **Adapter config validation** — adapters fetch URLs constructed from `municipalities.adapter_config` (JSONB). If someone gains write access to this table, they could point an adapter at internal services (e.g., `http://169.254.169.254/` for cloud metadata)
- [ ] **URL allowlisting** — validate adapter URLs against known domains before fetching
- [ ] **Low risk today** — no admin UI exists to modify the municipalities table, but this matters when one is built

### PDF Links

- [ ] **Homewood adapter** stores direct PDF URLs from a third-party CDN (`irp.cdn-website.com`). We don't validate these are actually PDFs
- [ ] **Content-Type verification** — if serving or proxying PDFs, verify the `Content-Type` header
- [ ] **Don't proxy blindly** — link to source PDFs, don't download and re-serve them (avoids liability and storage costs)

---

## Authentication Plan (When Needed)

Currently no auth is needed — all data is public civic records. When admin features are added:

- **Public routes** — no auth required (search, browse, meeting detail)
- **Admin routes** — session-based auth with strong passwords, consider SSO
- **Ingest/backfill triggers** — CLI only (no web trigger without auth)
- **Future API** — API keys with rate limits per key, usage tracking

---

## Comparison Notes (from Councilmatic review)

NYC Councilmatic uses:
- Django's built-in auth (session-based) — similar approach for Flask
- CSRF middleware — equivalent is `flask-wtf`
- Blackbox encryption for secrets in version control — we use `.env` (simpler, fine for small team)
- No visible rate limiting — this is a gap in their project too
- Solr for search — we use PostgreSQL FTS (simpler, fewer moving parts, adequate for our scale)
