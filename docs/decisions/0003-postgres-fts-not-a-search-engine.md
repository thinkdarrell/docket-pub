# 0003 — Search uses PostgreSQL tsvector and tsquery with GIN indexes, not a separate search engine.

## Decision

Search uses PostgreSQL tsvector and tsquery with GIN indexes, not a separate search engine.

## Rationale

A separate engine such as Elasticsearch or Meilisearch is another service to run, back up, and keep in sync, for a corpus of tens of thousands of short items. PostgreSQL's websearch_to_tsquery covers the query shapes readers actually type, and the search_vector column is rebuilt by migration when the indexed fields change (migration 015 added headline and why_it_matters). Revisit only if relevance or latency is measured to fail.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
