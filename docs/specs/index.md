# Behavior specs

## The reflection rule

A plan does not complete until its behavioral outcome is reflected here.
Before a plan moves to `plans/completed/`, whatever a user or caller can now
observe that they could not before is written into a spec file in this
directory — as a new file, or as an edit to the file that already owns that
behavior — and listed in the index below.

A plan whose outcome is purely internal (a refactor, a dependency bump)
reflects nothing and says so in its own Outcomes section. Silence is only
acceptable when it has been stated.

Spec files are overwritten freely: they describe the present, so an edit
that contradicts last month's text is a correct edit, not a lost one. The
history lives in version control and in `plans/completed/`.

## Index

| Spec | Covers |
| --- | --- |
| `operations.md` | How the system is run: environments, tests (`./tools/verify`, the disposable `docket_test_<hash>` database, the live-tier exclusion, the milestone judge as verify's third check), deploys, Railway, domain, transcriber, runbook index |

Present-tense behaviour specs do not exist yet for the areas `D9` in `docs/DEBT.md` lists; the design documents under `docs/superpowers/specs/` describe each as of the day it shipped.
