# 0020 — The video OCR pipeline is native to src/docket/analysis/ocr/; the al-municipal-meetings repository stays a research sandbox and is not absorbed into this one.

## Decision

The video OCR pipeline is native to src/docket/analysis/ocr/; the al-municipal-meetings repository stays a research sandbox and is not absorbed into this one.

## Rationale

PR #84 ported the classifier, header, layout, sequence, pipeline, frame I/O, and roster modules so OCR could run as a cron task against the production schema with its own idempotent persistence. The rest of al-municipal-meetings (its SQLite store, notebooks, and experiments) has no reader here, and absorbing it would import a second data model. scripts/import_video_ocr.py, the old bridge, is deprecated (docs/DEBT.md D19).

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-22)

## Status

accepted
