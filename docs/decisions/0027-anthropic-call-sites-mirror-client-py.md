# 0027 — Every new Anthropic API call site uses the tool-use pattern established in src/docket/ai/client.py (forced tool call, Pydantic-validated result, retries) and is smoke-tested against the live API before it ships.

## Decision

Every new Anthropic API call site uses the tool-use pattern established in src/docket/ai/client.py (forced tool call, Pydantic-validated result, retries) and is smoke-tested against the live API before it ships.

## Rationale

Hand-rolled call shapes elsewhere in the codebase broke on schema validation in production in ways the mocked unit tests could not see. One client pattern means one place to fix retries, pricing, and caching, and the live smoke test (tests/live/) is the only check that exercises the real model's output shape.

## Date

2026-10-11, recorded at harness bootstrap by the operator and Claude from CLAUDE.md and operator notes

## Status

accepted
