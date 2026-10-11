# doc-integrity

## Invariant

Every path reference in this repository's markdown artifacts resolves to a
file or directory that exists. A reference is a repository-relative path
written in backticks or used as a markdown link target. Repository-relative is
what puts a path in the set: an absolute one, starting at the filesystem root
— the scratch directory a constraint tells a tool to write into, say — points
outside the project altogether, so it is dropped where references are
extracted rather than carried as an exception to resolution. The checked set
is `AGENTS.md`, every artifact its map names, everything under `docs/`, and
the plan convention document `plans/PLANS.md`.

Four classes of non-resolving reference are legitimate and must not be
reported:

- a sibling filename cited from inside the directory that owns it, such as
  `CARD_FORMAT.md` named by `docs/capabilities/index.md`;
- an illustrative filename in a format document, such as
  `NNNN-short-slug.md`;
- quoted material: a reference inside a fenced or indented block is a
  transcript, not a citation. A capability card's remediation example names
  the file its own failing case creates, so a card checked as prose reports
  itself;
- a deliberate mention of a file that does not exist or must not exist, such
  as a non-goal naming the artifact this project chose not to have.

The first three classes are decidable — resolve relative to the citing file,
skip files whose own name ends in `_FORMAT.md`, and drop fenced and indented
blocks before extracting references. The fourth is a judgement no checker can
make, so it is carried as an allowlist of exact `path:reference` pairs, each
with a one-line reason. An allowlist entry is cheap to review; a checker that
reports legitimate references is switched off within a week, and then nothing
is checked at all.

Plan files are outside the checked set, in both `plans/active/` and
`plans/completed/`. A plan names the files it will create before they exist
and the files it deleted after they are gone, so a reference walk over plan
files reports a finding per planned artifact and not one of them is a defect.

Two things this card deliberately does not cover. Whether a document's
content is still true — "freshness" — is not decidable from text and stays a
review concern. Whether a plan carries its required sections belongs to
`evidence-check.md` in this directory, because plans have their own structural
contract and their own remediation.

## Enforcement point

The cheap verification command named under Commands in `AGENTS.md`, and the
same command in continuous integration. Failure refuses the change: nonzero
exit, no merge.

## Acceptance

Passing case: on a clean checkout the check exits zero and prints one summary
line stating how many references it resolved and how many allowlist entries it
applied. A run that prints nothing is indistinguishable from a run that
checked nothing.

Failing case: add the line ``- `docs/NOPE.md` — placeholder`` to the map in
`AGENTS.md`, run the check, and observe a nonzero exit with the remediation
message below naming `AGENTS.md`, the line number, and `docs/NOPE.md`. Delete
the line and observe the check pass again. Do this before marking the card
`built`; the count of references resolved must also be greater than zero in
the passing run, or the check is finding nothing to check.

## Remediation message

    doc-integrity: AGENTS.md:47 references `docs/NOPE.md`, which does not
    exist.
    Create the file, correct the path, or — if the mention is deliberate —
    add `AGENTS.md:docs/NOPE.md` to <allowlist path> with a reason.

The message names the citing file and line, the unresolved target, and the
three possible next actions. A message that says only "broken link found"
forces the reader to re-derive everything the checker already knew.

## Per-stack hints

A shell script over `grep -o` for backticked paths plus `test -e` is enough
for a repository of this size and needs no toolchain. Established options
where one is already present: `lychee` or `markdown-link-check` for link
targets, `mdbook-linkcheck` where the docs are built, or the repository's own
documentation test suite. Whichever is used must accept the allowlist and
must check backticked bare paths, not only markdown link syntax — most
references in these artifacts are backticked paths.
