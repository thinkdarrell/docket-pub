# Principles

<!--
GUIDANCE — MARKERS
  {{FILL: ...}} is a slot you must replace with real content.
  Every HTML comment block in this file starts with the word GUIDANCE and is
  an authoring instruction. Delete all of them once the file is filled.

GUIDANCE — WHAT THIS FILE OWNS
  The few rules that override local convenience: statements an agent must
  honor even when the surrounding code, the quickest available fix, or its
  own judgement suggests otherwise. Principles are chosen by this project,
  which is what separates them from the constraints in `GOALS.md` — those
  are imposed from outside and cannot be traded away at all.

GUIDANCE — WHAT IT MUST NOT ABSORB
  Style preferences a formatter already enforces, the reasoning behind one
  specific choice (`docs/decisions/`), dependency direction
  (`ARCHITECTURE.md`), or the mechanics of any automated check
  (`docs/capabilities/`).

GUIDANCE — ANTI-PATTERN THIS FILE EXISTS TO PREVENT
  The principle graveyard: a list so long and so agreeable that no agent can
  hold it in mind and no violation is ever noticed. A principle earns its
  place only if it costs something — only if it forbids a thing a reasonable
  agent would otherwise do. Keep the list under about seven entries; when an
  eighth is proposed, one of the existing seven retires or merges into it.

GUIDANCE — FORM
  Each principle gets a short imperative name, the rule in one sentence, and
  a concrete smell that shows it has been violated. The smell is the part
  that makes the principle usable: it turns a value into something a
  reviewer can point at. A smell that a command could detect is a candidate
  spec card — see `docs/capabilities/`.

GUIDANCE — EXAMPLES
  The three below illustrate the form. They are not inherited rules: adopt,
  rewrite, or ignore them. They disappear with this comment block when the
  file is filled, so nothing here needs a separate deletion pass.

    ## Fix the cause

    The rule: repair the source of a failure, never silence its symptom.
    Violated when: a change adds a catch, a default, or a special case whose
    only purpose is to stop something from reporting that it is broken.

    ## One owner per fact

    The rule: every fact lives in exactly one file, and everywhere else
    links to it.
    Violated when: two files state the same thing and one of them has
    quietly gone out of date.

    ## Evidence or silence

    The rule: claim something works only after observing it work.
    Violated when: a report names the command that would prove a change
    instead of what running that command printed.
-->

## {{FILL: principle name — short and imperative}}

The rule: {{FILL: one sentence stating what must or must not happen}}
Violated when: {{FILL: a concrete smell a reviewer or a check could spot}}

## {{FILL: principle name — short and imperative}}

The rule: {{FILL: one sentence stating what must or must not happen}}
Violated when: {{FILL: a concrete smell a reviewer or a check could spot}}
