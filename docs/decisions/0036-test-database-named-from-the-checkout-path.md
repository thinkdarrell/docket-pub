# 0036 — The disposable test database is named docket_test_<hash>, the hash being the first eight hex characters of the SHA-1 of the checkout's absolute path, and it is built on the server DATABASE_URL names.

## Decision

`tools/test-db` names the database it builds `docket_test_<hash>`, where `<hash>` is the first eight hex characters of `shasum` over the checkout root's `pwd -P`, computed after changing to the repository root so the name is the same from any directory inside the checkout. It is created on the server that `DATABASE_URL` names, resolved the way the application resolves it (`docket.config`, `.env` included), with only the database name replaced. `tools/test-db --drop` removes it by recomputing the same name.

## Rationale

The design document proposed a single `docket_test` database rebuilt on every run with `DROP DATABASE ... WITH (FORCE)`. Two worktrees running `./tools/verify` at the same time, which the factory's worktree-per-plan shape makes routine, would then drop each other's database mid-run and both would go red for a reason neither could see. The `isolated-env` card asks for exactly the property a per-checkout name provides.

A name derived from the process id, which the analytics test fixtures use (`docket_test_umami_<pid>_<hex>`), was rejected: a later run cannot recompute it, so a run killed before teardown leaves a stray that nobody drops (`D40` in `docs/DEBT.md` is that stray). A name derived from the path can be recomputed by the next run, so drop-before-create is idempotent, a failed run's leftover is replaced on the next run, and an operator reading `pg_database` can tell which checkout a `docket_test_*` row belongs to by hashing the path.

Building on the same server as `docket_db` rather than on the installed postgresql@18 keeps the plan from owning a machine change; `D4` records that `tools/test-db` can be pointed at another server by changing the server part of `DATABASE_URL`. Resolving the base URL through `docket.config` rather than the shell alone matters because the tests themselves reach the server that way: the shell has no `DATABASE_URL` on the operator's machine, and `load_dotenv` finds the `.env` above the worktree, so a database built anywhere else would not be the one the tests connect to. `tools/verify` exports the resulting URL, which `load_dotenv` does not override.

## Date

2026-10-11, the factory-tools plan author and M2 session (Claude, for the operator); graduated from the plan's Decision Log at its retrospective.

## Status

accepted
