# 0055 — The test suite's database guard keys on the exact marker expression `live` and has no escape hatch

## Decision

`tests/conftest.py` refuses, before any test is collected and with exit status 2, a `DATABASE_URL` (from the shell, or from `.env` when the shell has none) whose database is not named `docket_test_*`, unless the pytest marker expression is exactly `live`. No environment variable, command-line option, or configuration value lifts the refusal. A tier is run against another database by not doing that: `tools/test-db` builds a disposable one and `./tools/verify` exports it.

## Rationale

The unit tier's `fresh_db` fixture deletes rows from whatever `DATABASE_URL` names (`docs/DEBT.md` `D37`), and it reached developer `docket_db` databases because a person decided, each time, that the URL in the shell was fine. The guard exists to remove that judgment. The obvious convenience, an environment variable such as `DOCKET_ALLOW_DB=1` for the day a developer wants to run one tier against a database they care about, re-introduces exactly that judgment, and the first time it is set in a shell profile the guard is gone. A disposable database costs one to three seconds to build, which is less than the convenience saves.

The live tier reads a real database by design, and `pyproject.toml` already makes `-m live` the one way to select it, so the marker expression is the exemption, and it is exact: `live or slow` or `not live` also select the deleting tiers and are refused. A `markexpr` of `None` (pytest received no `-m`, which `pyproject.toml`'s `addopts` prevents) falls through to the check for the same reason. The guard is `tests/conftest.py`'s and so covers the tiers under `tests/`; `transcriber/tests` has no conftest and deletes only rows it inserted, by id, so it is left alone; and pytest's own `--noconftest` flag skips the guard, which `D37` names, because that switch is pytest's and not a hatch this repository added.

## Date

2026-10-17, the plan author (Claude, in the operator's session) in `plans/active/factory-enforcement.md`; graduated from the plan's Decision Log at its retrospective on 2026-10-18.

## Status

accepted
