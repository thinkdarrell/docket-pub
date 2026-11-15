# 0101 — The meeting page prints a committee item's body as the minutes give it

## Decision

Under "What the minutes say" an item's body is printed unaltered. It is left out only when it is empty or is nothing but the item's name again. No rule trims the call to order from a meeting's first item, or the repeated first line from an item named by it.

## Rationale

The parser's items are everything between one action and the next, so the first item of every minutes opens with "The Meeting was called to order ..." and a licence application's body begins with its own name. Both look like defects on the page, and a rule to trim them is easy to write.

The page's claim is that these are the minutes' words, linked to the PDF they came from. A trimmed body differs from the document it cites, and a wrong trim is silent: nobody sees the line that was removed. An untidy first line is visible and harmless. If the reading itself is to change (the call to order belonging to no item), that is a change to `parse_minutes_items` with a fixture test and a raised `PARSER_VERSION`, not a template filter.

## Date

2026-11-15, the M5 session, in plan `committee-documents`.

## Status

accepted
