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
| `operations.md` | How the system is run: environments (including the `node` requirement and the hooks path), tests (`./tools/verify`, the disposable `docket_test_<hash>` database, the live-tier exclusion, the milestone judge as verify's third check, the saved-workflow shape check as its fourth, the producer suite as its fifth, the active-plan check as its sixth, continuous integration), running the factory (`/cycle-plan`, `/cycle-run`, the `limit`, the closing sequence, halts and resume), deploys, Railway, domain, transcriber, runbook index |
| `calibration.md` | The daily calibration report and the `/admin/calibration` dashboard: what they compare, their windows and thresholds, how scores are read |
| `city-page.md` | The city page at `/al/<slug>/`: its sections and their empty, partial, and full states, the opener's rules (the last meeting, the dollar check, what a split vote names, one source per meeting, link limits, the 14-day wording, the meta description), the `briefing` metadata gate, the shared source panel and footer, the `briefing_facts` worker task (schedule, table, payload shapes, staleness on source health), the `since` and `order=amount` parameters, and the seed the tests render against |
| `transcripts.md` | What the producer uploads (the hallucination and prompt-leak filters, the prose prompt, the per-word speaker split, `TRANSCRIPT_VERSION`, the `--meeting-id` re-claim, what stays public during a re-run, what a failed re-run leaves behind, and what a re-upload clears) and the transcript comparison stage: which categories a model may assign, how a vote result is read, and what a re-comparison does to reviewed rows |

Present-tense behaviour specs do not exist yet for the areas `D9` in `docs/DEBT.md` lists, except the transcript comparison stage and the producer's output rules, which `transcripts.md` covers, and the city page, which has its own row above; the design documents under `docs/superpowers/specs/` describe each as of the day it shipped.
