# 0025 — The Strict-Transport-Security header is sent with max-age of one year and without includeSubDomains until www.docket.pub is served by Railway.

## Decision

The Strict-Transport-Security header is sent with max-age of one year and without includeSubDomains until www.docket.pub is served by Railway.

## Rationale

www.docket.pub is a Namecheap URL redirect that answers only over HTTP. With includeSubDomains, a browser that had visited the apex would force www to HTTPS and the redirect would fail. The pickup steps (second Railway custom domain, CNAME, Flask redirect from www to apex, then includeSubDomains and possibly preload) are docs/DEBT.md D10.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes (original decision 2026-05-04)

## Status

accepted
