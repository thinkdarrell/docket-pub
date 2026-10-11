# boundary-lint

## Invariant

No dependency edge in this repository points in a direction the layer map in
`ARCHITECTURE.md` forbids. `ARCHITECTURE.md` owns which directions are
allowed and why; this card owns only that every edge is checked mechanically
on every change.

An edge is whatever creates a compile-time or run-time dependency in the
languages this project uses: an import, include, require, use, or link
directive. In a repository with no compiled code, an edge is a path reference
from one component's files into another component's files. Either way the
edge set is derived from file content, never from a hand-maintained list of
known dependencies — such a list drifts the moment someone adds an import.

The check must also fail when it cannot find rules to apply. A layer map that
has been renamed, emptied, or written in a shape the checker no longer parses
must produce a loud failure, not a green run over zero rules. A check that
passes on everything is worse than no check, because its green output is
read as evidence.

## Enforcement point

The cheap verification command named under Commands in `AGENTS.md`, and the
same command in continuous integration. Failure refuses the change.

## Acceptance

Passing case: on a clean checkout the check exits zero and prints how many
edges it examined and how many rules from `ARCHITECTURE.md` it applied. Both
numbers must be nonzero.

Failing case: take the strictest rule in the layer map and violate it with
one line — in the component the rule protects, add an import or path
reference naming a file in the component it may not depend on. Run the check
and observe a nonzero exit naming the offending file, line, target, and the
rule violated. Revert the line and observe the check pass. Then, separately,
rename `ARCHITECTURE.md` temporarily and observe the check fail with a
message saying the layer map could not be read, rather than passing.

## Remediation message

    boundary-lint: src/core/user.py:12 imports src/adapters/db.py.
    ARCHITECTURE.md: core may not depend on adapters.
    Move the shared type into core, or invert the dependency — declare the
    interface in core and implement it in adapters. If the rule itself is
    wrong, change ARCHITECTURE.md in this same commit and say why in the
    plan's Decision Log.

The message names the offender by file and line, the forbidden target, and
the rule it broke, then offers the two legitimate fixes and the one
legitimate way to change the rule. "Boundary violation in src/core" fails
this bar: the reader still has to find the import.

## Per-stack hints

Python: `import-linter` with one contract per rule in the layer map. JavaScript
or TypeScript: `dependency-cruiser`, or `eslint-plugin-boundaries` where ESLint
is already configured. Go: `go list -deps` piped through a script, or
`go-arch-lint`. Rust: crate boundaries plus `cargo-deny` for the external
edges. A markdown-only repository needs no tooling at all: for each component
root, grep its files for path references into the roots it may not name.
