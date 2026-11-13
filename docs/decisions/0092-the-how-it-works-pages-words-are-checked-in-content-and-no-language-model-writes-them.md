# 0092 — The "How it works" page's words are checked-in content that a person wrote, and no language model writes or alters any of them

## Decision

Every rule, description, open question and journey on `/al/<slug>/how-it-works/` is YAML under `content/how-it-works/<slug>/`, written and reviewed by a person, read once at application start by `docket.services.how_it_works.load_explainers`, and rendered as written. No model call produces, summarises or rewords any sentence on the page, and a content file that fails validation stops the application from starting.

## Rationale

The obvious alternative is the one the rest of the site uses for prose about items: a model reads the source and writes the plain-language account. For a rule of procedure that is the wrong tool. The page says what the city's code and state law require, and a sentence that is nearly right ("four votes" where the general law says a majority of those elected, a seven-day notice the cited section does not hold) is the site misstating the law beside a link that makes it look sourced, which is what `docs/PRINCIPLES.md` forbids under Source or silence. A summary of an agenda item can be labelled provisional and checked against the item; a rule has no such second reading on the page. Hand-written text in the repository can be reviewed line by line, changes only by a commit, and can be checked mechanically against its source (decision `0094`).

A database table edited through the admin was the other alternative. It would have needed a migration, an editor, and its own review trail, to hold 54 rules and four journeys that change when the city amends its code. The `content/` tree is already deployed with the application and already holds the blog's markdown.

Failing application start on a broken file, rather than serving the page without the broken part, is deliberate: a page that silently drops a rule or a journey reads as "there is no such rule", and the failure is caught by `./tools/verify` before a deploy because the tests load the real content.

The trap is the convenient exception: a model asked to draft "just the descriptions", or to fill a journey's text from the item's summary. Either needs a decision of its own and a label on the page.

## Date

2026-11-12, the operator (the design, `docs/superpowers/specs/2026-11-12-how-it-works-design.md`) and Claude, in plan `how-it-works-explainer` (authored 2026-11-12; built in its M1 and M2).

## Status

accepted
