# Capabilities

## Register

| Card | Status | Enforced at |
| --- | --- | --- |
| `fast-verify` | enforced | `./tools/verify`; the `verify` job in `.github/workflows/verify.yml`, the required status check on `main` (decision 0052) |
| `evidence-check` | enforced | `./tools/verify` (sixth check, `tools/check-plans`); the `verify` job in `.github/workflows/verify.yml`, the required status check on `main` (decision 0052); `tools/hooks/pre-commit` where `core.hooksPath` is set |
| `doc-integrity` | specced | — |
| `boundary-lint` | specced | — |
| `isolated-env` | specced | — |
| `prose-duplication` | specced | — |
| `judge-milestone` | built | `./tools/verify` (the fixture self-test); `cycle-run` (the judge itself, before and after every milestone session) |
