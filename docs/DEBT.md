# Debt

## Register

| ID | Item | Where | Why deferred | Trigger to pay it down |
| --- | --- | --- | --- | --- |
| D4 | Local Postgres 16, Railway 18.3 | local environment | Homebrew default; the installed postgresql@18 is not running as a service | `tools/test-db` can be pointed at postgresql@18 by changing the server part of `DATABASE_URL`; do that once that server runs as a service |
| D6 | A worktree using the main checkout's venv tests the main checkout's code | `venv/` editable install | Only one checkout existed | `cycle-plan` builds a venv per worktree; the `isolated-env` card |
| D7 | Six web modules execute SQL directly | `src/docket/web/auth.py`, `admin.py`, `admin_badge_review.py`, `create_admin.py`, `source_security.py`, `public.py` | Grew with the admin surface | The next plan touching each module moves its SQL into `services/` |
| D8 | `ai/` imports `docket.services.badges` | `src/docket/ai/pipeline.py:70`, `batch_ingest.py:252`, `badges_policy.py:106` | Badge slugs live in services | Next change to badge policy moves the enabled-slug lookup into `ai/` or a shared module |
| D9 | No present-tense behaviour specs for ingest, vote matching, AI pipeline, OCR, coverage, blog, transcripts | `docs/specs/` | Design docs under `docs/superpowers/specs/` served as specs | The first plan touching each area reflects its behaviour into `docs/specs/` |
| D10 | `www.docket.pub` is a Namecheap HTTP redirect; HSTS omits `includeSubDomains` | DNS, `src/docket/web/__init__.py` | Apex first | Public launch preparation |
| D11 | Impact-First Phase 4 not built: migration 014 to drop the legacy `summary` column | `src/docket/migrations/` | Waits for every completed item to reach v3 | `SELECT count(*) FROM agenda_items WHERE processing_status='completed' AND ai_rewrite_version IS NULL` returns 0 |
| D12 | About 7,500 consent items sit in `data_quality_skipped` as `no_agenda_text`; the body is in the minutes PDF | `src/docket/ai/wave0.py`, `votes.raw_text` | Needs its own brainstorm; two recovery paths unevaluated | Before the next backfill wave |
| D13 | About 89 withdrawn-family rows use marker shapes Wave 0 does not match | `src/docket/ai/wave0.py` | Shape B landed in PR #22; the rest were listed, not fixed | Next Wave 0 change |
| D14 | No CSRF protection on admin POST routes | `src/docket/web/admin.py`, `src/docket/web/admin_badge_review.py` | Single trusted admin | Before any second admin user or public launch (issue #83) |
| D15 | Branch protection on `main` not enabled; deploy-from-main is discipline | GitHub settings | GitHub Pro required for private repo protection | GitHub Pro or a second committer (issue #37) |
| D16 | OCR assumes `city="birmingham"` and `scan_interval=2` | `src/docket/analysis/ocr/rosters.py`, `src/docket/services/video_ocr.py` | One OCR city | A second city with video (issue #86) |
| D17 | Admin force-rescan has no audit log | `POST /admin/meetings/<id>/rescan-ocr` | Parity with other admin actions left for later | Next admin audit pass (issue #85) |
| D18 | `video_ocr` cron has no Healthchecks ping | Railway worker env `HEALTHCHECK_VIDEO_OCR_UUID` | Ping no-ops cleanly when unset | Create the check and set the variable (issue #89) |
| D19 | Deprecated `scripts/import_video_ocr.py` still present | `scripts/` | Kept one cycle as a schema-mapping reference | Overdue: delete in the next gardening pass |
| D20 | OCR claim window hard-coded to 60 days | `src/docket/services/video_ocr.py` | Manual laptop OCR covers older meetings | Backfilling older meetings by OCR |
| D21 | Blog follow-ups: `extra_css` lint, sitemap, `city_blog_url()` helper, frontmatter type validation, authoring ergonomics | `src/docket/blog/`, `src/docket/web/` | v1 deliberately minimal | Next blog work (issue #92) |
| D22 | Search has no facets or sort | `src/docket/services/query.py` `search_agenda_items` | Separate feature | When search is revisited |
| D23 | Editorial coverage v1.1 to v1.3 surfaces (meeting, member, badge) and v2 proposers not built | templates, coverage schema | Paired chip-plus-block ships | When v1.1 starts |
| D24 | Granicus retraction (403) not detected; ghost rows deleted by hand | `src/docket/adapters/granicus.py` | Rare | Next ghost card |
| D25 | Badge INSERT statements outside `decide_status_and_confidence` in `src/docket/ai/badges_policy.py` rely on the column default for `status` | `src/docket/ai/badges_process.py`, `src/docket/ai/pipeline.py`, `src/docket/services/badges.py`, `src/docket/web/admin.py`, `src/docket/web/admin_badge_review.py` | Correct today via the DB default | Any change to the badge status contract |
| D26 | Manual vote-link correction UI not built; `is_manual` column ready | `src/docket/web/admin.py` | No miss has needed hand-fixing yet | First matcher miss that needs a human |
| D27 | No index on `agenda_items.dollars_amount` | migrations | Not yet slow | EXPLAIN shows a sequential scan at current scale |
| D28 | Source reconciliation (OCR versus minutes on the same meeting) not built | `src/docket/services/` | Few meetings have both | A meeting where both sources disagree reaches a reader |
| D29 | CivicPlus adapter is a stub; Hoover and Montgomery have no data | `src/docket/adapters/civicplus.py` | Hoover's AgendaCenter is empty | Hoover or Montgomery publishes readable data |
| D30 | Test fixture `seed_item` leaves orphan meetings in the local DB | `tests/unit/test_ai_worker_writeback.py` | Cosmetic | Next touch of that test file |
| D31 | A dozen stale `worktree-*` branches on `origin` | GitHub | Left after merges | Overdue: delete in the next gardening pass |
| D32 | A second Postgres service `Postgres-pKpA` exists in the Railway project with no known use | Railway | Unknown origin | Next Railway bill review |
| D33 | `src/docket/rosters/` is a tracked empty package with no importers | `src/docket/rosters/__init__.py` | Left from an early layout | Next plan touching `src/docket/analysis/ocr/rosters.py` deletes it |
| D34 | Five modules read `os.environ` directly instead of through `src/docket/config.py` | `src/docket/ai/batches.py`, `src/docket/web/__init__.py`, `src/docket/worker/tasks.py`, `src/docket/worker/scheduler.py`, `src/docket/worker/health.py` | Added ad hoc; one of them duplicates a setting config exposes | Next plan touching each module routes the read through config |
| D36 | `mv_badge_volume_monthly` has no scheduled refresh after a `WITH NO DATA` rebuild; only migrations rebuild it and a manual non-concurrent REFRESH is needed | `src/docket/migrations/`, `src/docket/worker/tasks.py` | Only matters when a migration recreates the view | Any migration touching the view |
| D37 | The unit-tier fixture `fresh_db` runs `DELETE FROM` on `vote_agenda_items`, `member_votes`, `votes`, `processing_status_audit`, `agenda_item_badges_audit`, `agenda_items`, and test meetings against whatever `DATABASE_URL` names, before each test and never after; it is why a developer `docket_db` ends up with no votes and why the leftover row of the last test survives a run | `tests/unit/test_ai_worker_claim.py` lines 13 to 28 | Predates the disposable database; `./tools/verify` exports a throwaway `DATABASE_URL`, so the suite no longer reaches `docket_db` | Anyone runs the unit tier by hand against a database they care about; the next touch of that file scopes the deletes to rows the test created or moves the tests to the integration tier |
| D38 | `test_013_up_down_up_cycle` rolls back migrations 028 to 021 and 013 and re-applies only versions missing from `schema_migrations`, so migration 033's `is_hidden` rebuild of `mv_badge_volume_monthly` never re-runs and the view is left at migration 022's definition; `test_033_up_refreshes_mv_with_filter` passes only because `test_033_migration.py` collects before `test_migration_013.py` | `tests/integration/test_migration_013.py`, `src/docket/migrations/runner.py` | Harmless on the disposable database within one run, which is the only way `./tools/verify` runs it | A fresh database is not available and the integration tier is rerun, or anyone changes integration collection order; the fix is for the cycle to roll 033 back too, or to restore the view in teardown |
| D39 | `query_a_per_item_divergence` and `query_b1_under_scoring_impact` cast `score_overrides` values with `::int` while `src/docket/ai/pipeline.py` line 368 writes the same dict; a float such as `4.0` in a row breaks the calibration report with `invalid input syntax for type integer` (16 tests failed this way on a poisoned `docket_db`) | `src/docket/services/calibration.py` lines 78 to 92 and 138 to 143, `src/docket/ai/pipeline.py` | Seen only from a test-written row; whether production ever writes floats is unknown | Next change to either file; first check `SELECT count(*) FROM agenda_items WHERE score_overrides->>'original_ai_significance' LIKE '%.%'` on production |
| D40 | The analytics view tests create a database per run named `docket_test_umami_<pid>_<hex>` and two were left on the local server on 2026-10-11; `tools/test-db` does not build them and `./tools/verify` does not drop them | `tests/integration/test_analytics_views.py` line 69 | Cosmetic; a few MB each | Next change to the analytics tests makes the fixture drop its database on teardown; drop the strays by hand meanwhile |

## Details

### D7 — SQL in the web layer

The rule in `ARCHITECTURE.md` says routes call services. The six modules named in the row call `db_cursor()` directly, mostly in admin forms and auth. Fixed means each query becomes a function in `src/docket/services/` with a unit test, and `grep -rl 'db_cursor\|db()' src/docket/web` prints nothing. Pay it down module by module inside plans that already touch each module; do not open a plan for it alone.

### D12 — Consent item text recovery

Birmingham's Granicus agenda lists consent items as title-only references. The body text appears in the post-meeting minutes PDF, which `analysis/minutes_parser.py` already parses for votes and stores in `votes.raw_text`. Two paths were named and neither evaluated: recover the body from the minutes text and re-run Wave 0, or have the adapter follow the item link to the full text at ingest. The brainstorm decides.

### D13 — Withdrawn marker shapes

Shapes not matched: `ITEM N. (WITHDRAWN)`, `(ph) ITEM N. REQUESTED TO BE WITHDRAWN`, `CONSENT(ph) WITHDRAWN ITEM N.`, `CONSENT(ph) ITEM N.- WITHDRAWN`. The matched shapes are in `WITHDRAWN_TITLE_PATTERNS` in `src/docket/ai/wave0.py`. Reclassify with one targeted UPDATE per decision 0026.
