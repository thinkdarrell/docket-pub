# fast-verify

## Invariant

One command, named under Commands in `AGENTS.md`, runs every check that is
safe to run after any edit. It takes no arguments, needs no network, assumes
no setup beyond the environment command, exits zero on a clean checkout and
nonzero if any check it covers fails, and finishes within a time budget
written down next to it.

The budget is part of the invariant, not a nice-to-have. An agent that cannot
predict what a command costs stops running it, and an unrun check enforces
nothing. Sixty seconds is a reasonable default; whatever number this project
picks is stated in `AGENTS.md` and is what the failing case below measures
against.

This card is the enforcement point named by most other cards in this
directory, which makes one further property part of the invariant: the command
line published in `AGENTS.md` is the command continuous integration runs. If
the two drift apart, every card that claims to be enforced by "the cheap
verification command" is enforced by nothing.

## Enforcement point

Continuous integration runs the documented command on every change, and it is
the command a pre-commit hook runs where the project has one. The
documentation-versus-job identity is checked the cheap way: the job invokes
the documented command by name rather than restating its steps, so there is
only one definition to keep true.

## Acceptance

Passing case: from a fresh clone, run the documented command with no
arguments. It exits zero, prints a one-line summary naming each check that
ran, and the observed wall-clock time is inside the stated budget. Record the
observed time — if it exceeds the budget, the card is not `built`, and either
the budget or the command's contents must change.

Failing case: introduce a violation of any check the command aggregates — the
cheapest is usually a formatting or link error — run the command, and observe
a nonzero exit with the failing check's own remediation text visible in the
output. Revert and observe the command pass. A run that hides the underlying
message and prints only its own summary fails this case.

## Remediation message

    fast-verify: 1 of 4 checks failed.
      boundary-lint: src/core/user.py:12 imports src/adapters/db.py …
    Fix the violations reported above and re-run `<the documented command>`.

fast-verify aggregates, so its own message is a summary and a re-run
instruction; it must never swallow or truncate the remediation text of the
checks it runs. When the project has no such command yet, `AGENTS.md` says so
in the Commands section in those words rather than naming an aspirational
command — a documented command that does not exist is the one failure this
card cannot detect from the inside.

## Per-stack hints

Whatever runner the project already has: `make verify`, `just verify`, an
`npm run verify` script, or `cargo make verify`. `pre-commit run --all-files`
works where hooks are already the convention and gives the aggregation for
free. A repository of markdown artifacts needs only a shell script whose body
is the other cards' checks, run in sequence, with a nonzero exit if any
failed.
