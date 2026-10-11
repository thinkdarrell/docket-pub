# Principles

Six rules that outrank convenience in this repository. Constraints imposed from outside live in `GOALS.md`; these are chosen.

## Source or silence

The rule: every data point shown to a reader links to the city's own document, and a value the source does not supply is shown as missing rather than filled with a plausible default.
Violated when: an LLM summary hallucinates a name, date, or dollar amount not strictly present in the source text; a template renders a fact without a corresponding source link or badge; or a SQL query maps a NULL to "0", "Unknown", or an assumed default on its way to the page.

## Keep the sources apart

The rule: a fact from video OCR and a fact from the official minutes carry their origin wherever they travel, are never merged into one column without a source flag, and a disagreement between them is displayed as a disagreement, not resolved by code.
Violated when: a migration, query, or data model uses `COALESCE()` or similar logic on a column that carries source provenance to merge OCR and minutes data into one field; or a page displays one vote count when the two underlying sources disagree.

## Framing follows the data

The rule: editorial text says what the record shows and does not manufacture balance, caveats, or a second side the record does not contain.
Violated when: an AI prompt or summary adds "on the other hand," "weighing the options," or "critics might say" without an explicit agenda item, recorded vote, or source citation supporting that opposition; or when editorializing adjectives replace raw municipal facts.

## Evidence or silence

The rule: a change is reported as working only after the command that proves it has run and its output was observed; a change to a data pipeline is compared old against new on real rows before it ships.
Violated when: an agent, plan, or PR claims a test passed or a fix worked without recording the `pytest` summary line or the script's output; a pipeline change is shipped on unit tests alone without a recorded SQL `SELECT` showing before-and-after results on real data; or a plan names the command that *would* prove the change instead of what running it actually printed.

## Production is not a sandbox

The rule: nothing runs a per-row sweep, a full re-ingest, or an unbounded batch against the Railway database or the Anthropic API; bulk changes are one targeted SQL statement with a WHERE clause, and batches are bounded by a limit and the daily budget.
Violated when: an agent writes an `UPDATE` or `DELETE` statement against `DATABASE_PUBLIC_URL` without a strict, narrow `WHERE` clause; a CLI API invocation omits the `--limit` flag; or a script loops per-row writes over thousands of production rows instead of issuing one statement (decision 0026 records the incident this prevents).

## One owner per fact

The rule: every fact about this project lives in exactly one file, and every other file that needs it links there instead of restating it.
Violated when: an agent hardcodes prompt rules, API constraints, or badge definitions inside a service module rather than importing them from the module or table that owns them (`src/docket/ai/prompts.py`, `src/docket/ai/badges_policy.py`, `src/docket/config.py`, the `priority_badge_templates` table); or two files state the same detail (such as a cron schedule in prose vs. `scheduler.py`) and one quietly goes stale.
