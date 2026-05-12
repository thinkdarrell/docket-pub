"""Migration 024 — category-landing presentation columns + description audit.

Spec: docs/superpowers/specs/2026-05-12-category-landing-redesign-design.md

Adds three forward-only presentation columns to priority_badge_templates:

- accent_color    — 3px left-edge border color for the Smart Brevity Card
                    in the compact-scan redesign (PR C). Hex string.
- chart_title     — Per-badge override for the volume timeline's centered
                    h2 ("Items the AI flagged as hidden on consent" beats
                    the default "Hidden on consent — items per month").
                    NULL → template's `name` + " — items per month" is the
                    fallback rendered by the template.
- chart_footnote  — Per-badge prose explaining badge-specific peculiarities
                    (e.g. "this badge filters to consent-agenda items by
                    design"). NULL → no footnote rendered.

Also rewrites priority_badge_templates.description for all 11 v1 badges:

- hidden_on_consent: original copy had a singular-noun grammar bug
  ("Item the AI judged should NOT be on consent..."); rewritten to plural
  with em-dash separator for the rhythm: "Items the AI flagged as
  high-public-interest — but council placed them on the consent agenda
  anyway."
- The other 10 are audited for similar issues. Each badge's new copy lives
  inline below with a one-line rationale comment.

Idempotent — IF NOT EXISTS on every column add; UPDATE statements are
keyed to slug so re-applying is a no-op. SQL_DOWN drops the columns; the
description rewrites are not reverted because the original copy was
broken — there's nothing to roll back to that we'd want.

Baked into migration 013's CREATE TABLE for fresh installs (project
convention — see 021/022/023). Seeds stay only here so this file is the
audit trail for the per-badge copy decisions.
"""

from __future__ import annotations


SQL_UP = r"""
-- ---------------------------------------------------------------------
-- Step 1: schema additions
-- ---------------------------------------------------------------------

ALTER TABLE priority_badge_templates
    ADD COLUMN IF NOT EXISTS accent_color    TEXT,
    ADD COLUMN IF NOT EXISTS chart_title     TEXT,
    ADD COLUMN IF NOT EXISTS chart_footnote  TEXT;


-- ---------------------------------------------------------------------
-- Step 2: accent_color — left-edge color cue by badge family.
-- Spec decision #6 table.
-- ---------------------------------------------------------------------

UPDATE priority_badge_templates SET accent_color = '#5a7a99' WHERE slug = 'legal_settlement';        -- cool blue
UPDATE priority_badge_templates SET accent_color = '#c4894a' WHERE slug = 'hidden_on_consent';      -- gold
UPDATE priority_badge_templates SET accent_color = '#c97a3f' WHERE slug = 'sole_source';            -- orange (procurement family)
UPDATE priority_badge_templates SET accent_color = '#c97a3f' WHERE slug = 'amends_prior_contract';
UPDATE priority_badge_templates SET accent_color = '#c97a3f' WHERE slug = 'emergency_action';
UPDATE priority_badge_templates SET accent_color = '#a04545' WHERE slug = 'property_recovery';      -- muted red (property family)
UPDATE priority_badge_templates SET accent_color = '#a04545' WHERE slug = 'blight_accountability';
UPDATE priority_badge_templates SET accent_color = '#7a4a99' WHERE slug = 'split_vote';             -- purple (vote-shape family)
UPDATE priority_badge_templates SET accent_color = '#7a4a99' WHERE slug = 'contested';
UPDATE priority_badge_templates SET accent_color = '#2e7a5a' WHERE slug = 'housing_stability';      -- muted green (policy-priority family)
UPDATE priority_badge_templates SET accent_color = '#2e7a5a' WHERE slug = 'public_safety_tech_privacy';


-- ---------------------------------------------------------------------
-- Step 3: chart_title — verb-led, citizen-facing.
-- Only set where it improves on "<badge name> — items per month".
-- ---------------------------------------------------------------------

UPDATE priority_badge_templates SET chart_title = 'Items the AI flagged as hidden on consent'                WHERE slug = 'hidden_on_consent';
UPDATE priority_badge_templates SET chart_title = 'Sole-source procurements'                                 WHERE slug = 'sole_source';
UPDATE priority_badge_templates SET chart_title = 'Legal settlements approved by council'                    WHERE slug = 'legal_settlement';
UPDATE priority_badge_templates SET chart_title = 'Council votes split along disagreement lines'             WHERE slug = 'split_vote';
UPDATE priority_badge_templates SET chart_title = 'Contested council votes'                                  WHERE slug = 'contested';
UPDATE priority_badge_templates SET chart_title = 'Contract amendments to prior council awards'              WHERE slug = 'amends_prior_contract';
UPDATE priority_badge_templates SET chart_title = 'Emergency-procurement actions'                            WHERE slug = 'emergency_action';
UPDATE priority_badge_templates SET chart_title = 'Property-recovery actions (demolitions, liens, nuisance)' WHERE slug = 'property_recovery';
UPDATE priority_badge_templates SET chart_title = 'Blight accountability — vacant-structure actions'         WHERE slug = 'blight_accountability';
UPDATE priority_badge_templates SET chart_title = 'Housing-stability actions'                                WHERE slug = 'housing_stability';
UPDATE priority_badge_templates SET chart_title = 'Public-safety tech and privacy decisions'                 WHERE slug = 'public_safety_tech_privacy';


-- ---------------------------------------------------------------------
-- Step 4: chart_footnote — only where the predicate has a quirk citizens
-- should know about. Most badges have no footnote (NULL).
-- ---------------------------------------------------------------------

UPDATE priority_badge_templates
SET chart_footnote = 'This badge filters to consent-agenda items by design; bars show consent volume only.'
WHERE slug = 'hidden_on_consent';

UPDATE priority_badge_templates
SET chart_footnote = 'Only roll-call votes are eligible — voice votes don''t expose the dissent shape this badge needs.'
WHERE slug IN ('split_vote', 'contested');


-- ---------------------------------------------------------------------
-- Step 5: description audit — plain-language rewrites for all 11 v1
-- badges. Rationale on the line above each UPDATE.
-- ---------------------------------------------------------------------

-- Singular→plural grammar fix; em-dash beat between setup and punch.
UPDATE priority_badge_templates SET description =
'Items the AI flagged as high-public-interest — but council placed them on the consent agenda anyway.'
WHERE slug = 'hidden_on_consent';

-- "no-bid" added as familiar synonym for procurement-naive readers.
UPDATE priority_badge_templates SET description =
'Contracts awarded without competitive bidding (sole-source or no-bid). The vendor was chosen directly — taxpayers don''t see a price comparison.'
WHERE slug = 'sole_source';

-- Plain-language replacement for "settlement"; flags the discretion lens.
UPDATE priority_badge_templates SET description =
'Council resolutions authorizing the city to settle a lawsuit or claim. Outcome details are often confidential by the settlement terms.'
WHERE slug = 'legal_settlement';

-- "1+ dissent" makes the threshold legible without the spec's `2+` jargon.
UPDATE priority_badge_templates SET description =
'Roll-call votes where one or more councilors voted against the majority. The disagreement might be the story.'
WHERE slug = 'split_vote';

-- Distinct from split_vote — the bar is higher (2+ dissents OR tied vote).
UPDATE priority_badge_templates SET description =
'Roll-call votes with two or more councilors voting against the majority, or a tie. These are where council is most internally divided.'
WHERE slug = 'contested';

-- "Amendment" plus the "more money or more time" framing.
UPDATE priority_badge_templates SET description =
'Amendments to contracts council already approved — usually a request for more money or more time. The cumulative dollar figure can outpace the original award.'
WHERE slug = 'amends_prior_contract';

-- "Emergency procurement" leads with the action, not the legal term.
UPDATE priority_badge_templates SET description =
'Emergency-procurement actions — purchases or repairs the mayor authorized without standard bidding because of an immediate public need.'
WHERE slug = 'emergency_action';

-- "Demolition" / "nuisance" / "lien" — the three concrete actions citizens
-- recognize from neighborhood-watch coverage.
UPDATE priority_badge_templates SET description =
'Council actions on neglected property — demolitions, nuisance findings, and liens against owners for cleanup costs.'
WHERE slug = 'property_recovery';

-- Birmingham-specific; "accountability" frames the citizen lens.
UPDATE priority_badge_templates SET description =
'Birmingham council actions holding owners of vacant or blighted structures accountable for the condition of their property.'
WHERE slug = 'blight_accountability';

-- "Eviction prevention" added as the citizen-facing anchor.
UPDATE priority_badge_templates SET description =
'Council actions affecting tenants, eviction prevention, fair housing, or housing-affordability programs.'
WHERE slug = 'housing_stability';

-- "Surveillance" / "data sharing" make the privacy lens concrete.
UPDATE priority_badge_templates SET description =
'Council decisions on police technology, surveillance, and data-sharing arrangements that affect resident privacy.'
WHERE slug = 'public_safety_tech_privacy';
"""

SQL_DOWN = r"""
-- Drop the three new columns. Description rewrites are not reverted
-- (the original `hidden_on_consent` copy was grammatically broken; the
-- other 10 were either fine or arguably-fine, and rolling them back to
-- pre-audit state has no business value).
ALTER TABLE priority_badge_templates
    DROP COLUMN IF EXISTS accent_color,
    DROP COLUMN IF EXISTS chart_title,
    DROP COLUMN IF EXISTS chart_footnote;
"""
