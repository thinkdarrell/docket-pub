# Decision record format

This file is shipped documentation, not a skeleton: it contains no
placeholder slots and no authoring comments, and it stays in the repository
as-is. Delete it only if this project abandons decision records entirely —
in which case also remove the `docs/decisions/` line from the map in
`AGENTS.md`.

## What this directory owns

Why. One file per durable decision, holding the reasoning that would
otherwise be reconstructed wrongly — or re-litigated — six months later.
Everything else in the docs tree says what is true; these files say why it
was chosen over the alternative that now looks obvious.

It must not absorb current-state description (`ARCHITECTURE.md`,
`docs/specs/`), rules (`docs/PRINCIPLES.md`), or the work that implemented
the decision (`plans/`). A record is written once and then left alone.

The failure this directory exists to prevent is the confident revert: an
agent sees code that looks wrong, cannot find a reason for it, "fixes" it,
and re-creates the failure that the shape was avoiding. A two-paragraph
record is cheaper than that loop, every time.

## When a decision earns a file

It changes something an agent would otherwise get wrong, and it is expected
to outlive the work that produced it. Decisions made inside a plan live in
that plan's Decision Log first; they graduate here when the plan completes
and the decision still binds future work. A choice that only mattered for
one change stays in the plan.

## File naming

`NNNN-short-slug.md`, with `NNNN` a zero-padded sequence number that is
never reused: `0007-single-writer-per-queue.md`. The number gives every
record a stable citation, so a comment or a plan can point at `0007` and
mean this file forever.

## The format

Four fields, in this order, and nothing else. The constraint is deliberate:
a longer format invites a design essay, and a design essay does not get
written, so the decision goes unrecorded.

    # NNNN — <the decision, as a statement>

    ## Decision

    What was decided, in the present tense, as a rule that binds future
    work. One or two sentences.

    ## Rationale

    Why this and not the obvious alternative. Name the alternative and what
    it would have cost. This is the only field where length is justified,
    and it is still no more than a few paragraphs.

    ## Date

    YYYY-MM-DD, and who or what decided.

    ## Status

    One of: accepted, superseded by NNNN, reverted.

## Superseding

Records are append-only. To change a decision, write a new record whose
Rationale names the old one, then edit the old record's Status field to
`superseded by NNNN` and change nothing else about it. Never rewrite a
record's Decision or Rationale — the wrong reasoning, dated and attributed,
is exactly what stops the same mistake recurring.

Append-only governs the reasoning, not the typography. A reference inside a
record that has stopped resolving — a file moved, a path written without its
directory — is repaired in place, because a citation nobody can follow
protects nothing. Such a repair changes the path and not one word of the
argument, and it is not a rewrite.

Reverting is the same operation with Status `reverted` and a new record
explaining what went wrong in practice.
