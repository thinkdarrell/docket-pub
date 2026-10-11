# Capability card format

This file is shipped documentation, not a skeleton: it contains no
placeholder slots and no authoring comments, and it stays in the repository
as-is. It defines how the cards beside it are written and what a status
transition requires; `index.md` in this directory records their statuses.

## What this directory owns

The mechanical enforcers this project wants, each specified as one card:
what must always be true, where that gets checked, how to tell the check
works, and what the failure tells the reader to do. Cards specify; they
never contain the implementation.

It must not absorb an invariant's justification (`docs/PRINCIPLES.md` for
chosen rules, `ARCHITECTURE.md` for dependency direction,
`docs/decisions/` for reasoning), the autonomy rung a card gates
(`docs/MATURITY.md`), or the work of building it (`plans/`). A card is a
contract, not a rationale and not a schedule.

The failure this directory exists to prevent is the invariant that lives
only in review comments. Anything important enough to be re-explained by a
human twice is a check that was never written, and every unwritten check is
paid for again on every change. Cards also prevent the opposite failure: a
check built from a vague wish, which passes on everything, fails on nothing,
and is trusted anyway.

## What a card is

A one-page specification for one mechanical check: a command, hook, or
pipeline step that makes a violation of an invariant impossible to merge
unnoticed. Cards are stack-agnostic on purpose — they state the invariant
and the observable acceptance, and leave the mechanism to whoever builds it
in whatever stack this project actually uses.

One invariant per card. A card that enforces two things cannot report a
single actionable failure, and its status cannot be meaningful.

## Naming and status

A card lives at `docs/capabilities/<card-name>.md`, lowercase-hyphenated,
and appears as one row in `docs/capabilities/index.md`.

Status is recorded in the index and nowhere else, so there is exactly one
place to read it and one place to change it. The three values:

- `specced` — the card exists and is complete. Nothing runs yet.
- `built` — the check exists and runs on demand. Promotion to this status
  requires the demonstrated failing case described below.
- `enforced` — the check runs where it cannot be skipped: pre-commit, CI, or
  the project's cheap verification command.

## The promotion bar

A card may not be marked `built` until someone has introduced a change that
violates the invariant, run the check, and observed it fail with the
remediation message visible in the output. A check that has never been seen
to fail is not known to check anything.

Record what was observed — the violating change, the command, and the exact
failure text — in the plan that built it. The card itself stays a
specification and is not edited to hold evidence.

## Sections

Five sections, in this order. The first four are mandatory; `Per-stack
hints` is optional.

    # <card-name>

    ## Invariant

    The property that must always hold, stated so that a violation is
    decidable without judgement. "Imports point inward" is a wish; "nothing
    under src/core may import from src/adapters" is an invariant.

    ## Enforcement point

    Where the check runs and what it blocks: the cheap verification
    command, a pre-commit hook, a CI job, or several. State what happens on
    failure — refusal, or a warning that something else escalates.

    ## Acceptance

    How a builder knows they are done, phrased as observable behavior. Two
    parts, both required: the passing case (on a clean tree the check
    succeeds and says so briefly) and the failing case (a specific
    violating change a builder can actually make, and the failure it must
    produce). The failing case is what gates promotion to `built`, so write
    it as an instruction, not as a description.

    ## Remediation message

    The text the check emits on failure. Mandatory, because a failure
    message is the only documentation an agent reads at the moment it is
    wrong. It must name what was violated, name the specific offender —
    file, line, symbol — and state the next action. "Boundary violation"
    fails this bar; "src/core/user.py:12 imports src/adapters/db.py —
    core may not depend on adapters; move the shared type into src/core or
    invert the dependency" passes it.

    ## Per-stack hints

    Optional. Plausible mechanisms in the ecosystems this project might
    use, as starting points rather than requirements. Omit the section
    entirely rather than leaving it empty.
