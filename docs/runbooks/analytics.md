# Analytics Runbook

Operational procedures for the `analytics` Railway service (self-hosted Umami) and the `umami` database on the existing Railway Postgres instance.

Spec: `docs/superpowers/specs/2026-05-15-umami-analytics-design.md`

## Initial Setup (one-time)

Prerequisites: `psql`, Railway CLI, registered SSH key (`railway ssh keys`), Namecheap DNS access for docket.pub.

### 1. Provision DB and roles

Record the printed passwords in 1Password before proceeding — the shell vars only live for this terminal session.

```bash
# Generate passwords (record in 1Password under "docket.pub / Umami")
UMAMI_PW=$(openssl rand -base64 32)
UMAMI_READER_PW=$(openssl rand -base64 32)
echo "UMAMI_PW=$UMAMI_PW"
echo "UMAMI_READER_PW=$UMAMI_READER_PW"

# Create roles and database
/opt/homebrew/opt/postgresql@18/bin/psql "$DATABASE_PUBLIC_URL" <<SQL
CREATE ROLE umami WITH LOGIN PASSWORD '$UMAMI_PW' CONNECTION LIMIT 8;
CREATE DATABASE umami OWNER umami;
GRANT ALL PRIVILEGES ON DATABASE umami TO umami;

CREATE ROLE umami_reader WITH LOGIN PASSWORD '$UMAMI_READER_PW';
GRANT CONNECT ON DATABASE umami TO umami_reader;
SQL
```

(The `GRANT SELECT` on views happens after the view layer is applied in step 5.)

### 2. Create the `analytics` Railway service

Generate the secret values in your terminal first (the Railway dashboard does not evaluate shell expressions — pasting `$(openssl rand ...)` literally sets the variable to that string):

```bash
echo "APP_SECRET=$(openssl rand -base64 48)"
echo "HASH_SALT=$(openssl rand -base64 24)"
```

**Use the Railway Umami template** — it pre-configures the image, Valkey cache, and (effectively) the Postgres wiring. The Empty Service flow is a footgun: the Source → Image picker is fragile and the template handles the deploy correctly with one click.

In the Railway dashboard for the docket.pub project:
1. **+ New → Templates** → search **"Umami"** → pick the official one (verify `umamisoftware/umami` shows in the preview) → **Deploy**.
2. The template provisions:
   - `umami` service (the app, currently Umami v3.x)
   - `Valkey` service (Redis-compatible cache used by v3 for sessions/caching — required)
   - "Postgres" service entry — this is a *reference* to the existing project Postgres, NOT a new instance. Railway's template auto-detects the existing Postgres and reuses it. No second Postgres bill.
3. Wait ~60s for `umami` and `Valkey` to go green.
4. **Repoint Umami at our pre-provisioned `umami` database**: the template defaults Umami to `DATABASE_URL=postgresql://postgres:...@.../railway` (superuser + editorial DB — wrong). Override it via CLI:

   ```bash
   railway variables --service umami --set \
     "DATABASE_URL=postgresql://umami:<UMAMI_PW>@postgres.railway.internal:5432/umami?connection_limit=5"
   ```

   Umami will redeploy. After ~30s, verify Umami's tables landed in the `umami` database (not in `railway`):

   ```bash
   /opt/homebrew/opt/postgresql@18/bin/psql \
     "postgres://umami:<UMAMI_PW>@<RAILWAY_PG_PUBLIC_HOST>:<PORT>/umami?sslmode=require" \
     -c "\dt"
   ```

   Expected output includes `website_event`, `event_data`, `session`, `website`, plus v3 tables like `board`, `session_replay`, `pixel`, `link`, `team`, etc.
5. **Record the template's auto-generated `APP_SECRET` and `HASH_SALT` in 1Password** (the values you generated locally are unused — keep what the template set):

   ```bash
   railway variables --service umami --kv | grep -E '^(APP_SECRET|HASH_SALT)='
   ```
6. Settings → Networking → Generate Domain on the `umami` service (note the `*.up.railway.app` URL temporarily).

(Historical note: an earlier version of this runbook used Empty Service + explicit `umamisoftware/umami:postgresql-v2.20.2` image. That worked architecturally but the Railway UI for setting the image during Empty Service creation is fragile. The template is cleaner. Trade-off: we lose explicit image-tag pinning, but Umami releases are well-tested and Railway can roll back if a deploy regresses.)

### 3. Custom domain (`stats.docket.pub`)

In Railway Settings → Custom Domain for the `analytics` service:
1. Add `stats.docket.pub`. Railway provides a CNAME target.
2. In Namecheap (docket.pub DNS): add `CNAME stats → <railway-target>`. TTL 5 min for initial provisioning.
3. Wait for Let's Encrypt cert (typically 2–10 min). Refresh Railway domain page until "Active" appears.
4. Visit `https://stats.docket.pub` — should redirect to Umami's login page with valid cert.

### 4. First-boot admin

Default credentials are `admin / umami`. **Immediately:**
1. Log in.
2. Settings → Profile → change password (record in 1Password under "docket.pub / Umami admin").
3. Settings → Websites → Add Website → Name: "docket.pub", Domain: "docket.pub".
4. Copy the generated **Website ID** (the UUID shown next to the website name; not the full `<script>` snippet which Umami also calls 'Tracking Code'). Record it in 1Password and as `UMAMI_WEBSITE_ID` for task 6.
5. Edit Website → Excluded URLs (one per line):
   ```
   /admin/*
   /healthz
   *.rss
   /al/*/data-debt.rss
   /al/*/upcoming-hearings.rss
   /coverage.rss
   ```
6. Settings → Websites → docket.pub → Share → enable public sharing. Copy the **Share URL** (looks like `https://stats.docket.pub/share/<token>/docket.pub`). Record for the footer 'Site usage' link added later in the rollout.

### 5. Capture schema fixture and apply views

The fixture seeds the integration test; the view layer is the queryable surface.

```bash
# From the laptop. Captures only Umami's schema, no data.
# (Find the public host and port in the Railway dashboard → Postgres service → Connect tab;
# or copy from $DATABASE_PUBLIC_URL if that env var is set.)
/opt/homebrew/opt/postgresql@18/bin/pg_dump --schema-only --no-owner --no-privileges \
  "postgres://umami:<UMAMI_PW>@<RAILWAY_PG_PUBLIC_HOST>:<PORT>/umami" \
  > tests/fixtures/umami_schema_v3.sql

# Apply our view layer
/opt/homebrew/opt/postgresql@18/bin/psql \
  "postgres://umami:<UMAMI_PW>@<RAILWAY_PG_PUBLIC_HOST>:<PORT>/umami" \
  -f db/umami_views.sql
```

**Note on v3 schema:** Umami v3 moved `country`/`region`/`city` columns from `website_event` to the `session` table. Our `v_geo_daily` view JOINs `website_event` to `session` to keep the public view-layer shape stable. If a future Umami release renames columns again, `db/umami_views.sql` is the single point of repair — consumers (Claude queries, cheat-sheet examples) don't move.

### 6. Worker env vars (for the retention task — task 4)

In Railway dashboard, `worker` service → Variables, add:
- `ANALYTICS_DATABASE_URL=postgres://umami:<UMAMI_PW>@postgres.railway.internal:5432/umami?connection_limit=2` (use the internal hostname — the worker runs inside the Railway VPC so `postgres.railway.internal` resolves; reserve the public host for laptop-based connections only)
- `HEALTHCHECK_PRUNE_ANALYTICS_UUID=<new-uuid-from-healthchecks.io>`

Create a new Healthchecks.io check named `prune_analytics` with schedule `0 4 1 * *` (1st of each month at 04:00 America/Chicago) and grace period 24 hours. Paste the UUID.

### 7. Reader credentials for ad-hoc Claude queries

Add to `~/.docket-pub.env.local` (not committed). Use the public host/port here — this file is read from the laptop, not from inside the Railway VPC. (Find the public host and port in the Railway dashboard → Postgres service → Connect tab.)

```bash
UMAMI_READER_URL="postgres://umami_reader:<UMAMI_READER_PW>@<RAILWAY_PG_PUBLIC_HOST>:<PORT>/umami"
```

## Routine Operations

### Querying analytics

```bash
source ~/.docket-pub.env.local
/opt/homebrew/opt/postgresql@18/bin/psql "$UMAMI_READER_URL" \
  -c "SELECT normalized_path, SUM(pageviews) AS views FROM v_pageviews_daily WHERE day >= current_date - 7 GROUP BY 1 ORDER BY 2 DESC LIMIT 20;"
```

See `docs/analytics-queries.md` for the cheat sheet.

### track.js sanity check

After Task 6 lands `track.js` in `base.html`, verify the helper loaded and the PII guardrail works. Open the browser dev console on any docket.pub page and run:

```javascript
__docketTrackInternals.sanitizeProps({short: 'ok', long: 'x'.repeat(50), num: 42});
// Expected: {short: 'ok', num: 42}   (the 50-char `long` value is dropped)

docketTrack('test_event', {q: 'topic'});               // should not throw
docketTrack('test_event', {q: 'x'.repeat(100)});       // should not throw; `q` is dropped
```

If `docketTrack` is `undefined`, the script tag in `base.html` is not loading — check the dev tools Network tab for `track.js`.

### Manual retention trigger

```bash
railway ssh --service worker
```

Inside the container shell that opens, run:

```bash
python -m docket.worker.scheduler --run-once prune_analytics
```

### Umami version bump

1. Update the `analytics` service image tag in Railway dashboard.
2. After redeploy, re-capture the schema fixture (step 5 above).
3. Run the integration tests: `pytest tests/integration/test_analytics_views.py -v`.
4. If any view definition broke, fix `db/umami_views.sql` and re-apply.
5. Commit both the new fixture and any view changes.

## Failure Modes

- **Tracker JS blocked by adblocker**: `docketTrack()` no-ops gracefully — page never breaks. Affected sessions don't generate pageviews; this is expected and bounded. If capture rate drops materially, the documented Phase 2 path (in-app reverse proxy at `docket.pub/s/script.js`) restores capture. See the spec's Future Directions section.
- **Prisma queue timeout under spike**: events drop, `docket-web` unaffected. See spec Risks.
- **`umami` role hits 8-connection cap**: Postgres rejects new Umami connections until existing ones close. Container does not crash thanks to `connection_limit=5` on the Prisma side.
- **stats.docket.pub cert expired**: Let's Encrypt auto-renews via Railway. If it lapses, regenerate via the Custom Domain panel.
