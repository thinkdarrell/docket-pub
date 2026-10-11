# prose-duplication

## Invariant

No run of prose appears in two of this project's markdown artifacts. Stated so
a violation is decidable: normalize each artifact to its sequence of lowercase
alphanumeric words, take every window of eight consecutive words, and require
the window sets of any two artifacts to be disjoint.

The checked set is `AGENTS.md`, every markdown artifact its map names,
everything under `docs/`, and the convention at `plans/PLANS.md`. Two
directories are outside it. Plan files under `plans/active/` and
`plans/completed/` quote convention text, command transcripts, and the
artifacts they change, and that quoting is what makes a plan self-contained.
Records under `docs/decisions/` restate the rule each one installed, and the
append-only rule in `docs/decisions/DECISION_FORMAT.md` forbids replacing a
record's text with a pointer, so every record's copy is historical by
construction.

Eight words is the floor, not a preference. Shorter windows fire on ordinary
English connective phrasing, and a check whose findings are mostly noise is
switched off; longer windows miss a restated one-sentence rule, which is the
duplication that actually goes stale.

Six classes of shared window are legitimate and must not be reported. Five
are decidable; the sixth is a judgement and is carried as an allowlist.

- an attributed restatement — the window's section in the non-owning file
  contains a backticked path to the file that owns the fact, which is what
  `docs/PRINCIPLES.md` requires of a restatement that has to exist;
- files a declared structural correspondence requires to be copies of each
  other. Where `ARCHITECTURE.md` declares such a rule, that rule owns those
  pairs, and comparing them here reports the correspondence as a defect;
- two files whose shape the same format document defines — cards written to
  `docs/capabilities/CARD_FORMAT.md`, records written to
  `docs/decisions/DECISION_FORMAT.md`. Decidable by finding each file's
  sibling `*_FORMAT.md` and skipping the pair when both siblings have the
  same filename, which keeps it working where a project keeps a second copy
  of a format document elsewhere in the tree. Their shared text is the
  format's, not either file's;
- shared boilerplate between two format documents themselves, decidable by
  skipping pairs where both filenames end in `_FORMAT.md`;
- quoted material: indented blocks, fenced blocks, and HTML comment blocks,
  which exist to reproduce a remediation message, a transcript, a skeleton,
  or the authoring guidance a skeleton carries, are stripped before
  windowing. Guidance comments are the case most easily missed: they are
  scaffolding deleted when a file is filled, so two skeletons still carrying
  the same guidance block verbatim are not duplicating each other, and a
  project mid-bootstrap holds several of them at once;
- a window that is a proper noun run, a path list, or a section-name list
  both files must spell out to name the same thing. This is the judgement
  class, carried as an allowlist of exact `fileA:fileB:window` triples, each
  with a one-line reason.

Skipping same-format siblings means duplication between two cards, or between
two records, is not decided here. That is the price of not reporting the
format's own scaffolding on every pair; `docs/capabilities/CARD_FORMAT.md`
states the one-invariant-per-card rule that keeps two cards from covering the
same ground, and it is enforced by review.

What this card deliberately does not decide: which copy is canonical. The
check reports a pair; a reader decides which file owns the fact and which one
gets a pointer instead. That is why no rung in `docs/MATURITY.md` gates on
this card — it removes the searching, not the routing.

## Enforcement point

The cheap verification command named under Commands in `AGENTS.md`, and the
same command in continuous integration. Failure refuses the change: nonzero
exit, no merge.

## Acceptance

Passing case: on a clean checkout the check exits zero and prints one line
stating how many artifacts it compared, how many windows it examined, and how
many allowlist entries it applied. Both counts must be greater than zero — a
glob that matches nothing passes forever.

Failing case: copy one whole sentence out of `docs/PRINCIPLES.md` into
`AGENTS.md`, run the check, and observe a nonzero exit with the remediation
message below naming both files and the shared window. Delete the copied
sentence and observe the check pass again. Do this before marking the card
`built`.

## Remediation message

    prose-duplication: AGENTS.md and docs/PRINCIPLES.md share the window
    "every fact lives in exactly one file and" (14 words shared in total).
    One of the two owns this fact. Delete the copy, leave a reference to the
    owning file, or — if the restatement must exist — name the owning file in
    the same section so it reads as attributed rather than duplicated.

The message names both files, the actual shared text, and the three possible
next actions. "Duplicate content found" fails this bar: the reader has to
re-derive the window the checker already computed.

## Per-stack hints

A script that builds a set of word windows per file and intersects the sets
pairwise is about twenty lines in any scripting language and needs no
dependency; run it as part of the documentation check the project already has.
Where a clone detector is already present for source code — `jscpd`, `pmd
cpd`, `simian` — it can be pointed at the markdown tree instead, provided its
minimum-token setting is lowered to the window size above and its output still
names both files.
