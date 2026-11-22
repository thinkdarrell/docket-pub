# 0129 — Minutes files are read by a capped stage of ingest, switched on by `adapter_config`, with no transaction open while a file is fetched

## Decision

A city's Minutes files are read by a stage of `ingest_municipality` (4b), for a city whose `adapter_config` names a `minutes_reader`, at most `minutes_read_cap` waiting files a run (10 when absent; 0 reads none while the link rule and the code join go on). It is not a worker task of its own. The read is in two passes: every file taken is fetched and parsed first with no transaction open and nothing written, then each outcome is stored in its own transaction; a dry run stores every outcome on one connection opened after the last file is read, and rolls it back. A file's votes and its member votes are two multi-row inserts, not a statement per vote.

## Rationale

Ingest already holds the adapter that listed the city's events, and the Minutes files are named in that listing, so a stage costs the city no second listing; a separate task would list again or share state across tasks. Decision `0111` made the same choice for hearings. No task in `src/docket/worker/tasks.py` was touched, and a failure is a line of the city's ingest errors under the worker's existing per-city isolation.

The settings follow decision `0122`: a city with neither key is ingested exactly as before, the backlog is brought in by a setting and a supervised script that runs the same service (`scripts/read_minutes_votes.py`), and a value that cannot be read is the run's one error before any request. The cap bounds what one morning asks of the city's site (one request a second) and of production; 0 is the stop without a deploy.

The two passes are there because the first design held one transaction across the whole run. The operator's backfill is about seven minutes of requests; with the update of `meetings.minutes_url` on 225 rows uncommitted for those minutes, any writer of those meeting rows would wait, the trap decision `0103` records as observed. Reading first and storing after keeps each transaction as long as its statements. The dry run still runs the real statements, which is what `0103` keeps a dry run for; its cost is that a full dry run inserts and rolls back every vote, so it is run once.

The stage does not consult `processing_status.votes_scanned`, which the vote stage sets on every CivicClerk meeting with a minutes link because `fetch_votes` returns nothing: which files are waiting is said by `minutes_files` alone.

## Date

2026-11-21, the authoring session of plan `mobile-votes-from-minutes` (Claude); the two passes added the same day from an outside review the operator supplied; built by that plan's M3 and M4 and graduated by its M6 session on 2026-11-22 (UTC).

## Status

accepted
