# Upcoming-meeting forward-voice AI

**Status:** Design — not yet implemented
**Filed:** 2026-05-18
**Last revised:** 2026-05-18 (incorporates first review pass: meeting-day voice clarification, evidence ordering, search_vector verification, in-process cache audit, deploy ordering, prompt-engineering guardrails)
**Surface:** `src/docket/ai/prompts.py`, `src/docket/ai/rewrite.py`, `src/docket/ai/meeting_summary.py`, `src/docket/worker/tasks.py`, `src/docket/web/templates/meeting_detail.html`, `src/docket/web/templates/partials/_card_shell.html`, plus a new migration.
**Severity:** High for citizen trust. Upcoming-meeting pages currently read in completed-action voice ("the council approved…", "residents can now serve…") for actions that haven't happened and may not happen.

---

## TL;DR

Once PR #65 started ingesting Birmingham agendas the Friday before each Tuesday meeting, every AI surface inherited a Haiku/Sonnet output written in indicative/completed voice — because the existing prompts assume the meeting has happened. The upcoming chip (PR #68) flags the meeting but the body text underneath still reads wrong.

Fix in two layers:

1. **Tactical patch (ships tonight, ahead of meeting 2232 on 2026-05-19):** template-level suppress the AI body on upcoming meetings; fall back to `item.title` (and the raw agenda body where present) and replace the executive summary with a notice + agenda link. Fix the hardcoded consent-calendar blurb.
2. **Proper fix (Option D, ships over the next few days):** fork the Haiku item-rewrite prompt and Sonnet meeting prompt into "upcoming" variants written in forward-looking voice ("the council will consider…", "if approved, the contract would…"). Select at queue time keyed off `meeting.meeting_date >= today`. Persist which voice was used. A new daily cron task re-queues items whose meeting just rolled into the past so the existing completed-action prompt overwrites the same columns.

---

## Symptom

Page: `https://docket.pub/al/birmingham/meetings/2232/` (Birmingham regular meeting scheduled 2026-05-19, ingested 2026-05-15 from the Granicus upcoming table).

Wrong-voice surfaces observed:

- **Meeting hero — Executive Summary** (Sonnet, in `meeting_detail.html`): describes proposed actions as decided actions.
- **Per-item card — headline, why-it-matters, summary** (Haiku, rendered through `partials/_card_shell.html` / `partials/card_smart_brevity.html` / legacy `card_v2_fallback.html`): items written as "can now serve", "residents will be able to", "the council approved".
- **Consent calendar blurb** (hardcoded in `meeting_detail.html` line 252): "Items passed as a group without individual discussion unless pulled by a council member."

Correct-voice surfaces already present (from PR #68):

- Upcoming chip in the hero eyebrow
- Upcoming chip in cross-meeting card meta-lines
- "This meeting hasn't happened yet" branch in `_vote_result_block.html`

---

## Root cause

Two contributing factors:

### 1. Prompts encode a temporal assumption

`ITEM_REWRITE_PROMPT` (v4 in `src/docket/ai/prompts.py`) and `MEETING_PROMPT` both instruct the model to summarize what the council *did*. There is no upcoming variant. Stage 2 rewrite runs on every eligible item the moment Wave 0 + Stage 1 finish, regardless of meeting tense.

### 2. The chip-only fix is not enough

PR #68 added the chip + the Vote Result no-vote branch, but did not touch the AI text columns (`headline`, `why_it_matters`, `executive_summary`, legacy `summary`). The chip says "Upcoming" while the paragraph below it reads as past tense — internally inconsistent and erodes trust more than not showing the text at all.

---

## Design

### Layer 1 — Tactical patch (tonight)

Scope: template-level only. No DB or AI-pipeline change.

**`meeting_detail.html`:**

- Gate the Executive Summary section: when `today is defined and meeting.meeting_date >= today`, replace the body with a static notice — *"This agenda was published by the city. The meeting hasn't happened yet, so no summary of what was decided is available."* — followed by a link to `meeting.agenda_url` when set.
- Gate the consent calendar blurb: when upcoming, render *"Items expected to pass as a group without individual discussion unless pulled by a council member."* (existing text is the past-tense version).

**`partials/_card_shell.html`:**

- When `today is defined and item.meeting_date is not none and item.meeting_date >= today`:
  - Headline `<a>` text falls back to `item.title` (skip `item.headline`).
  - The `card_why_block` renders nothing (skip `item.why_it_matters`).
  - The facts strip is unchanged (numbers/sponsor are tense-neutral).
- This change automatically covers every page that uses the shell (meeting_detail, search, category landing, topic detail) — anywhere an upcoming item appears, the wrong-voice paragraph disappears.

**Legacy v2 fallback (`partials/card_v2_fallback.html`):**

- Same gate: suppress `item.summary` on upcoming items. (Currently only relevant if `ai_rewrite_version < 3`, which is most pre-backfill items — but upcoming items are post-Phase-3 by definition, so this is belt-and-braces.)

**`partials/smart_brevity_card.html`** dispatcher itself: no change. The dispatcher's existing branching is correct — upcoming items will keep flowing into `card_smart_brevity.html` and the shell handles the suppression.

**`item_detail.html`:** apply the same gates so the drill-down page stays consistent.

Tests (template unit tests):
- Upcoming meeting + v3 item → renders title, hides headline/why
- Past meeting + v3 item → unchanged (headline + why visible)
- Upcoming meeting → consent blurb renders "expected to pass"
- Upcoming meeting → exec summary section renders notice, not Sonnet output

### Layer 2 — Forward-voice prompt fork (Option D)

#### Prompt variants

Two new prompt constants, scoped to narrative only (decision 2a — `extracted_facts` stays on the existing Stage 1 prompt):

- `ITEM_REWRITE_PROMPT_UPCOMING` — same schema as `ITEM_REWRITE_PROMPT` (returns `headline`, `why_it_matters`), but rewritten in forward voice. Examples of acceptable phrasings to teach the model:
  - "The council will consider awarding a $1.2M contract to…"
  - "If approved, the resolution would authorize…"
  - "The proposed ordinance would require…"
- `MEETING_PROMPT_UPCOMING` — same schema as `MEETING_PROMPT`, written in forward voice. The distinctive-vs-routine pre-classification stays.

**Prompt-engineering guardrails** (per review): both upcoming prompts must explicitly forbid completed-action verbs — `approved`, `passed`, `enacted`, `adopted`, `awarded`, `authorized` (in the past tense), `decided` — and require conditional/provisional framing (`will consider`, `would authorize`, `if approved`, `proposed`, `scheduled to`). The forbidden-verbs list is part of the prompt text, not a post-processing filter.

Live versioning constants in `prompts.py`:

```python
ITEM_REWRITE_PROMPT_VERSION = 4              # existing (completed voice)
ITEM_REWRITE_PROMPT_UPCOMING_VERSION = 1     # new (forward voice)
MEETING_PROMPT_VERSION = 2                   # existing
MEETING_PROMPT_UPCOMING_VERSION = 1          # new
```

#### Voice column

Add `agenda_items.ai_rewrite_voice text` (NULL by default; values `'completed'` or `'upcoming'`). Add `meetings.executive_summary_voice text` (same shape).

Migration 031 (next available number):
- `ALTER TABLE agenda_items ADD COLUMN ai_rewrite_voice text`
- `ALTER TABLE meetings ADD COLUMN executive_summary_voice text`
- Backfill: `UPDATE agenda_items SET ai_rewrite_voice = 'completed' WHERE ai_rewrite_version IS NOT NULL` (everything already rewritten is in completed voice — the new column is just making that explicit).
- Same for meetings.
- No index needed; the re-cascade query filters on `ai_rewrite_voice = 'upcoming'` AND a `meeting_date < today` join, both of which are cheap at BHM volume.

#### Prompt selection

In `src/docket/ai/rewrite.py`:

- New helper `_select_item_prompt(meeting_date, today) -> (prompt, version, voice)`
- Called at the start of `rewrite_item()`. `today` resolved via `datetime.now(ZoneInfo("America/Chicago")).date()` (same anchoring as the `today` Jinja context processor — see CLAUDE.md timezone note).
- Returns the upcoming variant when `meeting_date >= today`, otherwise the completed variant.
- Persisted: `ai_rewrite_version` and the new `ai_rewrite_voice` both written to the row.

Same shape in `src/docket/ai/meeting_summary.py`.

#### Meeting-day behavior

`meeting_date >= today` keeps the meeting in forward voice for the entire day the meeting happens. This is intentional: "the council will consider…" remains factually accurate while the council is actually in the room. The re-cascade fires the next morning at 04:30 CT, after `meeting_date < today` is true. No "live" or "in-progress" voice variant — two variants is the right number.

#### Re-cascade trigger (sub-decision 1a: date-based daily cron)

New worker task `recast_post_meeting_ai` in `src/docket/worker/tasks.py`. Scheduled around 04:30 CT (well before `ai_items` at 07:00) so the re-queued items get picked up the same morning.

Behavior:

```sql
-- Items whose meeting just rolled into the past AND has evidence of having
-- actually convened (clip_id or minutes_url). Cancelled meetings have neither
-- and are intentionally left in 'upcoming' voice for the follow-up cleanup path.
UPDATE agenda_items
SET processing_status = 'pending',
    ai_rewrite_version = NULL,
    ai_rewrite_voice = NULL
WHERE id IN (
  SELECT ai.id
  FROM agenda_items ai
  JOIN meetings m ON m.id = ai.meeting_id
  WHERE ai.ai_rewrite_voice = 'upcoming'
    AND m.meeting_date < (now() AT TIME ZONE 'America/Chicago')::date
    AND (m.clip_id IS NOT NULL OR m.minutes_url IS NOT NULL)
);

-- Meetings whose date just rolled into the past, same evidence gate.
UPDATE meetings
SET executive_summary = NULL,
    executive_summary_voice = NULL,
    ai_metadata = ai_metadata - 'phase' - 'confidence'
WHERE executive_summary_voice = 'upcoming'
  AND meeting_date < (now() AT TIME ZONE 'America/Chicago')::date
  AND (clip_id IS NOT NULL OR minutes_url IS NOT NULL);
```

The existing `ai_items` and `ai_meetings` tasks pick up the cleared rows and rewrite them with the completed-action prompt, landing `ai_rewrite_voice = 'completed'`.

Healthcheck UUID: `HEALTHCHECK_RECAST_POST_MEETING_UUID` (optional; task gracefully no-ops the ping when unset, matching the existing pattern).

Cost expectation: BHM ships ~5-15 upcoming items per cycle. Re-cascading one regular meeting's worth of items: ~100 items × $0.0026 + 1 meeting × $0.0085 ≈ $0.27. Negligible.

#### Cascade interaction

The existing minutes-adopted cascade (provisional → adopted exec summary) is unaffected — it only fires on `minutes_adopted_at` flips, which by definition only happen for past meetings. After re-cascade lands a 'completed'-voice exec summary, the minutes-adopted promotion later overwrites it again with the adopted-phase Sonnet output. Sequence: `upcoming → completed (provisional) → completed (adopted)`.

#### What happens if a meeting is cancelled

If a scheduled BHM meeting is cancelled, ingest will eventually drop or relabel the meeting row (PR #61's reconciliation path). The re-cascade task fires on `meeting_date < today` AND `ai_rewrite_voice = 'upcoming'`, so a cancelled meeting still in the table would have its items re-rewritten in completed voice — which would read wrong ("the council approved…" for an action never taken).

Mitigation: in the re-cascade SQL, additionally require **meeting-happened evidence**, in this priority order:

1. `clip_id` present on the meeting row (Granicus has assigned a video clip — set when recording starts, the strongest signal that the meeting actually convened);
2. `minutes_url` present (city has published minutes);
3. at least one row in `vote_agenda_items` for the meeting (tertiary signal — presentation-only meetings legitimately have zero votes, so this alone is not sufficient evidence).

Re-cascade fires when (1) OR (2) is true. Cancelled meetings have none of these, so their items stay in upcoming voice indefinitely. A follow-up cleanup path (out of scope here) can handle cancelled-meeting copy explicitly.

#### Search index coverage

Verified: `agenda_items.search_vector` is rebuilt by a DB trigger on INSERT/UPDATE (migration 015) — the trigger reads `title`, `headline`, `why_it_matters`, `summary`, `extracted_facts`, etc. The re-cascade SQL UPDATEs the row to clear, then the AI worker UPDATEs it again with completed-voice text. The trigger fires both times, so the FTS index stays in sync automatically. No separate reindex step needed.

#### In-process cache audit

`src/docket/web/public.py` has two short-lived in-process caches:

- `_overview_cache` (5-min TTL) — city overview/homepage
- `_rss_cache` (60-min TTL per docstring) — RSS feeds (data-debt, upcoming-hearings, etc.)

Meeting detail and item detail are NOT cached — they render straight from the DB. The 5-min city-overview window is acceptable lag for the re-cascade (worst case: 5 minutes of stale forward-voice text after a meeting completes). The 60-min RSS window is also acceptable — RSS feeds are summaries with their own freshness expectations.

No action needed. If we add per-page caching later, the re-cascade task should invalidate the relevant cache keys.

### Tests

Layer 1 (template):
- Upcoming meeting + v3 item: card renders `item.title`, not `item.headline`; no `why` paragraph.
- Past meeting + v3 item: unchanged baseline.
- Upcoming meeting: consent-calendar blurb says "expected to pass".
- Upcoming meeting: exec summary section renders the notice, not the Sonnet text.
- `today` undefined (test-app safety): templates render the past-meeting baseline (no UndefinedError).

Layer 2 (AI pipeline):
- `_select_item_prompt` returns upcoming variant when `meeting_date >= today`, completed otherwise.
- `rewrite_item()` persists `ai_rewrite_voice` matching the prompt used.
- Same for `summarize_meeting()`.
- Re-cascade task picks up only items where `ai_rewrite_voice = 'upcoming'` AND `meeting_date < today` AND meeting has actually-happened evidence.
- Re-cascade task does not touch `is_manual` or other protected columns.
- Live smoke test against Haiku/Sonnet (gated on `ANTHROPIC_API_KEY`, in `tests/live/`) — confirms the upcoming prompt produces forward-voice output on a sample agenda item.

---

## Out of scope

- Cancelled-meeting copy (referenced above; deferred to a follow-up).
- Per-page card variants on search / category landing / topic detail beyond the automatic shell-level fix.
- Rewriting `extracted_facts` for upcoming items (decision 2a — facts are tense-neutral).
- Pre-meeting AI for non-BHM cities. Hoover/Montgomery have no upcoming ingest yet; Mobile/Vestavia (CivicClerk) and Homewood (GenericCMS) don't surface pre-meeting agendas through their adapters today. The forward-voice prompts will fire only when an adapter starts populating upcoming meetings — no city-specific logic needed.

---

## Ship plan

1. **Tonight (Layer 1):** template patch + consent blurb + minimal tests. PR scoped to template-only. Manual verification on `/al/birmingham/meetings/2232/` before merge.
2. **Next few days (Layer 2):** migration 031 + prompt fork + cron task + tests. Live smoke against Haiku. Deploy, watch one BHM cycle end-to-end (upcoming → completed transition) before declaring done.

### Deploy ordering (Layer 2)

The `worker` service start command is `python -m docket.worker.scheduler` — no migration runner (only one process should hold the migration lock; CLAUDE.md). The `docket-web` service start command runs migrations before gunicorn boots.

Order:

1. `git push` → CI green.
2. `railway up --service docket-web --detach` — runs migration 031, then restarts web. New columns exist.
3. `railway up --service worker --detach` — restarts worker with the new prompt-fork code that reads/writes `ai_rewrite_voice`.

If we ship in the reverse order, the worker would attempt to write `ai_rewrite_voice` before the column exists and fail. The two `railway up` calls can be back-to-back; the only invariant is web-before-worker.
