# css-tokens

## Invariant

Every `var(--name)` written without a fallback in a stylesheet under
`src/docket/web/static/` or a template under `src/docket/web/templates/`
names a custom property that some file in those two trees declares. Stated
so a violation is decidable: collect the declared names by the regular
expression `--[A-Za-z0-9_-]+\s*:` over every `.css` and `.html` file in the
two trees (a rule body, a `<style>` block, and a `style` attribute all
match), collect every fallback-less use by `var\(\s*(--[A-Za-z0-9_-]+)\s*\)`
over the same files, and require every used name to be a declared name.

The lookup is by name across both trees and not per file because
`base.html` loads every sheet into one cascade, and a template may declare
a token inline for a sheet to read (`--accent-color` in a `style`
attribute of `partials/_card_shell.html`, read by `styles.css`). A use that
carries a fallback, `var(--ink-muted, #4a4a4a)`, is passed as written, since
the browser has somewhere to go.

The check exists because the browser does not report this. A `var()` of an
undeclared property with no fallback is not a syntax error: the declaration
becomes invalid at computed-value time and is dropped, so a margin computes
to zero and a colour inherits, and no console, test, or render says so.
`layout.css` read `--space-5` at two rules for as long as the city page
existed with the token declared nowhere, which removed the space above
every section heading, and `--ink-1` stands in the same state at
`.back-link:hover` and `.coverage-tab.is-active`.

What this card does not decide: whether a token's value is right, whether
the declaring rule is in scope at the point of use (a token declared on
`.foo` and read on `.bar` resolves only inside `.foo`), or whether a
fallback matches the design.

## Enforcement point

The cheap verification command named under Commands in `AGENTS.md`, as one
more `check` line, and so the same command in continuous integration.
Failure refuses the change: nonzero exit, no merge.

## Acceptance

Passing case: on a tree whose fallback-less uses are all declared, the check
exits zero and prints one line saying how many files it read, how many
declared names it found, and how many uses it checked; each count is
greater than zero, so a glob that matches nothing cannot pass. Building the
card therefore begins by declaring `--ink-1`, giving its two uses a
fallback, or changing them to a declared token, because the check must
fail on the tree as it stands.

Failing case: in `src/docket/web/static/layout.css` change one
`var(--ink-3)` to `var(--ink-9)`, run the check, and observe a nonzero exit
with the remediation message below naming that file, that line, and
`--ink-9`. Revert the line and observe the check pass again. Do this before
marking the card `built`.

## Remediation message

    css-tokens: src/docket/web/static/layout.css:1210 reads var(--ink-1)
    with no fallback, and no stylesheet under src/docket/web/static/ or
    template under src/docket/web/templates/ declares --ink-1, so the
    browser drops the declaration silently. Declare the token beside the
    --ink-* scale in src/docket/web/static/styles.css, use a declared
    token, or give the var() a fallback value.

## Per-stack hints

Two regular expressions over the files with `pathlib` and `re` from the
standard library, in a script under `tools/` of the shape `tools/check-plans`
has, about thirty lines. A declaration inside a Jinja expression
(`--topic-color: {{ topic.color }}`) still matches the declaration pattern,
which is the behaviour wanted.
