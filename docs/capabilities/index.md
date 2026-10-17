# Capabilities

## Register

| Card | Status | Enforced at |
| --- | --- | --- |
| `fast-verify` | built | `./tools/verify` |
| `evidence-check` | built | `./tools/verify` (sixth check, `tools/check-plans`); `tools/hooks/pre-commit` where `core.hooksPath` is set |
| `doc-integrity` | specced | — |
| `boundary-lint` | specced | — |
| `isolated-env` | specced | — |
| `prose-duplication` | specced | — |
| `judge-milestone` | built | `./tools/verify` (the fixture self-test); `cycle-run` (the judge itself, before and after every milestone session) |
