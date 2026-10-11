# 0002 — Every city is reached through an adapter implementing MunicipalSourceAdapter in src/docket/models/protocol.py; adding a city on a supported platform is a row in the municipalities table plus council data, not new code.

## Decision

Every city is reached through an adapter implementing MunicipalSourceAdapter in src/docket/models/protocol.py; adding a city on a supported platform is a row in the municipalities table plus council data, not new code.

## Rationale

Four vendor platforms already differ in shape: Granicus is scraped HTML, CivicClerk is a REST API, Homewood is an HTML archive of PDFs, CivicPlus is an AgendaCenter. Isolating each behind one protocol keeps the ingest service generic and lets a new city on a known platform land as configuration. The alternative, per-city scrapers, would have grown linearly with cities and leaked vendor quirks into services.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
