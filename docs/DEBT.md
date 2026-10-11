# Debt

<!--
GUIDANCE — MARKERS
  {{FILL: ...}} is a slot you must replace with real content.
  Every HTML comment block in this file starts with the word GUIDANCE and is
  an authoring instruction. Delete all of them once the file is filled.

GUIDANCE — WHAT THIS FILE OWNS
  Everything knowingly left undone or left wrong: shortcuts taken on
  purpose, work deferred out of a plan, gaps between `ARCHITECTURE.md` and
  the code, and checks that should exist but do not. One register, so that
  "what is wrong with this project" is a question with an answer.

GUIDANCE — WHAT IT MUST NOT ABSORB
  Bugs nobody chose (use the issue tracker), planned work with a committed
  route (`plans/`), open questions whose answers would change the plan
  (`GOALS.md`, Known unknowns), or a rewrite wish list. Debt is deliberate;
  if it was not a choice, it is not debt.

GUIDANCE — ANTI-PATTERN THIS FILE EXISTS TO PREVENT
  Debt that only exists in the head of whoever incurred it. An agent with a
  fresh context cannot see a shortcut as a shortcut: it reads the code as
  intent, builds on it, and the shortcut becomes load-bearing. A written
  entry with a trigger turns an invisible decay into a scheduled decision.
  The second failure this prevents is the write-only register — entries
  added, never closed, until the file is scenery. Every entry therefore
  carries a trigger, and a triggered entry either gets fixed or gets its
  trigger revised on purpose.

GUIDANCE — WHEN AN ENTRY LEAVES
  Fixed, or reclassified. Closing an entry means deleting its row and its
  detail section; the history is in version control, and a file of
  crossed-out debt costs every future reader the same as live debt.
-->

## Register

<!--
GUIDANCE
  One row per item. IDs are stable and never reused, so a plan or a comment
  can cite `D3` and still mean this thing in a year. "Trigger" is the
  observable event that makes the item worth paying down — a scale
  threshold, a second occurrence, a dependency landing, a rung being
  claimed. An item with no conceivable trigger is not debt; it is a decision
  and belongs in `docs/decisions/`.
-->

| ID | Item | Where | Why deferred | Trigger to pay it down |
| --- | --- | --- | --- | --- |
| {{FILL: D1}} | {{FILL: what is wrong, in a few words}} | {{FILL: path or component}} | {{FILL: the tradeoff that was taken}} | {{FILL: the observable event}} |
| {{FILL: D2}} | {{FILL: what is wrong, in a few words}} | {{FILL: path or component}} | {{FILL: the tradeoff that was taken}} | {{FILL: the observable event}} |

## Details

<!--
GUIDANCE
  A row is an index entry, not a handover. Any item that an agent could not
  pick up cold from its row alone gets a section here: what the current
  state actually is, what "fixed" would mean, and what the person paying it
  down will need to know that is not obvious from the code. Items whose row
  genuinely says everything need no section.
-->

### {{FILL: D1}} — {{FILL: short title}}

{{FILL: current state, what fixed looks like, and the non-obvious context a
fresh reader needs. Name files by repository-relative path.}}
