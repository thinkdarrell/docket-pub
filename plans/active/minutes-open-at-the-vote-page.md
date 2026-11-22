# Open the minutes at the vote's page, on docket.pub

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

A vote that docket.pub read from a city's minutes says which page of the minutes it is printed on, and links there: "Minutes, page 5" on the meeting page, "Read minutes, page 5" on the item page. Today that link is the city's own file address with `#page=5` on the end. For Mobile, the only city whose votes carry a page, the city's system answers every file request with a header that tells the browser to save the file, so the link does not open anything. The operator saw it on 2026-11-22 and wrote it on debt row `D188`: on https://docket.pub/al/mobile/, meeting of 2026-11-03, clicking "Minutes, page 5" on the vote on resolution 40-948-2026 downloaded the PDF in the Windows browser on a desk, and a phone tried to download it too. Neither opened at page 5.

After this work the same link opens a page on docket.pub that shows page 5 of the minutes, in the browser, on a desk and at phone width, with nothing downloaded. The page names the page number, always shows a visible link to the city's own file (the same address the link points at today), and has links to the page before and the page after. The route is keyed on the meeting and the page number, not on Mobile: any city whose vote has a page and whose meeting has a minutes address on the allowlist gets the viewer link, and a vote with no page keeps the link it has now. No copy of the city's PDF is kept: no migration, no table, no file on disk. The file is fetched from the city when a reader asks, held in the web process's memory for at most an hour, and drawn as a picture of the one page.

How to see it working. In the repository: new tests fail before the work and pass after it, showing that the vote's link on the meeting and item pages is a docket.pub viewer address carrying the page; that the viewer's answer for a seeded meeting, with the city's fetch faked, is 200, is shown inline (no `Content-Disposition` header), and contains the city's own file address as a link; that a page out of range, a meeting with no minutes link, a hidden meeting, or an address outside the allowlist is a 404; and that the viewer fetches only the address stored on the meeting, never one taken from the request. `./tools/verify` passes. The final acceptance is the operator's, after the pull request merges and the web service is deployed, in the Windows browser and on a phone, because no factory session has a browser: click "Minutes, page 5" on that vote and see page 5.

## Progress

- [ ] M1: three modules that no page uses yet fetch one PDF from a city under a time and size bound in one attempt (`docket.adapters.source_file`), draw one page of a PDF as a PNG in memory (`docket.analysis.pdf_page`), and hand a page of a stored minutes address to a caller from a small in-memory cache with a one-second gap between requests to one host (`docket.services.minutes_viewer`); `pypdfium2` and `pillow` are named in `requirements.txt`; their unit tests pass and `./tools/verify` passes
- [ ] M2: `GET /al/<slug>/meetings/<id>/minutes/page/<n>/` shows page n of the meeting's minutes inline on a docket.pub page with a visible link to the city's own file and links to the pages before and after, answers 404 for a page out of range, a meeting with no minutes link, a hidden meeting or an address outside the allowlist, shows the city's link alone when the file cannot be fetched, and is kept from crawlers by `robots.txt` and a `noindex` header; its web tests pass with the city's fetch faked and `./tools/verify` passes
- [ ] M3: the meeting page's "Minutes, page <n>" link and the item page's "Read minutes, page <n>" link open the viewer page in place of the city's file address, for any vote with a page on a meeting whose minutes address is a safe one; a vote with no page keeps the link it has; the web tests pass and `./tools/verify` passes
- [ ] M4: the close: the specs (`docs/specs/votes.md`, `civicclerk-ingest.md`, `crawlers.md`, `operations.md`, `index.md`), `ARCHITECTURE.md` and `docs/SECURITY_CHECKLIST.md` describe the viewer as built, the decision that supersedes `0128` is graduated to `docs/decisions/`, and `docs/DEBT.md` has the `D188` row rewritten as the operator's steps after the merge, the `D192` row saying its trigger fired and why it stays, and a row for each thing M1 to M3 deferred; `./tools/verify` passes

## Surprises & Discoveries

As authored on 2026-11-22, nothing has been executed, so no milestone has an observation here yet. What the author observed while researching is below; each is the author's, from the worktree at `4a8ad25` or from one request to the city.

- Observation (authoring): Mobile's file endpoint forbids framing as well as forcing a download, so no design that embeds the city's own address in a docket.pub page can work.
  Evidence: `curl -s -o <scratch file> -D - 'https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3854,plainText=false)'`, run once at 23:28Z on 2026-11-22, printed `HTTP/2 200`, `content-type: application/pdf`, `content-length: 693774`, `x-frame-options: DENY`, `content-disposition: attachment; filename=3854.pdf; filename*=UTF-8''3854.pdf`, and curl's timing line read `connect=0.060748s firstbyte=0.297054s total=0.372249s`. This was from the development machine (WSL); from Railway nobody has timed it.

- Observation (authoring): drawing one page of that file with the PDF library already installed takes well under a tenth of a second and little memory.
  Evidence: a scratch script (not committed) opened the 693,774-byte file with `pypdfium2.PdfDocument(bytes)`, and for pages 1, 5 and 38 called `page.render(scale=1200 / page.get_size()[0]).to_pil()` and saved a PNG to memory. It printed `pages 38 open_s 0.0`, then for page 5 `pts 612 1008 px (1200, 1977) RGB render+png_s 0.078 ... rgb_png 479644` (pages 1 and 38: 0.08 s and 339,541 bytes; 0.065 s and 386,725 bytes), and `maxrss_mb 54` for the whole process. A body that is not a PDF raised `pypdfium2._helpers.misc.PdfiumError: Failed to load document (PDFium: Data format error).`

- Observation (authoring): the repository already holds a small real PDF the tests can use as the city's answer, and it has four pages.
  Evidence: the same script on `tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf` (217,180 bytes) printed `pages 4` and for page 1 `pts 612 792 px (1200, 1553) RGB`; asking for a fifth page raised `PdfiumError: Failed to load page.`

- Observation (authoring): the test command this plan gives runs in this worktree, and the two existing files it will change pass today.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_mobile_minutes_votes.py tests/web/test_crawlers.py -q -p no:cacheprovider` printed `48 passed, 1 warning in 3.82s`; `tools/test-db --drop` then removed the database.

## Decision Log

- Decision: the viewer is a server-drawn picture of one page inside an ordinary docket.pub page, with no JavaScript PDF library and no pass-through of the PDF.
  Rationale: the scope brief settled this default and the author's measurements support it. A pass-through of the PDF with an inline header would open the file in a desk browser, but phone browsers do not honour `#page=`, so it would not open at the page on a phone. Framing the city's address is forbidden by the city's `x-frame-options: DENY`. A vendored pdf.js would be the repository's first vendored JavaScript library and still needs a pass-through of the file. `pypdfium2` 5.8.0 and `pillow` 12.2.0 are already pinned in `requirements.lock` (through `pdfplumber`), and one page draws in under 0.1 s. A picture works the same on a desk and on a phone.
  Date/Author: 2026-11-22, authoring (Claude), from the scope brief.

- Decision: the picture is put into the page itself as a `data:image/png;base64,` address, in the one response. There is no second route that serves the image.
  Rationale: one request from the reader is one code path and at most one request to the city. With a separate image route, the page and its image can be answered by two web processes, each with its own in-memory cache, which doubles the requests to the city. A page of about 340 to 480 kB of PNG is about 450 to 640 kB of HTML, which is acceptable for a page a reader opens deliberately. The repository sends no Content-Security-Policy header, so nothing blocks a `data:` image.
  Date/Author: 2026-11-22, authoring (Claude).

- Decision: "stores no copy of the PDF on the volume" is read as nothing persisted in Postgres or on disk. A bounded in-memory cache in each web process is allowed: at most 4 files and 40 MB, each kept at most one hour.
  Rationale: the scope brief's reading. The cache is what keeps reader traffic polite to the city: moving from page 5 to page 6 of the same minutes sends the city nothing. An hour bounds how stale a page can be if the city replaces a file.
  Date/Author: 2026-11-22, authoring (Claude), from the scope brief.

- Decision: a reader-triggered fetch is one attempt, with 5 seconds to connect, 10 seconds between bytes, 20 seconds in all, a 25 MB cap, no redirects followed, and `https` only. Requests to one host from one web process are at least one second apart, and a failed fetch is remembered for 60 seconds so that it is not repeated.
  Rationale: `GOALS.md` Constraints asks for at least one second between requests to a city. The `Dockerfile` starts gunicorn with its defaults (one synchronous worker and a 30-second timeout); the `Procfile` says `--timeout 120`; which one Railway runs is not written anywhere the author could read, so the bound is made to fit the smaller: one second of waiting plus 20 seconds of fetching is under 30. `CivicClerkAdapter.fetch_file` was not reused because it tries three times with a 30-second read limit and no size cap, which can exceed two minutes and hold the one worker. Not following redirects keeps the fetch on the address the allowlist passed. The one file measured is 0.7 MB; 25 MB is a guard, not an estimate.
  Date/Author: 2026-11-22, authoring (Claude).

- Decision: the fetch lives in a new city-neutral module in the adapter layer, `src/docket/adapters/source_file.py`, not in `CivicClerkAdapter`.
  Rationale: the goal asks for a viewer any city can use. A method on one vendor's adapter would make the viewer work only for that vendor. `ARCHITECTURE.md` says services do not talk to a vendor site directly and adapters own fetching; the adapter directory already holds read-only clients outside the adapter protocol (`city_calendar.py`, `youtube.py`, `committee_documents.py`). Which hosts may be fetched is decided before the service is called, by the allowlist the web layer already owns (`docket.web.source_security.is_url_safe`), which a service may not import.
  Date/Author: 2026-11-22, authoring (Claude).

- Decision: the web route reads the meeting through `docket.services.query` (as the meeting page does), checks the stored `minutes_url` against the allowlist, and passes that stored address to the service. The service has no SQL and takes no address from the request.
  Rationale: the route executes no SQL (the web rule in `ARCHITECTURE.md`; debt row `D7` lists the modules that break it and this plan must not add one). An address that came from the database row cannot be chosen by a visitor.
  Date/Author: 2026-11-22, authoring (Claude).

- Decision: a page below 1 or above 2,000 is a 404 before anything is fetched. A page above the file's real last page is a 404 after the file has been fetched (or found in the cache), because the page count is only in the file.
  Rationale: the scope brief asked that a page out of range be a 404 that sends no request. The file's length cannot be known without the file, and storing page counts would be a schema change for a viewer the goal calls simple. The brief allowed the plan author to refine; this is the refinement. 2,000 is far above the 38 pages of the one file measured.
  Date/Author: 2026-11-22, authoring (Claude).

- Decision: when the city's file cannot be fetched or read, the viewer answers 200 with a page that says so and shows the link to the city's own file with the page number, and `Cache-Control: no-store`. It does not answer 502 or 503.
  Rationale: the reader is then no worse off than today: they get the city's link and the page number. The site sits behind Cloudflare's proxy (`docs/specs/operations.md`, Domain and headers), and the author has not observed what Cloudflare shows a visitor when the origin answers 502; a 200 with the city's link cannot be replaced by an edge error page. The viewer is not indexed, so the status does not mislead a crawler.
  Date/Author: 2026-11-22, authoring (Claude).

- Decision: the link to the viewer opens in the same tab, with `rel="nofollow"` and without the "↗" mark; the link to the city's file on the viewer page keeps `target="_blank" rel="noreferrer"` and the "↗".
  Rationale: decision `0128` opened a new tab so the meeting page stayed on screen when the browser downloaded the file. The viewer is a docket.pub page with a link back to the meeting, so an ordinary link is right. "↗" marks a link that leaves the site everywhere else on these pages.
  Date/Author: 2026-11-22, authoring (Claude).

- Decision: `pypdfium2` and `pillow` are added to `requirements.txt`, and `requirements.lock` is edited by hand to add `-r requirements.txt` to the "via" comments of those two packages, with every pinned version left as it is. The lock is not regenerated.
  Rationale: code that imports a package should name it (`requirements.txt` calls itself the source of truth for runtime dependencies). Regenerating with `uv pip compile` needs the package index, which a milestone session may not reach, and would move unrelated pins. The hand edit changes comments only.
  Date/Author: 2026-11-22, authoring (Claude).

- Decision: debt row `D192` is not paid by this plan although M3 changes the file its trigger names; M4 writes on the row that the trigger fired and why it stays.
  Rationale: `D192` is two older minutes links in `partials/_vote_result_block.html` printed without the allowlist check. Paying it changes what Birmingham's and other cities' item pages print for a meeting whose minutes host is not on the allowlist, which needs a read of production's hosts that no factory session can make. This plan does not change either of those two links.
  Date/Author: 2026-11-22, authoring (Claude).

## Outcomes & Retrospective

As authored on 2026-11-22, nothing has been executed and there is no outcome to report. The closing milestone (M4) writes here what was built against the Purpose above; the retrospective and the move of this file to `plans/completed/` belong to the retro stage that runs after the last milestone, not to any milestone.

## Context and Orientation

### The repository, for a reader new to it

docket.pub is a Python 3.10 application: a Flask web app (`src/docket/web/`), a scheduled worker, and command-line scripts, sharing one PostgreSQL database. The code is layered and the layers are enforced by convention (`ARCHITECTURE.md`): web routes call services (`src/docket/services/`), which own every database transaction; services call adapters (`src/docket/adapters/`, the only code that talks to a city's website), analysis (`src/docket/analysis/`, which turns documents into facts), and others; nothing under `src/docket/web/` may execute SQL, and nothing under `adapters/` or `analysis/` may import from `services/` or `web/`. `docs/PRINCIPLES.md` holds six rules; the one that matters most here is Source or silence: every fact shown to a reader links to the city's own document.

The one check command is `./tools/verify`, run from the worktree root with the worktree's own `venv/`. It builds a throwaway database, runs every non-live test tier and five other checks, prints one `verify: <check> ... ok (<seconds>s)` line per check and a last line `verify: all 6 checks passed in <seconds>s.`, and exits 0 only when all passed. `AGENTS.md` says about 150 seconds; the last plan's sessions on this machine recorded about 300. Never run bare `pytest`: `tests/conftest.py` refuses any database not named `docket_test_*`. To run chosen test files, build the throwaway database inline, as in Concrete Steps.

### What exists today

A vote row (`votes` table; dataclass `Vote` in `src/docket/models/vote.py`) written by a minutes reader has `minutes_reader` set (`mobile` is the only reader) and `source_page`, the 1-based page of the minutes PDF on which the vote's `Ayes:` line is printed. A meeting row (`meetings`; `docket.models` `Meeting`, read by `query.get_meeting(meeting_id)` in `src/docket/services/query.py`) has `minutes_url`, the city's own address of the minutes file, or NULL. For Mobile that address has the form `https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3854,plainText=false)`.

`page_link(url, page)` in `src/docket/models/vote.py` returns the address with any fragment removed and `#page=<page>` added, or None unless both are given. It has two callers, both in `src/docket/services/query.py`: `list_votes` (line 592 as authored), which sets `Vote.minutes_page_url` for the meeting page, and the item page's vote reader (line 4232), which sets `minutes_page_url` beside `minutes_url`, `source_page`, `meeting_id` and `vote_id` on the record the item page prints. Both stay as they are: `minutes_page_url` remains the city's address at the page, and this plan uses it for the allowlist check and for the link to the city's file.

Two templates print `minutes_page_url`, and no other template or route does (`git grep -n minutes_page_url -- src` lists only these, `query.py` and `vote.py`):

`src/docket/web/templates/meeting_detail.html`, lines 285 to 294 as authored. A comment says the city serves the file as a download, then:

    {% if is_source_url_safe(vote.minutes_page_url) %}
    <div>
        <a class="link t-meta" href="{{ vote.minutes_page_url }}" target="_blank" rel="noreferrer">Minutes, page {{ vote.source_page }} ↗</a>
    </div>
    {% endif %}

`src/docket/web/templates/partials/_vote_result_block.html`, the macro `vote_source_link(v)`, lines 33 to 59. Its second branch is the page link:

    {%- elif is_source_url_safe(v.minutes_page_url) -%}
      <a class="link t-meta"
         href="{{ v.minutes_page_url }}"
         data-item-id="{{ item.id }}"
         target="_blank" rel="noreferrer">
        Read minutes, page {{ v.source_page }} ↗
      </a>

Its third branch (`v.minutes_url and not v.minutes_page_url`, "Read minutes ↗") and the "View full minutes ↗" link at line 134 print `minutes_url` with no allowlist check; those two are debt row `D192` and this plan does not change them. The member page prints no minutes link. The meeting page's rail also has an "Official minutes" link to `meeting.minutes_url` (line 456); this plan does not change it.

`is_source_url_safe` is the Jinja name of `is_url_safe` in `src/docket/web/source_security.py`: true only for an `http` or `https` address whose host is, or is a subdomain of, a domain on a closed list (a static set that includes `civicclerk.com` and `granicus.com`, plus each active city's `adapter_config` `base_url` host). It returns False for None.

The meeting page's route is `meeting_detail(slug, meeting_id)` in `src/docket/web/public.py` (line 232). Its first lines are the 404 rule every meeting-scoped route repeats, and the transcript route below it (`meeting_transcript`, line 312) is the nearest model for a second page under a meeting:

    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)
    meeting = query.get_meeting(meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)
    if meeting.is_hidden and not session.get("admin_user"):
        abort(404)

`src/docket/web/templates/transcript.html` is the model for the template: it extends `base.html`, fills `{% block title %}` and `{% block content %}`, opens with `<section class="hero hero--detail">` holding a `t-eyebrow` line, an `<h1 class="hero-title t-display">` with `meeting_label(meeting) or meeting.title`, and a `t-meta` paragraph with `← Back to the meeting`. `base.html` also has an empty `{% block head %}` inside `<head>`, a viewport meta tag, and loads `layout.css` (desk) and `mobile.css` (rules under 768 pixels).

Crawlers: `src/docket/web/crawlers.py` builds `/robots.txt` from `_ROBOTS_GENERAL` (the `User-agent: *` group: `Allow: /`, then `Disallow: /admin/`, `/search`, `/*?`) and a second group that disallows the whole site to named AI crawlers. The blog's routes set `X-Robots-Tag: noindex` on every response (`src/docket/web/blog.py`); that is the precedent for a header on one family of routes. There is no application rate limit and no Content-Security-Policy header.

Fetching: `CivicClerkAdapter` in `src/docket/adapters/civicclerk.py` has `fetch_file(url)`, used by ingest to read minutes files: three attempts, 10 seconds to connect and 30 to read, the whole body in memory, refused unless the address is under the adapter's own base. `src/docket/ai/transcripts/minutes.py` `download_minutes` is an existing example of a streamed download with a size cap. Neither is used by this plan; both are left alone.

PDF libraries: `requirements.lock` pins `pdfplumber==0.11.9`, `pypdfium2==5.8.0` ("via pdfplumber") and `pillow==12.2.0` ("via pdfplumber, pytesseract"). `requirements.txt` names `pdfplumber` only. The `Dockerfile` installs from `requirements.lock`. `venv/bin/python -c "import pypdfium2, PIL; print(pypdfium2.PYPDFIUM_INFO, PIL.__version__)"` printed `5.8.0 12.2.0` in this worktree. Whether the library's bundled binary loads in the production image has been seen by nobody; the design degrades to the city's link if it does not.

### Terms this plan uses

The viewer, or the viewer page: the new page at `/al/<slug>/meetings/<id>/minutes/page/<n>/`. The city's file: the PDF at `meetings.minutes_url`. The allowlist: the closed list of hosts `is_url_safe` accepts. The unavailable state: the viewer page when the city's file could not be fetched or read, which shows the city's link and no picture. A reader vote: a vote row with `minutes_reader` set.

### The states the viewer page must answer for

The viewer writes a sentence about a meeting's minutes ("Minutes, page 5 of 38"), so each state of the row and of the request is decided here. A slug that is not an active city, a meeting that does not exist or belongs to another city, and a hidden meeting seen by anyone but a signed-in admin are 404, by the same lines as the meeting page. A meeting whose `minutes_url` is NULL or empty (an upcoming meeting, a cancelled one, one whose minutes are not posted) is 404. A `minutes_url` that fails `is_url_safe` is 404. A page below 1 or above 2,000 is 404. None of those sends the city a request. A page above the file's last page is 404 once the file is in hand. A file that cannot be fetched (the city is down, slow, answers an error or a redirect, the body is over 25 MB, the address is not `https`) or cannot be read as a PDF gives the unavailable state. A file the city replaced after ingest read it is shown as it is now, at most an hour stale; the page says it is the city's file as docket.pub fetched it and makes no claim about a vote. Any query string on the request is ignored.

### Debt rows this plan accounts for

`D188` (the link downloads instead of opening at the page) is the row this plan pays. Its trigger has fired: the operator's observation is on the row, and the operator chose the viewer by stating this plan's goal. The row cannot be deleted by a milestone, because the proof is the operator's look after deploy; M4 rewrites it in place, under the same id, as the operator's ordered steps with "the pull request merges" as its trigger, and the operator deletes it after seeing page 5 on a desk and a phone. `git grep -n D188 -- . ':!plans/completed'` at authoring lists four places: the row itself, `docs/decisions/0128-...md` (a dated record; it keeps citing the row), `docs/specs/civicclerk-ingest.md` line 154 and `docs/specs/votes.md` line 37 (both edited by M4).

`D192` (two minutes links on the item page with no allowlist check) has as its trigger "the next change to that partial". M3 changes that partial. The Decision Log says why it is not paid; M4 writes that on the row, with the statement the operator can run to see production's minutes hosts.

`D7` (web modules that execute SQL) is not tripped as long as the new route calls services and executes no SQL; M2's acceptance checks that with a grep. The plan calls `docket.web.source_security.is_url_safe` and does not change that module.

### Prose that states the old rule

The old rule is "the link is the city's own file address with `#page=<n>`". `git grep` for `#page=`, `own file address`, `as a download` and `content-disposition` outside `plans/completed` and `docs/superpowers` lists these, each an edit or a leave-alone. Edited by M3: the comment above the link in `meeting_detail.html` (line 285) and the header comment of `_vote_result_block.html` (lines 14 to 21), and the assertions in `tests/web/test_mobile_minutes_votes.py`. Edited by M4: `docs/specs/votes.md` lines 33, 34 and 37; `docs/specs/civicclerk-ingest.md` line 154; `docs/DEBT.md` row `D188`; the Status line of `docs/decisions/0128-...md`. Left alone: `page_link` and its docstring in `src/docket/models/vote.py` and its tests in `tests/unit/test_vote_dataclass.py` and `tests/unit/test_query_list_votes.py` (the function is unchanged and now feeds the viewer's link to the city); `partials/source_anchor_button.html` and `tests/unit/test_source_anchor.py` (Birmingham's agenda anchors, a different link); `docs/specs/coming-up.md` and `public.py` line 1355 (the calendar feed's own header). `docs/SECURITY_CHECKLIST.md`, PDF Links, has the line "Don't proxy blindly — link to source PDFs, don't download and re-serve them"; M4 rewords it to say what the viewer does.

### Work in flight and identifiers

`plans/active/` held no other plan at authoring. In this tree the highest decision file is `0133` and the highest debt id is `D196`; those are observations, not allocations. A session that needs a new decision number or debt id takes the lowest number above every one spent in its own tree and on `origin/main` as its refs hold it at that moment (`ls docs/decisions`, `git grep -o "^| D[0-9]*" docs/DEBT.md`, and the same two against `origin/main`). A milestone session cannot list open pull requests; the retro stage after the last milestone does, and renumbers on a collision (debt row `D70` records this division).

## Plan of Work

### M1. Fetch, draw, and serve from memory

Write the unit tests first, see them fail, then write the three modules described in Interfaces and Dependencies, and name the two libraries in the requirements files.

`src/docket/adapters/source_file.py` holds `fetch_pdf`, one bounded GET with `requests`. `src/docket/analysis/pdf_page.py` holds `render_page`, which opens PDF bytes with `pypdfium2` and returns one page as PNG bytes with the page count. `src/docket/services/minutes_viewer.py` holds `page_view(minutes_url, page)`, which checks the page bound, takes the file from its cache or fetches it under a lock with the per-host gap, and renders. None of the three opens a database connection, and no route calls them yet.

In `requirements.txt` add two lines after `pdfplumber>=0.10`: `pypdfium2>=4.18` and `pillow>=9.1`, with a one-line comment above them saying the minutes page viewer draws a page with them. In `requirements.lock` change only the comments under the two packages so that they read:

    pillow==12.2.0
        # via
        #   -r requirements.txt
        #   pdfplumber
        #   pytesseract

    pypdfium2==5.8.0
        # via
        #   -r requirements.txt
        #   pdfplumber

(the blank line between them is for this plan's layout; in the file each block stays where it is, in alphabetical order). Do not run `uv pip compile`.

Tests, three new files. `tests/unit/test_source_file.py` fakes `requests.get` (monkeypatch `docket.adapters.source_file.requests.get` with a function returning a small stand-in response object that has `status_code`, `headers`, `iter_content(chunk_size)`, `close()` and, for a redirect, `is_redirect`) and asserts: a body beginning `%PDF-` is returned whole; the call was made with `stream=True`, `allow_redirects=False` and `timeout=(5.0, 10.0)`; an `http://` address raises `SourceFileError` and calls nothing; a 302, a 404 and a 500 raise; a `Content-Length` above the cap raises before any chunk is read; a body that passes the cap while streaming raises; a body that does not begin `%PDF-` raises; a `requests.ConnectionError` from the fake becomes `SourceFileError`; and when the module's clock (`source_file._now`, monkeypatched) passes the deadline between chunks, it raises. `tests/unit/test_pdf_page.py` reads `tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf` and asserts `render_page(data, 1)` has `page_count == 4`, `width == 1200`, `height == 1553`, and `png[:8] == b"\x89PNG\r\n\x1a\n"`; that page 4 renders; that pages 0 and 5 raise `PageOutOfRange` whose `page_count` is 4; and that `render_page(b"%PDF-1.4 not a pdf", 1)` raises `UnreadablePdf`. `tests/unit/test_minutes_viewer.py` replaces the service's `_fetch`, `_now` and `_sleep` with a counting fake fetch and a fake clock whose `sleep(s)` advances it, calls `minutes_viewer.clear()` before each test, and asserts the cases listed under Validation and Acceptance, M1.

### M2. The viewer page

Write `tests/web/test_minutes_viewer.py` first and see it fail (the route does not exist, so every request is a 404 where 200 is expected). Then add the route `minutes_page(slug, meeting_id, page)` to `src/docket/web/public.py` directly after `meeting_transcript`, the template `src/docket/web/templates/minutes_page.html`, a few CSS rules, and the robots line.

The route: the 404 lines quoted in Context; then 404 unless `meeting.minutes_url` is truthy and `source_security.is_url_safe(meeting.minutes_url)` (import `source_security` from `docket.web` at the top of `public.py`); then call `minutes_viewer.page_view(meeting.minutes_url, page)` (add `minutes_viewer` to the existing `from docket.services import ...` line). `NoSuchPage` is `abort(404)`. `Unavailable` renders the template with `view=None`. Both renders get `municipality`, `meeting`, `page`, and `city_url=page_link(meeting.minutes_url, page)` (import `page_link` from `docket.models.vote`); the available render also gets `view` and `image_b64`, the PNG bytes encoded with `base64.b64encode(...).decode("ascii")`. Every response from the route, the 200s only (an abort keeps the site's 404 page), carries `X-Robots-Tag: noindex`; the available one carries `Cache-Control: private, max-age=600` and the unavailable one `Cache-Control: no-store`. No response sets `Content-Disposition`. The route body contains no SQL and no `requests` call.

The template extends `base.html`. In `{% block head %}`: `<meta name="robots" content="noindex">`. Title: `Minutes, page {{ page }} — {{ meeting_label(meeting) or meeting.title }} — docket.pub`. Content, in this order, with these exact words and class names so that tests and later sessions agree:

A `<section class="hero hero--detail">` holding `<div class="t-eyebrow">Minutes · {{ meeting.meeting_date | format_date }}</div>`; an `<h1 class="hero-title t-display">` reading `Minutes, page {{ page }} of {{ view.page_count }}` when available and `Minutes, page {{ page }}` when not; a `<p class="t-meta">` with `<a class="link" href="{{ url_for('public.meeting_detail', slug=municipality.slug, meeting_id=meeting.id) }}">← Back to the meeting</a>` followed by ` · {{ meeting_label(meeting) or meeting.title }}`; and a `<p class="minutes-page-source">` holding the city's link, always present: `<a class="link minutes-city-file" href="{{ city_url }}" target="_blank" rel="noreferrer">The city's own file (PDF) ↗</a>` followed, when available, by the sentence ` This is page {{ page }} as docket.pub drew it from the city's file; the city's file is the record.` and, when not available, by ` docket.pub could not open the city's file just now. Open it and go to page {{ page }}.`

Then, when available only, a `<section class="feed minutes-page">` holding a `<nav class="minutes-page-nav t-meta">` with `<a class="link minutes-page-prev" rel="prev nofollow" href="...">← Page {{ page - 1 }}</a>` when `page > 1` and `<a class="link minutes-page-next" rel="next nofollow" href="...">Page {{ page + 1 }} →</a>` when `page < view.page_count` (each `href` from `url_for('public.minutes_page', ...)`), then `<img class="minutes-page-image" src="data:image/png;base64,{{ image_b64 }}" width="{{ view.width }}" height="{{ view.height }}" alt="Page {{ page }} of the minutes of the {{ meeting.meeting_date | format_date }} meeting, as the city published it">`, then the same nav again below the picture.

CSS, appended to `src/docket/web/static/layout.css`: `.minutes-page-image { display: block; width: 100%; max-width: 1200px; height: auto; border: 1px solid var(--rule); background: #fff; }` and `.minutes-page-nav { display: flex; justify-content: space-between; gap: 16px; padding: 8px 0; }`. `width: 100%` with `height: auto` is what makes the picture fit a phone's width; `mobile.css` needs no rule.

Robots: in `src/docket/web/crawlers.py` add the line `Disallow: /al/*/meetings/*/minutes/` to `_ROBOTS_GENERAL` after `Disallow: /*?`. Add to `tests/web/test_crawlers.py` a test `test_robots_keeps_crawlers_off_the_minutes_viewer` asserting that line is in the general group (taken the way `test_robots_welcomes_everyone_on_public_pages` takes it).

`tests/web/test_minutes_viewer.py` seeds, under external ids beginning `mv-test-` and removed before and after (model the helpers on `tests/web/test_mobile_minutes_votes.py`, which inserts into `meetings` by city slug): a Mobile meeting dated 2026-11-03 with `minutes_url` equal to the Mobile address quoted in Context; a Mobile meeting with no `minutes_url`; a Mobile meeting whose `minutes_url` is `https://minutes.example.org/file.pdf`; a Mobile meeting with the good address and `is_hidden` true; and a Birmingham meeting with `minutes_url` `https://bhamal.granicus.com/DocumentViewer.php?file=mv-test.pdf` (a host on the static allowlist), to show the route is not keyed on Mobile. An autouse fixture calls `minutes_viewer.clear()` and replaces `minutes_viewer._fetch` with a fake that appends its `url` argument to a list and returns the bytes of `tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf` (four pages), and `minutes_viewer._sleep` with a function that does nothing. The assertions are listed under Validation and Acceptance, M2.

### M3. The links

Change the tests first, see them fail, then the two templates.

In `meeting_detail.html` the link becomes, under the same `{% if is_source_url_safe(vote.minutes_page_url) %}`:

    <a class="link t-meta" rel="nofollow" href="{{ url_for('public.minutes_page', slug=municipality.slug, meeting_id=meeting.id, page=vote.source_page) }}">Minutes, page {{ vote.source_page }}</a>

and the comment above it is rewritten to say the link opens docket.pub's viewer of that page, which shows the city's own file address; that a vote with no page, or on a meeting with no minutes link, has no `minutes_page_url`; and that `is_source_url_safe` says no to that as to an address outside the allowlist. In `_vote_result_block.html` the second branch of `vote_source_link` becomes, under the same `elif`:

    <a class="link t-meta" rel="nofollow"
       href="{{ url_for('public.minutes_page', slug=municipality.slug, meeting_id=v.meeting_id, page=v.source_page) }}"
       data-item-id="{{ item.id }}">
      Read minutes, page {{ v.source_page }}
    </a>

and the file's header comment (lines 14 to 21) is rewritten the same way. The first, third and fourth branches and the "View full minutes" link are not touched. `minutes_page_url` is non-None only when `source_page` is set and the meeting has a `minutes_url`, so the condition already means "a vote with a page on a meeting whose minutes address is safe", for any city.

In `tests/web/test_mobile_minutes_votes.py`, add a helper `_viewer(ids_key_meeting_id, page)` returning `f"/al/mobile/meetings/{meeting_id}/minutes/page/{page}/"` and change these tests, and no others: `test_a_reader_vote_links_to_its_page_of_the_minutes` (the one link whose text contains "Minutes" has text exactly `Minutes, page 5`, its tag holds `href="<viewer address for the main meeting, page 5>"`, and the block holds neither `#page=` nor the city's `MINUTES_URL`); `test_the_page_link_opens_in_a_new_tab_without_a_referrer`, renamed `test_the_page_link_opens_in_the_same_tab_and_is_not_followed` (the tag holds `rel="nofollow"` and no `target=`); `test_each_reader_vote_links_to_its_own_page` (viewer addresses for pages 4 and 2); the two no-link tests for a meeting with no minutes link and an unsafe address, and the two "renders as before" tests, each gaining `assert "/minutes/page/" not in block` beside its existing assertions; `test_the_item_pages_vote_link_names_the_page` (text exactly `Read minutes, page 5`, the viewer address for page 5, `rel="nofollow"`, no `target=`); `test_the_item_pages_history_row_prints_its_own_declaration_and_page` (text `Read minutes, page 4`, the viewer address for page 4); and `test_the_item_page_prints_no_page_link_for_an_address_that_is_not_safe` (gaining `assert "/minutes/page/" not in section`). The module docstring's sentence about "a link to the page of the city's Minutes file" is reworded to "a link to docket.pub's viewer of that page". Add one test to `tests/web/test_minutes_viewer.py`, `test_the_meeting_pages_link_opens_a_viewer_page_that_answers`: seed a reader vote with `source_page` 2 on the good Mobile meeting (columns as `_vote` in `test_mobile_minutes_votes.py` inserts them), get the meeting page, take the `href` of the link whose text is `Minutes, page 2`, request it, and assert 200 and `Minutes, page 2 of 4` in the body.

### M4. The close

No code changes. Edit the documents so that each says, in the present tense, what M1 to M3 built, reading the code as built and not this plan's wording where they differ.

`docs/specs/votes.md`: lines 33 and 34 say the links open the viewer (words, address shape, `rel="nofollow"`, the same condition); line 37's paragraph is replaced by a short section, "The minutes page viewer", that owns the viewer's behaviour: the route and its 404 rule, the states listed in Context, what the page prints (heading, the city's link and its two sentences, the neighbouring-page links, the picture and its alt text), the headers, that nothing is stored, the cache and fetch bounds by reference to the constants in `src/docket/services/minutes_viewer.py` and `src/docket/adapters/source_file.py` (name the constants; do not restate values that the code owns beyond one mention), the per-process nature of the cache and the gap, and the tests that pin it. `docs/specs/civicclerk-ingest.md`: the Known limits line 154 says a browser saves the city's file, which is why the vote's link opens the viewer (`docs/specs/votes.md`), and the paragraph on requests (line 38) gains a sentence that a reader's view of a minutes page is a second, separate fetch of a city's file, made by the web process through `source_file.fetch_pdf` under its own bounds and not by the adapter. `docs/specs/crawlers.md`: the general rule's list gains the viewer path and why (each crawl of a viewer address could be a request to the city), and the `X-Robots-Tag: noindex` header is named beside the blog's. `docs/specs/operations.md`: under Railway specifics, one paragraph with the operator's look after a deploy that changes the viewer (the steps under Validation and Acceptance) and the log line to search for when the unavailable state appears. `docs/specs/index.md`: the `votes.md` row's description gains the viewer. `ARCHITECTURE.md`: the Adapters component names `source_file.py` as a fourth read-only client outside the protocol, the Analysis component names `pdf_page.py`, and the Services component names `minutes_viewer.py` (no statement of its own; an in-memory cache). `docs/SECURITY_CHECKLIST.md`, PDF Links: the "Don't proxy blindly" line is reworded to say source PDFs are linked, never stored, and that the one place a city's PDF is fetched for a reader is the minutes page viewer, which fetches only a stored address that passed the allowlist, follows no redirect, checks the body begins `%PDF-`, and serves a picture of one page beside the city's link.

Decisions: write one new record under `docs/decisions/`, in the format of `docs/decisions/DECISION_FORMAT.md` and numbered by the rule in Context, titled to the effect "A minutes vote's link opens docket.pub's viewer of the page, drawn in memory from the city's file, which is never stored", carrying the Decision Log entries above that proved durable (mechanism, no storage, fetch bounds and politeness, the 200 unavailable state, the layering). Change the Status line of `docs/decisions/0128-a-minutes-votes-link-is-the-citys-own-file-address-with-the-page-and-its-words-name-the-page.md` from `accepted` to `superseded by <the new number>`, and nothing else in that file.

`docs/DEBT.md`: rewrite the `D188` row in place, keeping the id. Its Item says the viewer is built and unobserved in a browser; its Trigger is "the pull request merges" followed by the operator's steps in the order Validation and Acceptance gives them, ending "the operator deletes this row after seeing page 5 on a desk and on a phone, or writes here what was seen instead". On the `D192` row, append that its trigger fired on this plan's M3, that the two links were not changed, why, and the statement the operator runs to list production's minutes hosts: `SELECT split_part(split_part(minutes_url, '://', 2), '/', 1) AS host, count(*) FROM meetings WHERE minutes_url IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;`. Add one new row, numbered by the rule in Context, for each of these unless a milestone's record shows it no longer holds: the viewer's fetch runs inside the web worker, so a slow city file holds that worker for up to about 21 seconds, and which gunicorn timeout and worker count production runs is not written down (trigger: the operator sees the site stall while a viewer page loads, or the web service is given more workers or threads); the viewer shows a picture of the page with no text a screen reader can read, the city's PDF being the only accessible form (trigger: an accessibility pass before public launch, or a reader asks); the meeting page's rail link "Official minutes" for a Mobile meeting still downloads the file (trigger: the operator asks for it to open the viewer at page 1). Add a row for anything else a milestone's Surprises or Decision Log deferred.

Write Outcomes & Retrospective's outcome entry: what exists against the Purpose, and that the operator's look is still to come.

## Concrete Steps

Every command is run from the worktree root, `.claude/worktrees/minutes-open-at-the-vote-page` under the main checkout, with that worktree's `venv/`.

At the start and at the end of every milestone session:

    ./tools/verify

Expected last line: `verify: all 6 checks passed in <seconds>s.` and exit status 0. Record the lines it printed.

To run chosen test files (the form the author ran at authoring, where it printed `48 passed` for two existing files):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest <files> -q -p no:cacheprovider

The inline `tools/test-db` builds the throwaway database and prints its address; `tools/test-db --drop` removes it afterwards, and `./tools/verify` builds and drops its own.

M1, after the modules exist (expected output, not yet observed; the figures are those the author's scratch script printed for this fixture):

    venv/bin/python -c "from pathlib import Path; from docket.analysis.pdf_page import render_page; r = render_page(Path('tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf').read_bytes(), 1); print(r.page_count, r.width, r.height, r.png[:8])"

    4 1200 1553 b'\x89PNG\r\n\x1a\n'

M2, the layering check (expected: no output from either):

    git grep -n "db_cursor\|db()\|execute(" -- src/docket/services/minutes_viewer.py src/docket/adapters/source_file.py src/docket/analysis/pdf_page.py
    git diff origin/main -- src/docket/web/public.py | grep "^+" | grep -n "execute(\|db_cursor\|requests\."

M4, after the edits (expected: `1` from the first; from the second, `docs/DEBT.md`, the `0128` record and the new decision record, and a spec file only where its sentence names the row as the operator's look still to come):

    grep -c "^| D188 " docs/DEBT.md
    git grep -ln "D188" -- docs src

Commit after each coherent step. Every commit in a milestone session changes this plan file (add the evidence as you go), a Progress line's text is never reworded, and git hooks are never bypassed.

## Validation and Acceptance

### M1

Before the modules exist, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_source_file.py tests/unit/test_pdf_page.py tests/unit/test_minutes_viewer.py -q -p no:cacheprovider` fails every test with an import error; record the summary line. After, the same command's summary line names no failure, the one-line render command in Concrete Steps prints `4 1200 1553 b'\x89PNG\r\n\x1a\n'`, the first layering grep prints nothing, `git diff origin/main --stat -- requirements.lock` shows comment lines only (no line beginning with a package name and `==` is added or removed: `git diff origin/main -- requirements.lock | grep "^[+-][a-z]"` prints nothing), and `./tools/verify` passes.

What `tests/unit/test_minutes_viewer.py` asserts, with a fake clock starting at 100.0 and the four-page fixture as the fetched bytes: `page_view(URL, 2)` returns a `PageView` with `page == 2`, `page_count == 4` and PNG bytes, after one fetch of exactly `URL`; a second call for page 3 of the same address fetches nothing more; `page_view(URL, 0)` and `page_view(URL, 2001)` raise `NoSuchPage` with no fetch at all; `page_view(URL, 5)` raises `NoSuchPage` after one fetch, and a repeat fetches nothing more; with the clock advanced 3,601 seconds a further call fetches again; a fetch that raises `SourceFileError` gives `Unavailable`, a second call 10 seconds later gives `Unavailable` with the fetch count still 1, and a call 61 seconds after the failure fetches again; bytes that are not a PDF give `Unavailable`, are not kept, and are not fetched again within 60 seconds; five different addresses fetched in turn and then the first again make six fetches (the cache holds four files); with `CACHE_BYTES` set to one more than the fixture's length, a second address evicts the first; and the gap: one address on host `a.example` fetched at 100.0, the clock moved to 100.3, a second address on the same host makes the fake sleep record exactly one call of 0.7 (`pytest.approx`), and a third address on host `b.example` straight after adds no sleep.

### M2

Before the route exists, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_minutes_viewer.py tests/web/test_crawlers.py -q -p no:cacheprovider` fails the new tests; record the summary line. After, its summary line names no failure, both layering greps print nothing, and `./tools/verify` passes.

What `tests/web/test_minutes_viewer.py` asserts. For the good Mobile meeting, `GET /al/mobile/meetings/<id>/minutes/page/2/` is 200; the response has no `Content-Disposition` header, `X-Robots-Tag` is `noindex`, and `Cache-Control` is `private, max-age=600`; the body contains `Minutes, page 2 of 4`, an `<a` tag with class `minutes-city-file` whose `href` is the stored address followed by `#page=2` with `target="_blank"` and `rel="noreferrer"`, an `<img` with class `minutes-page-image` whose `src` begins `data:image/png;base64,` and whose base64 text decodes to bytes beginning `\x89PNG`, a link to `/al/mobile/meetings/<id>/minutes/page/1/` and one to `.../page/3/`, a link back to the meeting page, and `<meta name="robots" content="noindex">`; and the fake fetch was called once, with exactly the stored address. Page 1 has no link to page 0 and page 4 has no link to page 5. The same request with `?url=https://evil.example/x.pdf&page=3` appended is the same page 2 and the fake's recorded addresses are all the stored one. Page 0 and page 2001 are 404 with the fake never called; page 5 is 404 with the fake called once. The meeting with no `minutes_url`, the meeting with the address outside the allowlist, the hidden meeting, the good meeting's id under `/al/birmingham/`, and an unknown meeting id are each 404 with the fake never called. With the fake raising `SourceFileError`, the response is 200 with `Cache-Control: no-store` and `X-Robots-Tag: noindex`, contains `Minutes, page 2` and not `of 4`, contains the `minutes-city-file` link to the stored address with `#page=2` and the words `could not open the city's file just now`, and contains no `<img` with class `minutes-page-image`. The Birmingham meeting's page 1 is 200 with the Birmingham address in its city link.

### M3

Before the templates change, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_mobile_minutes_votes.py tests/web/test_minutes_viewer.py tests/web/test_vote_result_block.py -q -p no:cacheprovider` fails the changed and added tests; record the summary line and which failed. After, its summary line names no failure; `git diff origin/main -- src/docket/web/templates/partials/_vote_result_block.html` shows changes only in the header comment and in the second branch of `vote_source_link`; and `./tools/verify` passes.

### M4

`./tools/verify` passes. `grep -c "^| D188 " docs/DEBT.md` prints `1` and the row's Trigger cell begins with the merge and lists the operator's steps below. `ls docs/decisions | tail -3` shows one new record whose number is above every other in the directory, and `grep -n "^superseded by" docs/decisions/0128-*.md` prints one line naming it. `git grep -n "own file address" -- docs/specs` prints no sentence that says a vote's link is the city's file address (a sentence saying the viewer page links to the city's own file address is expected), and `git grep -n "content-disposition" -- docs/specs/votes.md docs/specs/civicclerk-ingest.md` prints only sentences that give the city's download header as the reason the viewer exists. Each of the documents named in M4's Plan of Work has a diff against `origin/main` (`git diff origin/main --stat -- docs ARCHITECTURE.md` lists them).

### The operator's steps, after the pull request merges

These are not part of any milestone. No session takes them; M4 writes them into the `D188` row.

1. In the WSL checkout of docket-pub on the Legion (the main checkout, not a worktree), on a clean `main` that holds the merge: `scripts/deploy.sh --service docket-web`. There is no migration and the worker needs no deploy.
2. In the Windows browser, open `https://docket.pub/al/mobile/`, open the meeting of 2026-11-03, and on the vote on resolution 40-948-2026 click "Minutes, page 5". Expected: a docket.pub page headed "Minutes, page 5 of <the file's page count>" showing a picture of page 5, with nothing downloaded; "The city's own file (PDF) ↗" above the picture; "← Page 4" and "Page 6 →" that move a page each; "← Back to the meeting" that returns.
3. Narrow the window to phone width (about 375 pixels) and see the picture fit the width with no sideways scrolling; then do step 2 on a phone.
4. Open an item page of that meeting whose vote link reads "Read minutes, page <n>" and click it; the same viewer opens at that page.
5. If a viewer page instead says docket.pub could not open the city's file, run `railway logs --service docket-web` in the WSL terminal and look for a line beginning `minutes viewer:`; it gives the reason (a timeout from Railway to the city, a refusal, the PDF library not loading). Write what it says on the `D188` row; that is a finding for a new session.
6. When steps 2 to 4 are as expected, delete the `D188` row. The link to the city's file still downloads; that is the city's doing and is expected.

## Idempotence and Recovery

Every step is an edit to files in the worktree and can be repeated. There is no migration, no production write, and no request to any city in any milestone: tests fake the fetch, and a session must not fetch a city's file to "see it work". The in-memory cache is emptied by restarting the process; `minutes_viewer.clear()` empties it in tests. If the viewer misbehaves in production, reverting M3's two template changes restores the old links while leaving the viewer route in place; reverting the merge restores everything. `tools/test-db --drop` removes a throwaway database a failed run left behind.

If a milestone will not fit in its session, split its Progress entry in place as `plans/PLANS.md` says (add a new line for the remainder; do not reword the existing line), record the split in the Decision Log, and stop.

## Artifacts and Notes

What the author measured, once, on 2026-11-22, is in Surprises & Discoveries: the city's response headers for file 3854 (693,774 bytes, forced download, framing denied, 0.37 seconds from the development machine), and the drawing figures (38 pages; page 5 at 1,200 pixels wide is 1200 by 1977 and a 479,644-byte PNG, drawn and encoded in 0.078 seconds; 54 MB peak for the process). Whether file 3854 is the minutes of the 2026-11-03 meeting was not checked; it is the address the existing tests use. The downloaded file is in the author's scratch directory, outside the repository, and is not committed: the tests use the four-page Birmingham committee PDF already in `tests/fixtures/committee_documents/`.

The worst case for one reader request, from the constants: up to 5 seconds waiting for the lock (only when the process serves threads; a synchronous gunicorn worker never waits), up to 1 second for the gap, up to 20 seconds for the fetch, and about 0.1 second to draw: 26.1 seconds with a contended lock, 21.1 without, both under gunicorn's 30-second default.

## Interfaces and Dependencies

Libraries: `requests` (already used by every adapter) for the fetch; `pypdfium2` and `pillow` (already installed) to draw a page. No new package is installed. `pypdfium2` is imported inside `render_page`, not at module top, so that a failure to load its binary becomes `UnreadablePdf` and the unavailable state, not an import error that takes down the site.

In `src/docket/adapters/source_file.py`:

    class SourceFileError(Exception):
        """The file could not be fetched within the bounds, or is not a PDF."""

    CONNECT_TIMEOUT_S = 5.0
    READ_TIMEOUT_S = 10.0
    DEADLINE_S = 20.0
    MAX_BYTES = 25 * 1024 * 1024

    _now = time.monotonic   # replaced in tests

    def fetch_pdf(url: str) -> bytes:
        """One GET of a city's PDF, one attempt. SourceFileError unless the address is https,
        the answer is a 200 that is not a redirect, the body is at most MAX_BYTES (by its
        Content-Length when it declares one, and by count while streaming), arrives within
        DEADLINE_S, and begins b'%PDF-'. Follows no redirect. Any requests.RequestException
        is raised as SourceFileError."""

It calls `requests.get(url, stream=True, allow_redirects=False, timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))`, reads with `iter_content(chunk_size=64 * 1024)`, checks the deadline against `_now()` after each chunk, and closes the response in a `finally`. It imports nothing from `docket.services` or `docket.web`.

In `src/docket/analysis/pdf_page.py`:

    @dataclass(frozen=True)
    class RenderedPage:
        png: bytes
        page_count: int
        width: int
        height: int

    class UnreadablePdf(Exception): ...

    class PageOutOfRange(Exception):
        def __init__(self, page: int, page_count: int): ...   # keeps both as attributes

    WIDTH_PX = 1200

    def render_page(pdf_bytes: bytes, page: int, *, width_px: int = WIDTH_PX) -> RenderedPage:
        """Page `page` (1-based) of a PDF as a PNG width_px wide, with the file's page count."""

It opens the bytes with `pypdfium2.PdfDocument(pdf_bytes)`, takes `len(pdf)` as the count, raises `PageOutOfRange` unless `1 <= page <= count`, renders with `pdf[page - 1].render(scale=width_px / pdf[page - 1].get_size()[0]).to_pil()`, saves the image as PNG to an `io.BytesIO`, and closes the page and the document. The whole body runs under a module-level `threading.Lock`, because the PDF library is not safe to call from two threads at once. Any exception from the library (including a failed import) is raised as `UnreadablePdf`.

In `src/docket/services/minutes_viewer.py`:

    MAX_PAGE = 2000
    CACHE_FILES = 4
    CACHE_BYTES = 40 * 1024 * 1024
    CACHE_TTL_S = 3600.0
    FAILURE_TTL_S = 60.0
    HOST_GAP_S = 1.0
    LOCK_WAIT_S = 5.0

    _fetch = source_file.fetch_pdf   # replaced in tests
    _now = time.monotonic
    _sleep = time.sleep

    @dataclass(frozen=True)
    class PageView:
        page: int
        page_count: int
        png: bytes
        width: int
        height: int

    class NoSuchPage(Exception): ...
    class Unavailable(Exception): ...

    def page_view(minutes_url: str, page: int) -> PageView: ...
    def clear() -> None:   # forget every cached file, failure and host time; for tests

`page_view` works in this order. Raise `NoSuchPage` unless `1 <= page <= MAX_PAGE`. Take the module lock with `acquire(timeout=LOCK_WAIT_S)`; if it is not acquired, raise `Unavailable`. Under the lock: if a failure for this address is remembered and younger than `FAILURE_TTL_S`, raise `Unavailable`; if the cache holds this address younger than `CACHE_TTL_S`, use its bytes; otherwise wait, with `_sleep`, whatever remains of `HOST_GAP_S` since the last request to this address's host (`urlsplit(url).netloc.lower()`) returned or raised, call `_fetch(minutes_url)` through the module attribute (so a test's replacement is seen), record `_now()` as that host's last request time whether it returned or raised, and on `SourceFileError` log a warning beginning `minutes viewer:` with the address and the reason, remember the failure, and raise `Unavailable`; on success store the bytes with the time, then drop the oldest entries until at most `CACHE_FILES` files and `CACHE_BYTES` bytes remain (read both constants at call time, so a test can change them). Release the lock, then call `pdf_page.render_page(bytes, page)`: `PageOutOfRange` becomes `NoSuchPage`; `UnreadablePdf` removes the address from the cache, remembers a failure, logs the same kind of warning, and becomes `Unavailable`. The service imports `docket.adapters.source_file` and `docket.analysis.pdf_page` and nothing from `docket.web`, `docket.db` or `docket.services.query`.

In `src/docket/web/public.py`:

    @bp.route("/al/<slug>/meetings/<int:meeting_id>/minutes/page/<int:page>/")
    def minutes_page(slug, meeting_id, page): ...

The endpoint name is `public.minutes_page`; M3's templates build the address with `url_for('public.minutes_page', slug=..., meeting_id=..., page=...)`. The template is `src/docket/web/templates/minutes_page.html`, with the class names `minutes-city-file`, `minutes-page-image`, `minutes-page-nav`, `minutes-page-prev` and `minutes-page-next` given in the Plan of Work.

Revision note, 2026-11-22 (authoring): this is the first version of the plan, written from the operator's goal and a scope brief that the plan folds into Purpose and Context instead of committing it as a file. Deliberately left out, as the brief's out-of-scope list has it: Birmingham's minutes links and the `#page=N` links of `partials/source_anchor_button.html` (Birmingham votes carry no page and its files were not reported as downloading; the viewer is city-neutral by construction but nothing is switched over for a city without vote pages); the `p. N` marks on minutes-versus-video discrepancies, which are a different page number from a different table; highlighting the vote's lines, searching inside the minutes, or a text layer; storing rendered pages or PDFs in Postgres or on disk; a Content-Security-Policy or other site-wide headers; the adjacent Mobile rows `D183` and `D189`; the deploy and the look on a desk and a phone, which are the operator's and are written as steps for the `D188` row; and the open GitHub issues, none of which names this link. The author also left out, and names for M4's debt rows: the meeting page's rail link "Official minutes", which still goes to the city's file; and paying `D192`, whose trigger M3 fires. Two refinements of the brief's defaults are in the Decision Log: a page past the file's end is a 404 only after the file is in hand, and the fetch goes through a new city-neutral adapter module, not `CivicClerkAdapter.fetch_file`.
