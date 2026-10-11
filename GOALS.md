# Goals

## Purpose

docket.pub ingests, parses, and indexes the public meeting records of Alabama municipalities and publishes them as a searchable site. A resident can find what their council voted on, who sponsored it, what it cost, and read the city's own document that says so. Every fact on the site links back to that source document. The project is in a private development phase: the site is live at https://docket.pub but has not been announced.

## Outcomes

- A resident can open any Birmingham City Council meeting back to 2005 and see its agenda items, the vote of each member, the dollar amounts involved, and a link to the official minutes or the video.
- A reader can search across cities and land on an item page whose headline and "why it matters" text trace to the source text, with the AI prompt version and generation time stored beside them.
- A journalist can subscribe to editorial coverage by RSS and cite docket.pub item and meeting pages as stable permalinks.
- New meetings, votes, summaries, and video OCR appear within a day of the city publishing them without an operator touching anything.

## Success conditions

- Every citizen-facing data point renders a source badge and a link that resolves to the city's own document.
- Facts derived from video OCR and facts from official minutes are labelled distinctly everywhere they appear, and a disagreement between them is shown as a disagreement.
- Every scheduled worker task pings its Healthchecks.io check on schedule; a missed ping pages the operator.
- The published verify command in `AGENTS.md` passes on `main`.
- Daily AI spend stays under `AI_DAILY_BUDGET_USD`; the admin dashboard at `/admin/ai` shows it.
- No AI-generated sentence is shown without its prompt version and generated-at timestamp stored on the same row.

## Scope

Alabama municipalities whose meeting platforms the adapters support: Granicus (Birmingham), CivicClerk (Vestavia Hills, Mobile), generic HTML archives (Homewood), and CivicPlus (adapter exists, no city yet produces data). Birmingham is the deep case and the only city with votes, video OCR, and transcripts. One operator runs the project.

The repository is the project's only memory. Multi-file or multi-session work runs under a plan in `plans/active/` following `plans/PLANS.md`. Design specs and plans written before this convention arrived live under `docs/superpowers/` and are history, not current behaviour.

The agent harness artifacts and the procedures under `skills/` come from the harness blueprint at https://github.com/bholzer/factory-loop, checked out at /Users/darrellnance/projects/factory-loop; the adopter guide is https://github.com/bholzer/factory-loop/blob/main/docs/guide/adopting.md.

Related repositories: `thinkdarrell/al-municipal-meetings` is the original Birmingham scraper and remains a research sandbox; `thinkdarrell/docket-pub-site` is the separate landing page; `thinkdarrell/docket-pub-archived` is a read-only pre-consolidation skeleton.

## Non-goals

- A public REST API: deferred until public launch because of the security surface it opens; the security checklist in `docs/SECURITY_CHECKLIST.md` gates launch.
- Replacing Flask and HTMX with a JavaScript frontend such as Astro: the current stack renders everything the outcomes need; re-evaluate only if a concrete rendering limit appears.
- Coverage outside Alabama: depth in one state's records is the product.
- Editorial opinion beyond what the records support: summaries describe what the body did; the editorial coverage feature cites outside journalism rather than writing it.
- Absorbing `al-municipal-meetings` into this repository: the video OCR pipeline was ported in 2026-05; the rest stays a sandbox.
- Running our own language models: summaries use the Anthropic API behind a daily budget cap.
- Autonomous choice of what to build next: the operator states goals; the factory plans and executes them.
- Deploying from inside any automated loop: a human deploys from `main` after a pull request merges.

## Constraints

- The production Postgres volume on Railway is small (1 GB). Per-row bulk updates across tens of thousands of rows overflow its write-ahead log and have crashed the database; bulk changes use one targeted SQL statement.
- The Railway worker idles near 954 MB; an OCR scan adds roughly 750 MB. Nothing may spawn a second heavy Python process on the worker.
- Daily AI spend is capped by `AI_DAILY_BUDGET_USD` and every batch respects it.
- Scraping city sites uses polite delays of at least one second between requests.
- `railway up` deploys whatever is in the local working tree, so deploys happen only from a clean `main` after merge, through `scripts/deploy.sh`.
- Local Postgres is version 16; Railway runs 18.3. Dumps and restores against Railway use the postgresql@18 binaries.
- Commits in this repository use the `hello@docket.pub` identity and the `thinkdarrell` GitHub account.
- New Anthropic API call sites mirror the tool-use pattern in `src/docket/ai/client.py` and are smoke-tested live before they ship.

## Known unknowns

- Will Hoover (CivicPlus) or Montgomery ever publish data the adapters can read?
- Can the 89 percent of minutes votes with no linked agenda item be linked without a language-model fallback, or is that the floor?
- Does a factory workflow run survive a multi-hour plan without being cut off? The first real plan measures this.
- What does public launch require beyond `docs/SECURITY_CHECKLIST.md`, and when?
- Is a two-to-four-minute venv build per worktree acceptable at the start of every plan?
