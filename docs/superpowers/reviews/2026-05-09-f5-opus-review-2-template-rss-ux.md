# F5 Review #2 — Template + RSS XML + UX (Opus)

**Commit:** ea3aeed
**Branch:** feat/impact-first-phase-2-track-3
**Reviewer angle:** HTML template + RSS XML + UX + citizen copy + accessibility

## Summary

The XML structure is solid (RSS 2.0 + atom self-link + RFC-822 dates + CDATA-wrapped descriptions all correct) and the citizen-friendly enum translator on the HTML page is a nice touch. **The two things blocking ship are: (1) the mailto link interpolates raw `meeting_title` into a hand-percent-encoded URL, which Birmingham's "Planning & Development Committee" titles will absolutely break; and (2) the RSS description macro leaks the `data_quality=no_text_layer` enum into citizen feeds despite the HTML page explicitly avoiding that jargon.** Plus the new `.data-debt-*` BEM classes have zero CSS rules — the page renders with default `<ul>` bullets and no row separation.

## REQUIRED

- **`data_debt.html` L110, L146 — mailto URL fragments on `&` in titles.** The `mailto:` href interpolates `{{ municipality.slug }}`, `{{ item.id }}`, `{{ item.meeting_title or '' }}`, and `{{ item.meeting_date or '' }}` raw into a partially hand-encoded URL string. Confirmed against local DB: many Birmingham meetings have titles like `"Planning & Development Committee"`, `"City Council & School Board Election Results"`, and `"Regular City Council Meeting: Video Link- https://www.periscope.tv/.../1OdKrgwLOLOGX?"` (a raw `?` and `#` in the title). For any item attached to one of those meetings, the `&` will terminate the `body=` parameter in the mailto, splitting the email into stray parameters; the literal `?` will start a new query string. The neighboring `partials/engagement_strip.html:77` already has the right pattern — `{{ _subject | urlencode }}` and `{{ _body | urlencode }}` plus `&amp;` for the HTML attribute separator. Adopt it. Suggested fix:
  ```jinja
  {%- set _subject = "Data issue - " ~ municipality.slug ~ " item " ~ item.id -%}
  {%- set _body = "Item ID: " ~ item.id ~ "\n\nMeeting: " ~ (item.meeting_title or '') ~ "\nDate: " ~ (item.meeting_date or '') -%}
  <a href="mailto:{{ admin_email }}?subject={{ _subject | urlencode }}&amp;body={{ _body | urlencode }}">
      Report a problem with this item
  </a>
  ```
  Same fix on both branches (high_items L110 and normal_items L146 — copy/paste duplicate, also worth refactoring into a macro).

- **`rss/_macros.xml.j2` L9 — RSS description leaks the `data_quality` enum to citizens.**
  ```jinja
  Source content needs review (data_quality={{ item.data_quality }}).
  ```
  This puts `data_quality=no_text_layer` (or `=no_agenda_text`, `=foreign_language`, etc.) into RSS feed-reader UIs. The HTML template went out of its way to translate these via `friendly_labels` (L24–40). The RSS feed must do the same — citizens reading via NetNewsWire/Feedly see internal enum strings that mean nothing to them. Reuse the same translation table (extract to a shared Python helper or a Jinja macro both surfaces import). Today's BHM/Mobile/Vestavia/Homewood feeds will broadcast these enum values to anyone who subscribes.

- **`data_debt.html` — five new `.data-debt-*` classes have no CSS.** `data-debt-list`, `data-debt-row`, `data-debt-row__title`, `data-debt-row__meta`, `data-debt-row__needs`, `data-debt-row__action`, `data-debt-pager`, `data-debt-loadmore` — verified absent from `styles.css`, `layout.css`, `councilmatic.css`, `tweaks.css`, `mobile.css`, `css/smart_brevity.css`. The page will render as a default `<ul>` with bullet markers and no row separators. The wrapper `.feed` / `.feed-head` / `.feed-title` / `.hero-sub` provide the section chrome but the list itself is unstyled. Either (a) add the BEM rules under `tweaks.css` or a new section in `layout.css`, or (b) reuse the existing `.feed-row` / `.feed-row` family that the rest of the site uses for list items. Either way, this is a citizen-facing visual regression at deploy time, not a stylistic preference.

- **No RSS auto-discovery for `upcoming-hearings.rss` anywhere in HTML.** The data-debt page advertises its own RSS via `<link rel="alternate">` (good), but the upcoming-hearings RSS feed is only linked from the engagement-strip partial (only renders for items where `action_type == 'public_hearing_set' and not public_hearing_date`). Feed-reader auto-discovery should put a `<link rel="alternate" type="application/rss+xml" title="…upcoming hearings" href="…">` in the `<head>` of `city.html` (and arguably `meeting_detail.html`) so a reader pointed at the city page picks up both feeds. Not blocking ship, but the spec §6.9 promises subscription as the primary citizen consumption path.

## SUGGESTED

- **`data_debt.html` L110/L146 — mailto duplication.** The two branches (high/normal) are identical 8-line `<li>` blocks with one constant change (the loop var). Extract a `data_debt_row(item, admin_email)` macro at the top of the file alongside `friendly_label`. Reduces the surface area for the mailto fix above to one site.

- **`_data_debt_admin_email` should respect `app.config["ADMIN_EMAIL"]` instead of hardcoding `"admin@docket.pub"`.** `config.py:25` already loads `ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@docket.pub")` and `web/__init__.py:21` mounts it onto `app.config`. `engagement_strip.html:77` reads `config.ADMIN_EMAIL`. F5's helper at `public.py:435` returns `municipality.get("admin_email") or "admin@docket.pub"` — the literal string bypasses ops' ability to override via env var. Suggested:
  ```python
  from flask import current_app
  return municipality.get("admin_email") or current_app.config.get("ADMIN_EMAIL", "admin@docket.pub")
  ```

- **RSS subject/body for "Report a problem" not visible in RSS feeds.** Citizens reading via RSS only see `<description>` text — they never see the HTML mailto. Consider adding the report-mailto to the RSS `<description>` (CDATA-wrapped HTML link) so subscribers can flag issues without leaving their feed reader. Decision #77 specifically chose mailto-over-queue for this reason.

- **`data_debt.html` L46 — eyebrow says "Data debt".** Citizens won't recognize "data debt" as a term of art (it's an industry phrase). The H1 below ("Items not yet machine-readable") and hero text both communicate fine without it. Either drop the eyebrow or make it the friendlier `Reading gaps` / `Source-document gaps`. The empty-state header on L73 says "All items machine-readable" which is the language to anchor to.

- **`data_debt.html` L92, L128 — `<ul>` semantics.** Using `<ul>` is correct, but the items have a 4-line internal layout (title, meta, needs, action). If those are styled as separate columns/rows, screen-reader announcement will be "list item: link, text, text, link" which is fine — but consider whether the "needs" line (L107/L143) is best rendered as `<p>` inside the `<li>` rather than a `<div>`, so screen readers pause between meta and needs.

- **`rss/_macros.xml.j2` `data_debt_description` — sentence 1 always ends with a period.** L7: `{{ item.municipality_name }}: {{ item.title or item.meeting_title or 'agenda item' }}.` — if `item.title` already ends in a period (often does), the rendered description has `..`. Cosmetic.

- **`data_debt.xml.j2` / `upcoming_hearings.xml.j2` — channel-level `{{ municipality.name }}` is unescaped.** L5/L7. Today's 4 cities (Birmingham, Mobile, Vestavia Hills, Homewood) have no XML-special chars in their names, so this is safe in practice. But the pattern is unsafe — when Hoover, Bessemer, Tuscaloosa, etc. are added, a city named "Tuscaloosa & Northport joint authority" or any other ampersand would break the feed. Add `| e` to all channel-level `municipality.name` substitutions.

- **`<![CDATA[` close-detection in description.** The two CDATA blocks (`data_debt.xml.j2:14`, `upcoming_hearings.xml.j2:14`) wrap macro output. If any item title or meeting_title contains the literal substring `]]>` the CDATA terminates early. Vanishingly unlikely in real Birmingham data but the standard mitigation is `value.replace(']]>', ']]]]><![CDATA[>')` or simpler: don't use CDATA, just escape every text node. Low priority.

- **Test rigor — auto-discovery test (L306–311) is substring-based.** It checks `'rel="alternate"' in body`, `'type="application/rss+xml"' in body`, and `'/al/birmingham/data-debt.rss' in body`. All three would also pass against the body link on L58–62 (the in-page Subscribe `<a rel="alternate" type="application/rss+xml">`), not the head's `<link>` tag. Parse the response with `lxml`/`html.parser` and assert the link is in `<head>`, with all three attrs.

- **Test rigor — RSS validity tests don't assert RFC-822 format on `<lastBuildDate>` or `<pubDate>`.** `test_data_debt_rss_renders_valid_xml` just checks the elements exist, not their content. Add `from email.utils import parsedate_tz; assert parsedate_tz(channel.find('lastBuildDate').text) is not None`. Same for an item's `<pubDate>`.

- **Test rigor — no test asserts URLs in RSS are absolute.** `test_data_debt_rss_renders_valid_xml` could check `channel.find("link").text.startswith("http")` — currently any future regression that drops `_external=True` would silently produce relative URLs that fail in feed readers. Worth one line.

- **Test rigor — `test_data_debt_empty_state_is_citizen_friendly` relies on Vestavia Hills having no data-debt items in the test DB.** Fragile across test data churn. Either explicitly delete any data-debt items from the city before the assertion, or use a uniquely-seeded synthetic city with zero items.

- **Path drift — engagement_strip-style auto-discovery for upcoming-hearings.** No test verifies the renamed `/al/<city>/upcoming-hearings.rss` is reachable by name from any HTML page (only the engagement-strip's contextual subscribe link). Adding `<link rel="alternate" type="application/rss+xml" title="Upcoming hearings" href="…upcoming-hearings.rss">` to `city.html`'s `<head>` would justify the rename.

## NICE-TO-HAVE

- **F5 introduces `block head` for the first time.** Worth confirming in the PR description so future template authors know it's there and reach for it instead of injecting a body-level `<link>` tag.

- **Inline style on L56: `style="margin-top: 0.5rem;"`.** Move to a class like `.hero-sub--subscribe` or just `.hero-sub + .hero-sub { margin-top: 0.5rem; }` in `tweaks.css`.

- **HTML page subscribe link L58-62 has redundant `rel="alternate"` + `type="application/rss+xml"`.** Those attributes are valid but unusual on body-level `<a>`; they're meaningful on `<link>` in `<head>`. Browsers ignore them on `<a>`. Drop them or move to `<head>` only.

- **Spec §6.9 mock-up uses `⚠️ HIGH` framing** with the warning emoji; F5 uses prose `High priority · {N}`. Both fine; the implementation is more accessible (no emoji-as-meaning) but worth a one-liner in the commit message acknowledging the spec divergence so future readers don't think it's a regression.

- **"Other items needing attention" (L125) reads slightly fluffy.** Spec says `NORMAL (124 items)`. Citizen-friendly but neutral could be `Other items waiting for OCR or extraction` or just keep the eyebrow `Standard priority · {N}` and drop the second clause. Minor.

- **`<title>` for both RSS feeds uses an em-dash** (`Birmingham data debt — docket.pub`). Em-dash is fine in UTF-8 RSS and `<![CDATA[]]>`/`| e` paths handle it, but some old readers (NetNewsWire 4 era) garble non-ASCII in `<title>`. Modern readers handle it. Worth knowing.

## Implementer-flagged question responses

1. **Empty-state copy.** Verdict: **good — citizen-friendly and correctly framed.** L77–80 reads "All items in {city}'s record are currently machine-readable. Nothing is waiting on OCR or extraction here. Check back if a recent meeting was added — newly ingested items are checked within a day." That's the data-honesty framing the F2/F3/F4 lens calls for: it doesn't claim the project is incomplete, doesn't expose internal pipeline names, and gives the reader an action ("check back"). The eyebrow says "Status" not "Wave 0" and the H2 is "All items machine-readable" — perfect for the production-likely path. Only nit: paired with a missing CSS layer (REQUIRED above), the "All items machine-readable" h2 may render at default browser size rather than the styled `.feed-title.t-display` because `.feed-title` is styled but the unstyled wrapper `<ul>` doesn't even exist in this branch — so the empty path is actually the *prettiest* path of the three. No copy changes needed.

2. **Mailto fallback to `admin@docket.pub`.** Verdict: **fallback works, but it's wired around the existing `ADMIN_EMAIL` config plumbing.** The link renders correctly today (`mailto:admin@docket.pub?…`) and the test on L320 confirms. But:
   - The literal `"admin@docket.pub"` in `_data_debt_admin_email` (`public.py:435`) bypasses the `ADMIN_EMAIL` env var that `config.py:25` and `web/__init__.py:21` already plumb through. `partials/engagement_strip.html:77` correctly reads `{{ config.ADMIN_EMAIL }}`. F5 should match. (See SUGGESTED above.)
   - The mailto itself is broken under realistic Birmingham data (raw-`&`-in-meeting-title — see REQUIRED #1). Hiding it isn't necessary, but fixing the encoding is.
   - Don't hide it — citizens *expect* a way to flag issues, the mailto-to-the-project-mailbox is the documented decision #77 path, and "admin@docket.pub" is a reasonable production fallback during a beta. Just fix the URL encoding and switch to `current_app.config["ADMIN_EMAIL"]`.

## Out-of-scope observations

The following belong to reviewer #1's scope but were noticed in passing — flagging only:

- `_rss_cached` (`public.py:411`) is module-global state; not torn down between Flask test clients. The fixture at `test_f5_data_debt.py:147` clears `_rss_cache` per test, which works, but a worker restart is the only way to invalidate in production. The TODO comment notes this.
- `list_upcoming_hearings`'s "title contains 'hearing'" heuristic is documented as v1; reviewer #1's territory.
- `_data_debt_admin_email` lookup is in `public.py:429`, not in `services/`; the rest of the F5 code keeps business logic in services and routes thin.
- 60-min cache is implemented via `_rss_cache` dict, not `flask-caching` — intentional, per docstring.
- The `data_debt` route doesn't itself cache (only the RSS feeds cache). HTML `data-debt` page hits the DB on every request — fine at current scale but worth knowing for Wave 0 post-backfill load.
