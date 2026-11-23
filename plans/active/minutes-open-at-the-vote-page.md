# Open the minutes at the vote's page, on docket.pub

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `plans/PLANS.md`.

## Purpose / Big Picture

A vote that docket.pub read from a city's minutes says which page of the minutes it is printed on, and links there: "Minutes, page 5" on the meeting page, "Read minutes, page 5" on the item page. Today that link is the city's own file address with `#page=5` on the end. For Mobile, the only city whose votes carry a page, the city's system answers every file request with a header that tells the browser to save the file, so the link does not open anything. The operator saw it on 2026-11-22 and wrote it on debt row `D188`: on https://docket.pub/al/mobile/, meeting of 2026-11-03, clicking "Minutes, page 5" on the vote on resolution 40-948-2026 downloaded the PDF in the Windows browser on a desk, and a phone tried to download it too. Neither opened at page 5.

After this work the same link opens a page on docket.pub that shows page 5 of the minutes, in the browser, on a desk and at phone width, with nothing downloaded. The page names the page number, always shows a visible link to the city's own file (the same address the link points at today), and has links to the page before and the page after. The route is keyed on the meeting and the page number, not on Mobile: any city whose vote has a page and whose meeting has an `https` minutes address on the allowlist gets the viewer link, and any other vote keeps the link it has now. No copy of the city's PDF is kept: no migration, no table, no file on disk. The file is fetched from the city when a reader asks, held in the web process's memory for at most an hour, and drawn as a picture of the one page.

How to see it working. In the repository: new tests fail before the work and pass after it, showing that the vote's link on the meeting and item pages is a docket.pub viewer address carrying the page; that the viewer's answer for a seeded meeting, with the city's fetch faked, is 200, is shown inline (no `Content-Disposition` header), and contains the city's own file address as a link; that a page out of range, a meeting with no minutes link, a hidden meeting, or an address outside the allowlist or not `https` is a 404; and that the viewer fetches only the address stored on the meeting, never one taken from the request. `./tools/verify` passes. The final acceptance is the operator's, after the pull request merges and the web service is deployed, in the Windows browser and on a phone, because no factory session has a browser: click "Minutes, page 5" on that vote and see page 5.

## Progress

- [x] (2026-11-23 03:10Z) M1: two modules that no page uses yet fetch one PDF from a city under a time and size bound in one attempt (`docket.adapters.source_file`) and draw one page of a PDF as a picture in memory, with its size bounded whatever the page's shape (`docket.analysis.pdf_page`); `pypdfium2` and `pillow` are named in `requirements.txt`; their unit tests pass and `./tools/verify` passes
- [ ] M2: a service that no page uses yet (`docket.services.minutes_viewer`) hands a page of a stored minutes address to a caller from a small in-memory cache, with a one-second gap between requests to one host, one fetch for callers who ask for the same file at once, and a memory of failures that stops repeats; its unit tests pass, the ones with two threads included, and `./tools/verify` passes
- [ ] M3: `GET /al/<slug>/meetings/<id>/minutes/page/<n>/` shows page n of the meeting's minutes inline on a docket.pub page with a visible link to the city's own file and links to the pages before and after, answers 404 for a page out of range, a meeting with no minutes link, a hidden meeting, or an address that is not `https` or is outside the allowlist, shows the city's link alone when the file cannot be fetched, and is kept from crawlers by `robots.txt` and a `noindex` header; its web tests pass with the city's fetch faked and `./tools/verify` passes
- [ ] M4: the meeting page's "Minutes, page <n>" link and the item page's "Read minutes, page <n>" link open the viewer page in place of the city's file address, for any vote with a page on a meeting whose minutes address the viewer can show; any other vote keeps the link it has; the web tests pass and `./tools/verify` passes
- [ ] M5: the close: the specs (`docs/specs/votes.md`, `civicclerk-ingest.md`, `crawlers.md`, `operations.md`, `index.md`), `ARCHITECTURE.md` and `docs/SECURITY_CHECKLIST.md` describe the viewer as built, the decision that supersedes `0128` is graduated to `docs/decisions/`, and `docs/DEBT.md` has the `D188` row rewritten as the operator's steps after the merge, the `D192` row saying its trigger fired and why it stays, and a row for each thing M1 to M4 deferred; `./tools/verify` passes

## Surprises & Discoveries

As authored on 2026-11-22, nothing has been executed, so no milestone has an observation here yet. What the author observed while researching, and while revising the plan against an outside review the same day, is below; each is the author's, from the worktree at `4a8ad25` (the first four) or `c75fef6` (the rest), from a scratch script, or from a request to the city or to docket.pub's public pages.

- Observation (authoring): Mobile's file endpoint forbids framing as well as forcing a download, so no design that embeds the city's own address in a docket.pub page can work.
  Evidence: `curl -s -o <scratch file> -D - 'https://mobileal.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3854,plainText=false)'`, run once at 23:28Z on 2026-11-22, printed `HTTP/2 200`, `content-type: application/pdf`, `content-length: 693774`, `x-frame-options: DENY`, `content-disposition: attachment; filename=3854.pdf; filename*=UTF-8''3854.pdf`, and curl's timing line read `connect=0.060748s firstbyte=0.297054s total=0.372249s`. This was from the development machine (WSL); from Railway nobody has timed it.

- Observation (authoring): drawing one page of that file with the PDF library already installed takes well under a tenth of a second and little memory.
  Evidence: a scratch script (not committed) opened the 693,774-byte file with `pypdfium2.PdfDocument(bytes)`, and for pages 1, 5 and 38 called `page.render(scale=1200 / page.get_size()[0]).to_pil()` and saved a PNG to memory. It printed `pages 38 open_s 0.0`, then for page 5 `pts 612 1008 px (1200, 1977) RGB render+png_s 0.078 ... rgb_png 479644` (pages 1 and 38: 0.08 s and 339,541 bytes; 0.065 s and 386,725 bytes), and `maxrss_mb 54` for the whole process. A body that is not a PDF raised `pypdfium2._helpers.misc.PdfiumError: Failed to load document (PDFium: Data format error).`

- Observation (authoring): the repository already holds a small real PDF the tests can use as the city's answer, and it has four pages.
  Evidence: the same script on `tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf` (217,180 bytes) printed `pages 4` and for page 1 `pts 612 792 px (1200, 1553) RGB`; asking for a fifth page raised `PdfiumError: Failed to load page.`

- Observation (authoring): the test command this plan gives runs in this worktree, and the two existing files it will change pass today.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_mobile_minutes_votes.py tests/web/test_crawlers.py -q -p no:cacheprovider` printed `48 passed, 1 warning in 3.82s`; `tools/test-db --drop` then removed the database.

- Observation (review revision): file 3854 is the minutes of the 2026-11-03 meeting, the one the operator's report names, so the file the author measured is the file the operator will look at.
  Evidence: `curl -s https://docket.pub/al/mobile/meetings/1071/` (docket.pub's own public page, 2026-11-23 about 02:30Z) contains `40-948-2026` once and the file ids 3831 and 3854; meetings 1069, 1070 and 1072 do not contain `40-948-2026`. Meeting 1070's page carries 48 page links to file 3861 with pages from 2 to 42. Ten Mobile minutes files an earlier plan's author had saved in a scratch directory run from about 0.5 MB (the median is 563,153 bytes) to 1,583,468 bytes.

- Observation (review revision): the same picture saved as lossless WebP is about a fifth the size of the PNG, pixel for pixel the same, and takes about as long.
  Evidence: a scratch script (not committed) on file 3854 printed, for page 5 at 1200 by 1977, `png (479644, 0.044)`, `webp_lossless (90240, 0.065)`, `webp85 (232792, 0.085)`, `gray_png (199097, 0.019)`, each pair being bytes and seconds to encode; pages 1 and 38 gave lossless WebP of 70,858 and 69,012 bytes against PNG of 339,541 and 386,725; the fixture's page 1 gave 86,612 against 311,110. Rendering alone took 0.004 to 0.015 s a page. `PIL.features.check('webp')` printed `True` in this worktree. Whether the production image's Pillow can write WebP nobody has seen; the design falls back to PNG.

- Observation (review revision): the scale the first version of this plan gave, `width_px / page width`, has no bound on the picture's height, and the library follows a page's rotation.
  Evidence: the scratch script set page boxes on the fixture and printed what that scale would draw: a page 0.5 by 800 points gives 1200 by 1,920,000 pixels, a page 612 by 14,400 points gives 1200 by 28,235, a page 1224 points wide (a 17-inch ledger sheet) gets a scale of 0.98, about 70 dots to the inch. With `page.set_rotation(90)` on the fixture's letter page, `get_size()` returned `(792.0, 612.0)` and the render was 1200 by 928, so size and render agree on a rotated page. Every rendered image was mode `RGB` and its corner pixel `(255, 255, 255)`: the library fills the page white by default. The rule this plan now states (Interfaces and Dependencies), run on pages made with `pypdfium2.PdfDocument.new()`, printed these sizes, which are the figures M1's tests use: 612 by 792 points gives (1200, 1553); 1224 by 792 gives (1836, 1188); 3000 by 792 gives (4000, 1056); 612 by 14,400 gives (170, 4000); 20 by 20 gives (1200, 1200); 612 by 792 rotated 90 degrees gives (1200, 928). The library also opened the fixture with a byte-order mark and a newline put before `%PDF-` (`prefixed opens, pages 4`).

- Observation (review revision): Mobile's file endpoint answers a request that names docket.pub as it answers curl.
  Evidence: one request at 02:35Z on 2026-11-23, `curl -s -A "docket.pub minutes viewer (+https://docket.pub)" -H "Accept: application/pdf"` to the address of file 3854, printed `HTTP/2 200`, `content-type: application/pdf`, `content-length: 693774`, the same two headers as before, `total=0.554487s`, and the body began `%PDF-1.6`. From the development machine; from Railway nobody has tried it. The ingest adapter (`CivicClerkAdapter`, `src/docket/adapters/civicclerk.py`) sends the `requests` library's default User-Agent from Railway every day and is answered.

- Observation (review revision): the review's worry that the item page's macro cannot see `municipality` does not hold in this tree.
  Evidence: `src/docket/web/templates/item_detail.html` line 111 brings the partial in with `{% include 'partials/_vote_result_block.html' %}`, which shares the page's variables; the macro `vote_source_link` is defined and called in that one file and its fourth branch already builds a link with `url_for('public.meeting_detail', slug=municipality.slug, meeting_id=v.meeting_id, ...)`; `tests/web/test_vote_result_block.py` passes `"municipality": _MUNI` in every render and its `_FakeVote` has `meeting_id = 100`.

- Observation (review revision): nothing in the repository checks `requirements.lock` against a hash or regenerates it, so the hand edit of its comments is not refused by a check.
  Evidence: `grep -n "requirements" tools/verify tools/check-* .github/workflows/*` printed one line, `.github/workflows/verify.yml:32: cache-dependency-path: requirements.lock`, which only keys a cache.

- Observation (review revision): what production's web service runs is still unread, and a factory or authoring session cannot read it.
  Evidence: the author's `railway ssh --service docket-web "... ps -eo pid,ppid,rss,args ..."` was refused before it ran, by the harness's auto-mode classifier (`Reason: [Unauthorized Access]`). What the tree says: the `Dockerfile`'s last line starts `gunicorn 'docket.web:create_app()' --bind ...` with no other option (gunicorn's defaults: one synchronous worker, a 30-second timeout); the `Procfile` adds `--timeout 120`; there is no `railway.toml` or `railway.json`; a comment at `src/docket/web/public.py` line 117 says "single-worker sync gunicorn per Procfile + Dockerfile". The three readings only the operator can take are under Validation and Acceptance, The operator's readings before the merge.

- Observation (M1, 2026-11-23): the starting state was green, and the two new test files fail every test before the modules exist.
  Evidence: `./tools/verify`, run at `2eb9317` before any edit, printed `verify: unit+web+services ... ok (176s)`, `verify: integration ... ok (128s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (10s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 315s.` Then, with `tests/unit/test_source_file.py` and `tests/unit/test_pdf_page.py` written and neither module present, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_source_file.py tests/unit/test_pdf_page.py -q -p no:cacheprovider` printed `1 warning, 42 errors in 0.68s`. They are 42 errors and not 42 failures because each test takes its module through a fixture that imports it (`ModuleNotFoundError` in the fixture's setup), which keeps the files collectable; the commit that holds this entry holds the tests in that state.

- Observation (M1, 2026-11-23): with the two modules written, every acceptance check of M1 printed what the plan expects.
  Evidence: `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_source_file.py tests/unit/test_pdf_page.py -q -p no:cacheprovider` printed `42 passed, 1 warning in 0.84s` on the tests as committed failing at `4cbe6bd`, and `45 passed, 1 warning in 0.91s` after the three tests the removal check added (next entry). The one-line render command of Concrete Steps printed `4 1200 1553 image/webp b'RIFF' b'WEBP'`. `git grep -n "db_cursor\|db()\|execute(" -- src/docket/adapters/source_file.py src/docket/analysis/pdf_page.py` printed nothing (the service's file, the third the plan's command names, does not exist until M2). `git diff origin/main -- requirements.lock | grep "^[+-][a-z]"` printed nothing; the lock's whole diff is one added comment line under `pillow` and `# via pdfplumber` under `pypdfium2` become the three-line form the plan gives. `venv/bin/python -c "import sys, docket.analysis.pdf_page, docket.adapters.source_file; print('pypdfium2' in sys.modules, 'PIL' in sys.modules)"` printed `False False`: importing the two modules loads neither library. `./tools/verify`, run after the last edit to any file under `src/` or `tests/`, printed `verify: unit+web+services ... ok (171s)`, `verify: integration ... ok (128s)`, `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (10s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 310s.`

- Observation (M1, 2026-11-23): the new tests passed on the first run of the code, so each rule was taken out of a copy of the code held in memory and the tests run against it. 48 removals were tried; 43 failed at least one test; 5 fail none, and each of the 5 is named here.
  Evidence: a pytest plugin in the session scratchpad (not committed) compiled each module's source with one substitution and executed it into the imported module; the committed files were not edited. The first run, of 47 removals against the 42 tests of `4cbe6bd`, left eight free; three tests were then added to `tests/unit/test_pdf_page.py` (after the failing-first commit): `test_render_page_holds_the_lock_and_closes_the_document`, `test_page_count_holds_the_lock_and_closes_the_document` and `test_the_lock_is_released_when_the_page_is_out_of_range`, which put a stand-in for the PDF library in `sys.modules` whose documents record whether `pdf_page._lock` was held when they were opened and that they were closed. With them, removing the lock from either function and removing either `pdf.close()` each fail a test (a 48th removal, the `close()` in `page_count`, was added to the list then). The 25 removals in `source_file.py` (the `https` check and its letter case, each argument of the request, each status rule, both caps and their strictness, the malformed `Content-Length`, the chunk size, the deadline, its `host_down` and where it is counted from, the PDF mark and its 1,024-byte window, the wrapping of request errors, `close()`) fail a test, all but one. The five that fail nothing: (1) `source_file._declared_length` returning a negative `Content-Length` as it is, because a negative number is never above the cap, so the clause and its absence behave the same; (2) the refusal of a page whose width or height is not above zero, because no such page could be made: `pypdfium2.PdfDocument.new().new_page(0, 100)` and `new_page(100, 0)` each printed a size of `(612.0, 792.0)`, before and after saving and reopening; (3) the conversion to `RGB`, because every picture the library drew was already `RGB` (the author's observation, and these tests'); (4) `pdf_page.close()` on the page, which nothing a test can see depends on (closing the document is pinned); (5) moving `import pypdfium2` to the top of `pdf_page.py`, which is an artifact of the method and not a hole: `test_the_module_does_not_load_the_pdf_library_when_imported` reads the file on disk, which the in-memory copy does not change. The same filter the test uses, run on the altered source, printed `['import pypdfium2']`, so the test would fail on a committed file with that import.

- Observation (M1, 2026-11-23): the library gives a new page asked for with a zero side the size of a letter sheet.
  Evidence: the scratch run quoted in the entry above. It means M1's zero-size refusal is unreachable through pages the library itself makes; it stays in the code as the plan's Interfaces state it, because a file from a city is not made by this library.

- Observation (M2, 2026-11-23): the first `./tools/verify` of the session, on a clean tree at `4dd7422` with no edit made, failed two checks; the second, started about six minutes later on the same tree with still no edit made, passed all six. The cause of the first was not established.
  Evidence: the first run (begun about 03:16Z) printed `verify: unit+web+services ... FAILED (167s)`, `verify: integration ... FAILED (130s)`, the other four `ok`, and `verify: 2 of 6 checks failed in 310s.`; the two tiers' summary lines were `49 failed, 3596 passed, 4 skipped, 4 xfailed, 2 warnings, 26 errors in 165.35s` and `27 failed, 1132 passed, 2 warnings, 7 errors in 129.48s`. The failures were in files this plan does not touch (`tests/web/test_city_briefing.py`, `test_coming_up_page.py`, `test_hearings_rss_flagged.py`, `tests/services/test_briefing_facts.py`, `test_committee_documents_*.py`, `tests/integration/test_050_migration.py`, `test_transcriber_role.py`, `test_transcript_pipeline.py` and others), none in M1's two test files, and the errors were of rows appearing and vanishing under a test: `UniqueViolation ... (municipality_id, external_id)=(1, BRIEFING_TEST_past) already exists`, `ForeignKeyViolation ... Key (calendar_event_id)=(55) is not present in table "city_calendar_events"`, `Key (meeting_id)=(1384) is not present in table "meetings"`. That is what a second process using the same throwaway database would produce (`tools/test-db` names the database after the checkout's path, so two runs in one worktree share `docket_test_9553e660`), but the session did not see such a process: when it looked, after the run, `pgrep -af "pytest|tools/verify"` listed none and no `docket_test_*` database existed. The second run (begun 03:22Z) printed `verify: unit+web+services ... ok (175s)` (`3664 passed, 5 skipped, 4 xfailed`), `verify: integration ... ok (127s)` (`1164 passed`), `verify: judge-fixtures ... ok (1s)`, `verify: workflows ... ok (0s)`, `verify: transcriber ... ok (11s)`, `verify: plans ... ok (0s)`, `verify: all 6 checks passed in 314s.` The second run is the starting state this milestone is measured from.

- Observation (M2, 2026-11-23): the new test file fails every test before the service exists.
  Evidence: with `tests/unit/test_minutes_viewer.py` written and no `src/docket/services/minutes_viewer.py`, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_minutes_viewer.py -q -p no:cacheprovider` printed `1 warning, 43 errors in 0.88s`. As in M1 they are errors and not failures because each test takes the module through a fixture that imports it (`ModuleNotFoundError` in the fixture's setup); the commit that holds this entry holds the tests in that state.

## Decision Log

- Decision: the viewer is a server-drawn picture of one page inside an ordinary docket.pub page, with no JavaScript PDF library and no pass-through of the PDF.
  Rationale: the scope brief settled this default and the author's measurements support it. A pass-through of the PDF with an inline header would open the file in a desk browser, but phone browsers do not honour `#page=`, so it would not open at the page on a phone. Framing the city's address is forbidden by the city's `x-frame-options: DENY`. A vendored pdf.js would be the repository's first vendored JavaScript library and still needs a pass-through of the file. `pypdfium2` 5.8.0 and `pillow` 12.2.0 are already pinned in `requirements.lock` (through `pdfplumber`), and one page draws in under 0.1 s. A picture works the same on a desk and on a phone.
  Date/Author: 2026-11-22, authoring (Claude), from the scope brief.

- Decision: the picture is put into the page itself as a `data:image/png;base64,` address, in the one response. There is no second route that serves the image.
  Rationale: one request from the reader is one code path and at most one request to the city. With a separate image route, the page and its image can be answered by two web processes, each with its own in-memory cache, which doubles the requests to the city. A page of about 340 to 480 kB of PNG is about 450 to 640 kB of HTML, which is acceptable for a page a reader opens deliberately. The repository sends no Content-Security-Policy header, so nothing blocks a `data:` image.
  Date/Author: 2026-11-22, authoring (Claude). Amended the same day by the entry below on lossless WebP: the picture stays inside the page, its format changes.

- Decision: "stores no copy of the PDF on the volume" is read as nothing persisted in Postgres or on disk. A bounded in-memory cache in each web process is allowed: at most 4 files and 40 MB, each kept at most one hour.
  Rationale: the scope brief's reading. The cache is what keeps reader traffic polite to the city: moving from page 5 to page 6 of the same minutes sends the city nothing. An hour bounds how stale a page can be if the city replaces a file.
  Date/Author: 2026-11-22, authoring (Claude), from the scope brief.

- Decision: a reader-triggered fetch is one attempt, with 5 seconds to connect, 10 seconds between bytes, 20 seconds in all, a 25 MB cap, no redirects followed, and `https` only. Requests to one host from one web process are at least one second apart, and a failed fetch is remembered for 60 seconds so that it is not repeated.
  Rationale: `GOALS.md` Constraints asks for at least one second between requests to a city. The `Dockerfile` starts gunicorn with its defaults (one synchronous worker and a 30-second timeout); the `Procfile` says `--timeout 120`; which one Railway runs is not written anywhere the author could read, so the bound is made to fit the smaller: one second of waiting plus 20 seconds of fetching is under 30. `CivicClerkAdapter.fetch_file` was not reused because it tries three times with a 30-second read limit and no size cap, which can exceed two minutes and hold the one worker. Not following redirects keeps the fetch on the address the allowlist passed. The one file measured is 0.7 MB; 25 MB is a guard, not an estimate.
  Date/Author: 2026-11-22, authoring (Claude). Superseded in its time figures the same day by the entry below on tighter bounds; one attempt, the cap, no redirects, `https` only, the one-second gap and the 60 seconds stand.

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
  Date/Author: 2026-11-22, authoring (Claude). Amended the same day: the line in `requirements.txt` is `pypdfium2>=5.0`, not `>=4.18` as the first version of this plan had it, because the lock holds 5.8.0, the author's measurements were all made on 5.8.0, and a regenerated lock should not be able to fall back a major version.

- Decision: debt row `D192` is not paid by this plan although M4 changes the file its trigger names; M5 writes on the row that the trigger fired and why it stays.
  Rationale: `D192` is two older minutes links in `partials/_vote_result_block.html` printed without the allowlist check. Paying it changes what Birmingham's and other cities' item pages print for a meeting whose minutes host is not on the allowlist, which needs a read of production's hosts that no factory session can make. This plan does not change either of those two links.
  Date/Author: 2026-11-22, authoring (Claude). The milestone numbers were M3 and M4 in the first version; the re-cut below moved them.

The entries from here down were made on 2026-11-22 while revising the plan against an outside review ("ExecPlan Review: Minutes Page Viewer", given to the author by the operator the same day, before any milestone ran). Each says what the review asked and what the author found when checking it.

- Decision: the first milestone is cut in two. M1 is now the fetch and the drawing; the service is M2; the old M2, M3 and M4 are M3, M4 and M5.
  Rationale: the review's changes add the single-flight and per-host design to the service and about a dozen tests across the three modules, and a milestone must fit one session with room to record its evidence. The fetch and the drawing are each testable alone; the service is testable with the fetch faked. Nothing had run when the cut was made, so no Progress entry had been ticked or snapshotted; the entries were rewritten in place and this entry is the record of the earlier cut: "M1: three modules that no page uses yet", then the route, the links, the close.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: the service holds no lock while it sleeps, fetches or draws. A short state lock guards its dictionaries only. Callers who ask for the same address while it is being fetched wait for that one fetch (an in-flight marker per address); the one-second gap is kept by a lock per host held across that host's wait and fetch; a caller who waits longer than `WAIT_S` gets the unavailable state and no failure is remembered for it.
  Rationale: the review's first high-priority finding, and it is right. The first version held one module lock across the sleep and the fetch, so with threads one slow file would make every other viewer request, cached pages and other cities included, wait five seconds and then show the unavailable state; it also changed the cache after releasing the lock. With one synchronous worker neither can happen, but nobody has read what production runs, and the fix the same review recommends for the stall (threads) is exactly what would expose it. The design is tested with two real threads (Validation, M2), each test worked against the old single-lock rule to see that it tells the two apart.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: the fetch bounds are tightened to 3 seconds to connect, 4 seconds between bytes and 8 seconds in all, and a fetch that failed because the host did not answer (a connection error, a timeout, a status of 500 or above, the deadline) is remembered for the whole host for 60 seconds, not only for the one address.
  Rationale: the review's second high-priority finding is that a slow city file holds a single synchronous worker, and with it the whole site. The plan cannot choose production's worker count (that is the operator's, and a debt row), but it can bound the stall. The first version's "20 seconds in all" was also wrong by its own rule: the deadline is looked at only between chunks, so a read can run a further read-timeout past it, 30 seconds with the old figures. With the new ones the fetch ends within 12 seconds (8 plus one 4-second read). The ten Mobile files seen are at most 1.6 MB and the one timed took 0.37 and 0.55 seconds from the development machine, so 8 seconds is generous. Remembering a dead host means a city that is down costs one stall a minute, not one stall for every different meeting a reader or a crawler asks for. A failure that is about the one file (a 404, a redirect, too big, not a PDF) is remembered for that address only.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: the picture is lossless WebP, with PNG as the fallback when the image library cannot write WebP. It stays inside the page as a `data:` address.
  Rationale: the review offered WebP at quality 85 as an optional saving. The author measured it: quality 85 halves the PNG, but lossless WebP is a fifth of it (about 70 to 90 kB a page against 340 to 480 kB) and is the same pixels, so the page shows exactly what the PDF library drew and no lossy step stands between the reader and the city's record. Every current browser shows WebP (Safari since 2020); a browser that cannot still shows the city's link above the picture and the alt text. Pillow's wheels carry their own WebP library, but nobody has seen the production image write one, so the format is tried in order and PNG is used if WebP raises.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: the drawing's scale is `max(width_px / page width, MIN_SCALE)`, then cut down so that neither side of the picture exceeds `MAX_SIDE_PX`; `WIDTH_PX` is 1200, `MIN_SCALE` 1.5, `MAX_SIDE_PX` 4000.
  Rationale: the review asked for a clamp and a pixel cap, and the author's script showed why (Surprises): the old rule's height was unbounded, and a wide sheet came out at 70 dots to the inch. The review's suggested clamp of 1.0 to 3.0 would shrink a letter page drawn at 1.96 only if it were set as an upper bound on small pages, which is not the risk; the risk is the long side, so the cap is on pixels per side. A 4000 by 4000 picture is 48 MB of pixels for a moment, which the process can hold. The CSS shows any picture at the column's width, so a wider picture is sharper, not larger on screen.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: the cache drops the least recently used file, not the oldest fetched; it keeps each file's page count beside its bytes; bytes are checked as a PDF before they are kept; and the entry just stored is never the one dropped.
  Rationale: all four are the review's and all four are cheap. A reader paging through one meeting should not lose it to three other fetches; a page past the end of a cached file is answered without opening the PDF; a body that is not a PDF never sits in the cache; and a test that lowers `CACHE_BYTES` below one file cannot make the file vanish before it is drawn. The hour still counts from the fetch, not from the last use.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: the viewer is offered, and answers, only for a minutes address that begins `https://` and passes the allowlist; a new predicate `is_viewer_url` in `src/docket/web/source_security.py` says so in one place, and the route and both templates ask it. A vote on a meeting whose safe address is `http://` keeps the direct link it has today.
  Rationale: the review found that the allowlist passes `http` while the fetch refuses it, so the templates would have linked such a vote to a viewer page that could only ever show the unavailable state. Fetching a city file over plain `http` from the web process was never wanted. The first version said this plan does not change `source_security.py`; it now adds one function there and changes nothing that exists.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: the fetch sends `User-Agent: docket.pub minutes viewer (+https://docket.pub)` and `Accept: application/pdf`, and accepts a body whose first 1,024 bytes contain `%PDF-`.
  Rationale: the review asked for the project's standard identifying User-Agent; there is none (the CivicClerk adapter sends the library default, three other fetchers send a browser's string because Granicus's CloudFront refuses anything else, `generic_cms.py` names docket.pub). A fetch made because a reader clicked should say who is asking. Mobile's endpoint answered it (Surprises). The cost is known and goes on a debt row: a future city behind a filter that refuses non-browser agents would show the unavailable state until someone decides otherwise. The PDF library opens a file with a few bytes before the header (Surprises), so the fetch does not refuse what the library would read.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: a hidden meeting's viewer page, seen by a signed-in admin, is sent with `Cache-Control: no-store`.
  Rationale: the review's point: a hidden meeting's page should not sit in a browser's disk cache for ten minutes.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: no second cache of drawn pictures, and no application rate limit.
  Rationale: the review suggested a cache of the last 16 to 32 drawn pages and a Cloudflare rate-limit rule. Drawing and encoding a page measured about 0.07 s, less than the meeting page's own queries, so a burst of clicks on one link costs little; a second cache would need its own rule for when a file is replaced or dropped. The rule at Cloudflare is the operator's to add in Cloudflare's dashboard and is named on the debt row about the worker (M5), with the path to match, for the day the logs show a crawler ignoring `robots.txt`.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision: three readings of production are the operator's, asked for before the merge, and no milestone waits on them: what the web service's processes are, whether the PDF library draws and writes WebP inside the running container, and which schemes and hosts the minutes addresses of votes with a page have.
  Rationale: the review's second and third high-priority findings ask for the first two before deploy, and the plan-author procedure asks for the third whenever a new predicate is laid over real rows. The author tried the first and was refused (Surprises); Docker is not installed in the development machine's WSL, so the image cannot be built there. The running production image already holds the same pinned libraries, so the container reading can be taken today, before any code lands. Each has a design that survives either answer (the stall is bounded and on a debt row; a library that will not load gives the unavailable state, WebP falls back to PNG; an `http` address keeps its direct link), which is why no milestone is ordered after them. The closing milestone writes into the `D188` row whichever readings are still not recorded in this plan.
  Date/Author: 2026-11-22, review revision (Claude).

- Decision (M1): each new test takes its module through a pytest fixture that imports it (`importlib.import_module`), not through an import at the top of the test file.
  Rationale: the plan's acceptance says the files fail "every test with an import error" before the modules exist. A module-level import would be one collection error per file and would show nothing per test; `skills/plan-execute/SKILL.md` asks for the import inside the test for that reason. The before state therefore reads `42 errors` (a `ModuleNotFoundError` in each test's fixture), not `42 failed`: every test fails by an import error, as the acceptance asks, and pytest counts a fixture's error as an error.
  Date/Author: 2026-11-23, M1 session (Claude).

- Decision (M1): the tests hold more than Validation lists, and nothing it lists is left out.
  Rationale: Validation's list was written before the code; the removal check and the Interfaces text name rules it does not. Added in `tests/unit/test_source_file.py`: the constants' values, an `HTTPS://` address in capitals is fetched, a `Content-Length` of exactly the cap and a streamed body of exactly the cap are accepted (the caps are "above", not "at"), a PDF mark that begins after byte 1,024 is refused, an error raised while the body is read (`ChunkedEncodingError`) is `host_down` with the response closed, a fetch that ends inside the deadline is returned, and the error keeps its reason. Added in `tests/unit/test_pdf_page.py`: the constants' values, two pages of the fixture are different pictures, the `width_px` argument is used, no writable format at all is `UnreadablePdf`, a PDF library that will not import is `UnreadablePdf` from both functions (`sys.modules["pypdfium2"] = None`), the module's top-level imports name neither library, and the three lock-and-close tests. 45 tests in all, 19 and 26.
  Date/Author: 2026-11-23, M1 session (Claude).

- Decision (M1): three small things the Interfaces text leaves open were settled inside the two modules. `SourceFileError` keeps its reason as the attribute `reason` as well as its message (M2's log line needs the reason). The PDF mark is looked for once, after the whole body is read, not as soon as 1,024 bytes are in hand. `render_page`'s work is in a private `_render`, and the module's lock is `pdf_page._lock`.
  Rationale: `reason` costs one line and saves M2 from parsing a message. Checking the mark early would stop a large body that is not a PDF sooner, but the caps already bound that body at 25 MB and 8 seconds, and one check after the loop is the plainer reading of "has `%PDF-` in its first 1,024 bytes"; a later session may move it without changing any test's meaning. `_lock` is named here because M1's tests read it and M2 must not take it itself: the service calls `page_count` and `render_page`, which take it.
  Date/Author: 2026-11-23, M1 session (Claude).

## Outcomes & Retrospective

As authored on 2026-11-22, nothing had been executed and there was no outcome to report. After M1 (2026-11-23): `docket.adapters.source_file.fetch_pdf` and `docket.analysis.pdf_page.page_count` and `render_page` exist with 45 unit tests, nothing calls them, and no reader sees any change yet; M2 (the service) is next. The closing milestone (M5) writes here what was built against the Purpose above; the retrospective and the move of this file to `plans/completed/` belong to the retro stage that runs after the last milestone, not to any milestone.

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

Its third branch (`v.minutes_url and not v.minutes_page_url`, "Read minutes ↗") and the "View full minutes ↗" link at line 134 print `minutes_url` with no allowlist check; those two are debt row `D192` and this plan does not change them. Its fourth branch builds a link to the meeting page from `municipality.slug` and `v.meeting_id`, so both names are already in the macro's reach: the item page includes the partial (`{% include %}`, which shares the page's variables) and the partial's own test passes `municipality`. The member page prints no minutes link. The meeting page's rail also has an "Official minutes" link to `meeting.minutes_url` (line 456); this plan does not change it.

`is_source_url_safe` is the Jinja name of `is_url_safe` in `src/docket/web/source_security.py`, registered in `create_app` (`src/docket/web/__init__.py` line 102: `app.jinja_env.globals["is_source_url_safe"] = source_security.is_url_safe`): true only for an `http` or `https` address whose host is, or is a subdomain of, a domain on a closed list (a static set that includes `civicclerk.com` and `granicus.com`, plus each active city's `adapter_config` `base_url` host). It returns False for None. Its unit tests are `tests/unit/test_source_security.py`, which pass an explicit `allowed_domains` set so that no database is read.

The meeting page's route is `meeting_detail(slug, meeting_id)` in `src/docket/web/public.py` (line 232). Its first lines are the 404 rule every meeting-scoped route repeats, and the transcript route below it (`meeting_transcript`, line 312) is the nearest model for a second page under a meeting:

    municipality = query.get_municipality(slug)
    if not municipality:
        abort(404)
    meeting = query.get_meeting(meeting_id)
    if not meeting or meeting.municipality_id != municipality["id"]:
        abort(404)
    if meeting.is_hidden and not session.get("admin_user"):
        abort(404)

`public.py` has no module logger as authored (`grep -n "getLogger" src/docket/web/public.py` prints nothing).

`src/docket/web/templates/transcript.html` is the model for the template: it extends `base.html`, fills `{% block title %}` and `{% block content %}`, opens with `<section class="hero hero--detail">` holding a `t-eyebrow` line, an `<h1 class="hero-title t-display">` with `meeting_label(meeting) or meeting.title`, and a `t-meta` paragraph with `← Back to the meeting`. `base.html` also has an empty `{% block head %}` inside `<head>`, a viewport meta tag, and loads `layout.css` (desk) and `mobile.css` (rules under 768 pixels).

Crawlers: `src/docket/web/crawlers.py` builds `/robots.txt` from `_ROBOTS_GENERAL` (the `User-agent: *` group: `Allow: /`, then `Disallow: /admin/`, `/search`, `/*?`) and a second group that disallows the whole site to named AI crawlers. The blog's routes set `X-Robots-Tag: noindex` on every response (`src/docket/web/blog.py`); that is the precedent for a header on one family of routes. There is no application rate limit and no Content-Security-Policy header.

Fetching: `CivicClerkAdapter` in `src/docket/adapters/civicclerk.py` has `fetch_file(url)`, used by ingest to read minutes files: three attempts, 10 seconds to connect and 30 to read, the whole body in memory, the `requests` library's default User-Agent, refused unless the address is under the adapter's own base. `src/docket/ai/transcripts/minutes.py` `download_minutes` is an existing example of a streamed download with a size cap. Neither is used by this plan; both are left alone. Three other fetchers (`city_calendar.py`, `committee_documents.py`, `src/docket/analysis/ocr/frame_io.py`) send a browser's User-Agent string, and a comment in `frame_io.py` says why: Granicus serves through CloudFront, which answers 403 to non-browser agents.

PDF libraries: `requirements.lock` pins `pdfplumber==0.11.9`, `pypdfium2==5.8.0` ("via pdfplumber") and `pillow==12.2.0` ("via pdfplumber, pytesseract"). `requirements.txt` names `pdfplumber` only. The `Dockerfile` installs from `requirements.lock`. `venv/bin/python -c "import pypdfium2, PIL; print(pypdfium2.PYPDFIUM_INFO, PIL.__version__)"` printed `5.8.0 12.2.0` in this worktree. Importing `pdfplumber` does not load `pypdfium2` (`'pypdfium2' in sys.modules` printed `False` after `import pdfplumber`), so the minutes reader's daily run on production is no evidence that the library's bundled binary loads in the production image; nobody has seen that, the operator's second reading asks, and the design degrades to the city's link if it does not.

What production runs: the `Dockerfile` ends by starting gunicorn (the web server program that runs the Flask app) with no option but the address, which means one worker process that answers one request at a time ("synchronous") and is killed if a request takes more than 30 seconds; the `Procfile` adds `--timeout 120`. Which one Railway uses, and whether the service's settings override both, is not written in the repository and no session can read it. This plan's bounds are made to hold under the smaller, and its service is written to be correct if requests are ever answered by several threads in one process.

### Terms this plan uses

The viewer, or the viewer page: the new page at `/al/<slug>/meetings/<id>/minutes/page/<n>/`. The city's file: the PDF at `meetings.minutes_url`. The allowlist: the closed list of hosts `is_url_safe` accepts. A viewer address: a minutes address that begins `https://` and passes the allowlist, which is what the new `is_viewer_url` says. The unavailable state: the viewer page when the city's file could not be fetched or read, which shows the city's link and no picture. A reader vote: a vote row with `minutes_reader` set. Single flight: when several callers want the same file at once, one of them fetches it and the others wait for that fetch. The host gap: the second that must pass between one request to a city's host ending and the next beginning.

### The states the viewer page must answer for

The viewer writes a sentence about a meeting's minutes ("Minutes, page 5 of 38"), so each state of the row and of the request is decided here. A slug that is not an active city, a meeting that does not exist or belongs to another city, and a hidden meeting seen by anyone but a signed-in admin are 404, by the same lines as the meeting page. A hidden meeting seen by a signed-in admin is shown, with `Cache-Control: no-store`. A meeting whose `minutes_url` is NULL or empty (an upcoming meeting, a cancelled one, one whose minutes are not posted) is 404. A `minutes_url` that is not a viewer address (it fails the allowlist, or it is `http`) is 404. A page below 1 or above 2,000 is 404. None of those sends the city a request. A page above the file's last page is 404 once the file is in hand. A file that cannot be fetched (the city is down, slow, answers an error or a redirect, the body is over 25 MB) or cannot be read as a PDF gives the unavailable state, as does a request that waited too long behind another. A file the city replaced after ingest read it is shown as it is now, at most an hour stale; the page says it is the city's file as docket.pub fetched it and makes no claim about a vote. Any query string on the request is ignored.

What the links do for each state of a vote: a vote with a page on a meeting whose minutes address is a viewer address links to the viewer; a vote with a page on a meeting whose address passes the allowlist but is `http` keeps the direct link to the city's file at the page, exactly as today; a vote with no page, or on a meeting with no minutes address or one outside the allowlist, prints what it prints today.

### Debt rows this plan accounts for

`D188` (the link downloads instead of opening at the page) is the row this plan pays. Its trigger has fired: the operator's observation is on the row, and the operator chose the viewer by stating this plan's goal. The row cannot be deleted by a milestone, because the proof is the operator's look after deploy; M5 rewrites it in place, under the same id, as the operator's ordered steps with "the pull request merges" as its trigger, and the operator deletes it after seeing page 5 on a desk and a phone. `git grep -n D188 -- . ':!plans/completed'` at authoring lists four places: the row itself, `docs/decisions/0128-...md` (a dated record; it keeps citing the row), `docs/specs/civicclerk-ingest.md` line 154 and `docs/specs/votes.md` line 37 (both edited by M5).

`D192` (two minutes links on the item page with no allowlist check) has as its trigger "the next change to that partial". M4 changes that partial. The Decision Log says why it is not paid; M5 writes that on the row, with the statement the operator can run to see production's minutes hosts.

`D7` (web modules that execute SQL) is not tripped as long as the new route calls services and executes no SQL; M3's acceptance checks that with a grep. The plan adds one function, `is_viewer_url`, to `docket.web.source_security` and changes nothing else in that module.

### Prose that states the old rule

The old rule is "the link is the city's own file address with `#page=<n>`". `git grep` for `#page=`, `own file address`, `as a download` and `content-disposition` outside `plans/completed` and `docs/superpowers` lists these, each an edit or a leave-alone. Edited by M4: the comment above the link in `meeting_detail.html` (line 285) and the header comment of `_vote_result_block.html` (lines 14 to 21), and the assertions in `tests/web/test_mobile_minutes_votes.py`. Edited by M5: `docs/specs/votes.md` lines 33, 34 and 37; `docs/specs/civicclerk-ingest.md` line 154; `docs/DEBT.md` row `D188`; the Status line of `docs/decisions/0128-...md`. Left alone: `page_link` and its docstring in `src/docket/models/vote.py` and its tests in `tests/unit/test_vote_dataclass.py` and `tests/unit/test_query_list_votes.py` (the function is unchanged and now feeds the viewer's link to the city and the direct link an `http` address keeps); `partials/source_anchor_button.html` and `tests/unit/test_source_anchor.py` (Birmingham's agenda anchors, a different link); `docs/specs/coming-up.md` and `public.py` line 1355 (the calendar feed's own header). `docs/SECURITY_CHECKLIST.md`, PDF Links, has the line "Don't proxy blindly — link to source PDFs, don't download and re-serve them"; M5 rewords it to say what the viewer does. The comment at `public.py` line 117 about single-worker gunicorn is about another cache and is left alone.

### Work in flight and identifiers

`plans/active/` held no other plan at authoring. In this tree the highest decision file is `0133` and the highest debt id is `D196`; those are observations, not allocations. A session that needs a new decision number or debt id takes the lowest number above every one spent in its own tree and on `origin/main` as its refs hold it at that moment (`ls docs/decisions`, `git grep -o "^| D[0-9]*" docs/DEBT.md`, and the same two against `origin/main`). A milestone session cannot list open pull requests; the retro stage after the last milestone does, and renumbers on a collision (debt row `D70` records this division).

## Plan of Work

### M1. Fetch one file, draw one page

Write the unit tests first, see them fail, then write the two modules described in Interfaces and Dependencies, and name the two libraries in the requirements files. Neither module opens a database connection, and nothing calls them yet.

`src/docket/adapters/source_file.py` holds `fetch_pdf`, one bounded GET with `requests`. `src/docket/analysis/pdf_page.py` holds `page_count` and `render_page`, which open PDF bytes with `pypdfium2`; `render_page` returns one page as picture bytes (lossless WebP, or PNG if WebP cannot be written) with the page count.

In `requirements.txt` add two lines after `pdfplumber>=0.10`: `pypdfium2>=5.0` and `pillow>=9.1`, with a one-line comment above them saying the minutes page viewer draws a page with them. In `requirements.lock` change only the comments under the two packages so that they read:

    pillow==12.2.0
        # via
        #   -r requirements.txt
        #   pdfplumber
        #   pytesseract

    pypdfium2==5.8.0
        # via
        #   -r requirements.txt
        #   pdfplumber

(the blank line between them is for this plan's layout; in the file each block stays where it is, in alphabetical order). Do not run `uv pip compile`. No check in the repository compares the lock against a hash (Surprises).

Tests, two new files. `tests/unit/test_source_file.py` fakes `requests.get` (monkeypatch `docket.adapters.source_file.requests.get` with a function that records its keyword arguments and returns a small stand-in response object that has `status_code`, `headers`, `iter_content(chunk_size)` and `close()`) and asserts what Validation and Acceptance, M1 lists for the fetch. `tests/unit/test_pdf_page.py` reads `tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf` for the real-file cases and, for pages of odd shapes, builds a one-page PDF in the test with the library itself:

    def _blank_pdf(width, height, rotation=0) -> bytes:
        pdf = pypdfium2.PdfDocument.new()
        page = pdf.new_page(width, height)
        if rotation:
            page.set_rotation(rotation)
        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        return buf.getvalue()

(the author ran exactly this to get the sizes in Validation). It asserts what Validation and Acceptance, M1 lists for the drawing.

### M2. Serve a page from memory, politely

Write `tests/unit/test_minutes_viewer.py` first, see it fail, then write `src/docket/services/minutes_viewer.py` as Interfaces and Dependencies describes: `page_view(minutes_url, page)` checks the page bound, takes the file from its cache or fetches it (single flight, the host gap, the failure memory), and draws the page. The module opens no database connection and no route calls it yet.

The tests replace the service's `_fetch`, `_now` and `_sleep` with a counting fake fetch and a fake clock whose `sleep(s)` advances it, call `minutes_viewer.clear()` before each test, and assert the single-threaded cases listed under Validation and Acceptance, M2. Three further tests start a real second thread (`threading.Thread`) and use a fake fetch that sets one `threading.Event` when it is entered and waits on another before returning; every wait and every `join` in them carries a timeout of 5 seconds so that a wrong implementation fails the test and cannot hang the run.

### M3. The viewer page

Write `tests/web/test_minutes_viewer.py` first and see it fail (the route does not exist, so every request is a 404 where 200 is expected). Then add `is_viewer_url` to `src/docket/web/source_security.py` and register it, add the route `minutes_page(slug, meeting_id, page)` to `src/docket/web/public.py` directly after `meeting_transcript`, the template `src/docket/web/templates/minutes_page.html`, a few CSS rules, and the robots line.

The predicate: in `source_security.py`, below `is_url_safe`, `is_viewer_url(url, allowed_domains=None)` returns True only when `url` is a string that begins `https://` in any letter case and `is_url_safe(url, allowed_domains)` is True. In `create_app` (`src/docket/web/__init__.py`), beside the line that registers `is_source_url_safe`, add `app.jinja_env.globals["is_minutes_viewer_url"] = source_security.is_viewer_url`. Add tests to `tests/unit/test_source_security.py`, passing `allowed_domains=frozenset({"civicclerk.com"})` as that file's other tests do: the Mobile address quoted in Context is a viewer address; the same address with `http://` is not, though `is_url_safe` says yes to it; the same address with `#page=5` on the end is; `HTTPS://MobileAL.api.civicclerk.com/x` is; `https://minutes.example.org/file.pdf` is not; None is not.

The route: the 404 lines quoted in Context; then 404 unless `meeting.minutes_url` is truthy and `source_security.is_viewer_url(meeting.minutes_url)` (import `source_security` from `docket.web` at the top of `public.py` if it is not already imported); then call `minutes_viewer.page_view(meeting.minutes_url, page)` (add `minutes_viewer` to the existing `from docket.services import ...` line). `NoSuchPage` is `abort(404)`. `Unavailable` renders the template with `view=None`, after logging a warning through a module logger (add `logger = logging.getLogger(__name__)` to `public.py`) whose message begins `minutes viewer: unavailable` and carries the city's slug, the meeting id and the page. Both renders get `municipality`, `meeting`, `page`, and `city_url=page_link(meeting.minutes_url, page)` (import `page_link` from `docket.models.vote`); the available render also gets `view` and `image_b64`, the picture's bytes encoded with `base64.b64encode(...).decode("ascii")`. Every response from the route, the 200s only (an abort keeps the site's 404 page), carries `X-Robots-Tag: noindex`. `Cache-Control` is `private, max-age=600` on the available page of a meeting that is not hidden, and `no-store` on the unavailable page and on any page of a hidden meeting. No response sets `Content-Disposition`. The route body contains no SQL and no `requests` call.

The template extends `base.html`. In `{% block head %}`: `<meta name="robots" content="noindex">`. Title: `Minutes, page {{ page }} — {{ meeting_label(meeting) or meeting.title }} — docket.pub`. Content, in this order, with these exact words and class names so that tests and later sessions agree:

A `<section class="hero hero--detail">` holding `<div class="t-eyebrow">Minutes · {{ meeting.meeting_date | format_date }}</div>`; an `<h1 class="hero-title t-display">` reading `Minutes, page {{ page }} of {{ view.page_count }}` when available and `Minutes, page {{ page }}` when not; a `<p class="t-meta">` with `<a class="link" href="{{ url_for('public.meeting_detail', slug=municipality.slug, meeting_id=meeting.id) }}">← Back to the meeting</a>` followed by ` · {{ meeting_label(meeting) or meeting.title }}`; and a `<p class="minutes-page-source">` holding the city's link, always present: `<a class="link minutes-city-file" href="{{ city_url }}" target="_blank" rel="noreferrer">The city's own file (PDF) ↗</a>` followed, when available, by the sentence ` This is page {{ page }} as docket.pub drew it from the city's file; the city's file is the record.` and, when not available, by ` docket.pub could not open the city's file just now. Open it and go to page {{ page }}.`

Then, when available only, a `<section class="feed minutes-page">` holding a `<nav class="minutes-page-nav t-meta">` with `<a class="link minutes-page-prev" rel="prev nofollow" href="...">← Page {{ page - 1 }}</a>` when `page > 1` and `<a class="link minutes-page-next" rel="next nofollow" href="...">Page {{ page + 1 }} →</a>` when `page < view.page_count` (each `href` from `url_for('public.minutes_page', ...)`), then `<img class="minutes-page-image" src="data:{{ view.mime }};base64,{{ image_b64 }}" width="{{ view.width }}" height="{{ view.height }}" alt="Page {{ page }} of the minutes of the {{ meeting.meeting_date | format_date }} meeting, as the city published it">`, then the same nav again below the picture.

CSS, appended to `src/docket/web/static/layout.css`: `.minutes-page-image { display: block; width: 100%; max-width: 1200px; height: auto; border: 1px solid var(--rule); background: #fff; }`, `.minutes-page-nav { display: flex; justify-content: space-between; gap: 16px; padding: 8px 0; }` and `.minutes-page-next { margin-left: auto; }`. `width: 100%` with `height: auto` is what makes the picture fit a phone's width, whatever the picture's own width in pixels; `mobile.css` needs no rule. The third rule keeps "Page 2 →" at the right edge on page 1, where it is the nav's only child and `space-between` alone would put it at the left. Where the links sit cannot be seen by a session, which has no browser; the session observes the rule in the stylesheet, and the look is the operator's step 2.

Robots: in `src/docket/web/crawlers.py` add the line `Disallow: /al/*/meetings/*/minutes/` to `_ROBOTS_GENERAL` after `Disallow: /*?`. Add to `tests/web/test_crawlers.py` a test `test_robots_keeps_crawlers_off_the_minutes_viewer` asserting that line is in the general group (taken the way `test_robots_welcomes_everyone_on_public_pages` takes it).

`tests/web/test_minutes_viewer.py` seeds, under external ids beginning `mv-test-` and removed before and after (model the helpers on `tests/web/test_mobile_minutes_votes.py`, whose `_meeting(cur, slug, ext, title, meeting_date, minutes_url=None, video_url=None)` inserts into `meetings` by city slug): a Mobile meeting dated 2026-11-03 with `minutes_url` equal to the Mobile address quoted in Context; a Mobile meeting with no `minutes_url`; a Mobile meeting whose `minutes_url` is `https://minutes.example.org/file.pdf`; a Mobile meeting whose `minutes_url` is the Mobile address with `http://` in place of `https://`; a Mobile meeting with the good address and `is_hidden` true; and a Birmingham meeting with `minutes_url` `https://bhamal.granicus.com/DocumentViewer.php?file=mv-test.pdf` (a host on the static allowlist), to show the route is not keyed on Mobile. An autouse fixture calls `minutes_viewer.clear()` and replaces `minutes_viewer._fetch` with a fake that appends its `url` argument to a list and returns the bytes of `tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf` (four pages), and `minutes_viewer._sleep` with a function that does nothing. For the hidden meeting seen by an admin, the test signs its client in the way `tests/web/test_hidden_meetings_admin.py` does (line 96: `with client.session_transaction() as sess: sess["admin_user"] = ...`, with a `SECRET_KEY` set on the app). The assertions are listed under Validation and Acceptance, M3.

### M4. The links

Change the tests first, see them fail, then the two templates. Both edits put the viewer link in front of the link that exists and leave that link, word for word, as the arm that follows.

In `meeting_detail.html` the block becomes:

    {% if is_minutes_viewer_url(vote.minutes_page_url) %}
    <div>
        <a class="link t-meta" rel="nofollow" href="{{ url_for('public.minutes_page', slug=municipality.slug, meeting_id=meeting.id, page=vote.source_page) }}">Minutes, page {{ vote.source_page }}</a>
    </div>
    {% elif is_source_url_safe(vote.minutes_page_url) %}
    <div>
        <a class="link t-meta" href="{{ vote.minutes_page_url }}" target="_blank" rel="noreferrer">Minutes, page {{ vote.source_page }} ↗</a>
    </div>
    {% endif %}

and the comment above it is rewritten to say the link opens docket.pub's viewer of that page, which shows the city's own file address; that an address the viewer cannot fetch (`http`) keeps the direct link to the city's file, which the city serves as a download; that a vote with no page, or on a meeting with no minutes link, has no `minutes_page_url`; and that both predicates say no to that as to an address outside the allowlist. In `_vote_result_block.html` a new branch goes into `vote_source_link` between the first branch (the video link) and the existing page branch:

    {%- elif is_minutes_viewer_url(v.minutes_page_url) -%}
      <a class="link t-meta" rel="nofollow"
         href="{{ url_for('public.minutes_page', slug=municipality.slug, meeting_id=v.meeting_id, page=v.source_page) }}"
         data-item-id="{{ item.id }}">
        Read minutes, page {{ v.source_page }}
      </a>

and the file's header comment (lines 14 to 21) is rewritten the same way. No existing branch is changed, and the "View full minutes" link is not touched. `minutes_page_url` is non-None only when `source_page` is set and the meeting has a `minutes_url`, and it is the meeting's address with a fragment added, so `is_minutes_viewer_url(minutes_page_url)` means "a vote with a page on a meeting whose minutes address is a viewer address", for any city. `municipality` and `v.meeting_id` are in the macro's reach (Context).

In `tests/web/test_mobile_minutes_votes.py`, add a helper `_viewer(meeting_id, page)` returning `f"/al/mobile/meetings/{meeting_id}/minutes/page/{page}/"` and change these tests, and no others: `test_a_reader_vote_links_to_its_page_of_the_minutes` (the one link whose text contains "Minutes" has text exactly `Minutes, page 5`, its tag holds `href="<viewer address for the main meeting, page 5>"`, and the block holds neither `#page=` nor the city's `MINUTES_URL`); `test_the_page_link_opens_in_a_new_tab_without_a_referrer`, renamed `test_the_page_link_opens_in_the_same_tab_and_is_not_followed` (the tag holds `rel="nofollow"` and no `target=`); `test_each_reader_vote_links_to_its_own_page` (viewer addresses for pages 4 and 2); the two no-link tests for a meeting with no minutes link and an unsafe address, and the two "renders as before" tests, each gaining `assert "/minutes/page/" not in block` beside its existing assertions; `test_the_item_pages_vote_link_names_the_page` (text exactly `Read minutes, page 5`, the viewer address for page 5, `rel="nofollow"`, no `target=`); `test_the_item_pages_history_row_prints_its_own_declaration_and_page` (text `Read minutes, page 4`, the viewer address for page 4); and `test_the_item_page_prints_no_page_link_for_an_address_that_is_not_safe` (gaining `assert "/minutes/page/" not in section`). The module docstring's sentence about "a link to the page of the city's Minutes file" is reworded to "a link to docket.pub's viewer of that page". Add one new test there, `test_a_reader_vote_on_an_http_minutes_address_keeps_the_citys_link`: a meeting seeded as the unsafe-address test seeds its own, with `minutes_url` equal to `MINUTES_URL` with `http://` in place of `https://`, and one reader vote with `source_page` 3; its block holds a link with text `Minutes, page 3 ↗` whose tag holds `href="<that http address>#page=3"` and `target="_blank"`, and `"/minutes/page/" not in block`. Add one test to `tests/web/test_minutes_viewer.py`, `test_the_meeting_pages_link_opens_a_viewer_page_that_answers`: seed a reader vote with `source_page` 2 on the good Mobile meeting (columns as `_vote` in `test_mobile_minutes_votes.py` inserts them), get the meeting page, take the `href` of the link whose text is `Minutes, page 2`, request it, and assert 200 and `Minutes, page 2 of 4` in the body.

### M5. The close

No code changes. Edit the documents so that each says, in the present tense, what M1 to M4 built, reading the code as built and not this plan's wording where they differ.

`docs/specs/votes.md`: lines 33 and 34 say the links open the viewer (words, address shape, `rel="nofollow"`, the condition `is_minutes_viewer_url`, and that an `http` address keeps the direct link); line 37's paragraph is replaced by a short section, "The minutes page viewer", that owns the viewer's behaviour: the route and its 404 rule, the states listed in Context, what the page prints (heading, the city's link and its two sentences, the neighbouring-page links, the picture, its format and its alt text), the headers, that nothing is stored, the cache and fetch bounds by reference to the constants in `src/docket/services/minutes_viewer.py` and `src/docket/adapters/source_file.py` (name the constants; do not restate values that the code owns beyond one mention), single flight and the host gap, the per-process nature of the cache and the gap, what a future city needs for the viewer to work (an `https` address on the allowlist that answers 200 itself and not a redirect, and that answers the viewer's own User-Agent), and the tests that pin it. `docs/specs/civicclerk-ingest.md`: the Known limits line 154 says a browser saves the city's file, which is why the vote's link opens the viewer (`docs/specs/votes.md`), and the paragraph on requests (line 38) gains a sentence that a reader's view of a minutes page is a second, separate fetch of a city's file, made by the web process through `source_file.fetch_pdf` under its own bounds and not by the adapter. `docs/specs/crawlers.md`: the general rule's list gains the viewer path and why (each crawl of a viewer address could be a request to the city), and the `X-Robots-Tag: noindex` header is named beside the blog's. `docs/specs/operations.md`: under Railway specifics, one paragraph with the operator's look after a deploy that changes the viewer (the steps under Validation and Acceptance) and the two log lines to search for when the unavailable state appears (`minutes viewer:` from the service, with the address, the reason and the milliseconds, and `minutes viewer: unavailable` from the route, with the city, the meeting and the page). `docs/specs/index.md`: the `votes.md` row's description gains the viewer. `ARCHITECTURE.md`: the Adapters component names `source_file.py` as a fourth read-only client outside the protocol, the Analysis component names `pdf_page.py`, and the Services component names `minutes_viewer.py` (no statement of its own; an in-memory cache). `docs/SECURITY_CHECKLIST.md`, PDF Links: the "Don't proxy blindly" line is reworded to say source PDFs are linked, never stored, and that the one place a city's PDF is fetched for a reader is the minutes page viewer, which fetches only a stored `https` address that passed the allowlist, follows no redirect, checks the body is a PDF, and serves a picture of one page beside the city's link.

Decisions: write one new record under `docs/decisions/`, in the format of `docs/decisions/DECISION_FORMAT.md` and numbered by the rule in Context, titled to the effect "A minutes vote's link opens docket.pub's viewer of the page, drawn in memory from the city's file, which is never stored", carrying the Decision Log entries above that proved durable (mechanism, no storage, fetch bounds and politeness, single flight and no lock across a fetch, the 200 unavailable state, `https` only, the layering). Change the Status line of `docs/decisions/0128-a-minutes-votes-link-is-the-citys-own-file-address-with-the-page-and-its-words-name-the-page.md` from `accepted` to `superseded by <the new number>`, and nothing else in that file.

`docs/DEBT.md`: rewrite the `D188` row in place, keeping the id. Its Item says the viewer is built and unobserved in a browser; its Trigger is "the pull request merges" followed by the operator's steps in the order Validation and Acceptance gives them, ending "the operator deletes this row after seeing page 5 on a desk and on a phone, or writes here what was seen instead". Read this plan's Surprises & Discoveries for entries that record the operator's three readings before the merge; each reading that has no entry there is written into the row as a step before the deploy, with its command, exactly as Validation and Acceptance gives it. On the `D192` row, append that its trigger fired on this plan's M4, that the two links were not changed, why, and the statement the operator runs to list production's minutes hosts: `SELECT split_part(split_part(minutes_url, '://', 2), '/', 1) AS host, count(*) FROM meetings WHERE minutes_url IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;`. Add one new row, numbered by the rule in Context, for each of these unless a milestone's record or an operator's reading shows it no longer holds. First, the viewer's fetch runs inside the web worker, so a city file that is slow to arrive holds that worker for up to about 13 seconds, at most once a minute for a host that is not answering; which gunicorn timeout, worker count and thread count production runs is not written down unless the operator's first reading recorded it (in which case the row states it); and nothing limits how fast one visitor may ask for viewer pages. Its trigger: the operator sees the site stall while a viewer page loads, or the logs show a crawler on `/al/*/meetings/*/minutes/page/*` despite `robots.txt`; what to weigh then is more workers or threads for the web service (the service is written for threads; each worker process has its own cache of up to 40 MB) and a rate-limiting rule on that path in Cloudflare's dashboard. Second, the viewer shows a picture of the page with no text a screen reader can read, the city's PDF being the only accessible form (trigger: an accessibility pass before public launch, or a reader asks). Third, the meeting page's rail link "Official minutes" for a Mobile meeting still downloads the file (trigger: the operator asks for it to open the viewer at page 1). Fourth, the viewer works for a city only when its minutes address is `https`, answers 200 itself (the fetch follows no redirect, and portals such as Granicus and Legistar often answer 302 to a signed address elsewhere), and answers a request whose User-Agent names docket.pub (Granicus's CloudFront refuses non-browser agents, by the comment in `src/docket/analysis/ocr/frame_io.py`); otherwise every viewer page for that city is the unavailable state (trigger: a second city's votes carry a page). Add a row for anything else a milestone's Surprises or Decision Log deferred.

Write Outcomes & Retrospective's outcome entry: what exists against the Purpose, and that the operator's look is still to come.

## Concrete Steps

Every command is run from the worktree root, `.claude/worktrees/minutes-open-at-the-vote-page` under the main checkout, with that worktree's `venv/`.

At the start and at the end of every milestone session:

    ./tools/verify

Expected last line: `verify: all 6 checks passed in <seconds>s.` and exit status 0. Record the lines it printed.

To run chosen test files (the form the author ran at authoring, where it printed `48 passed` for two existing files):

    DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest <files> -q -p no:cacheprovider

The inline `tools/test-db` builds the throwaway database and prints its address; `tools/test-db --drop` removes it afterwards, and `./tools/verify` builds and drops its own.

M1, after the modules exist (observed by the M1 session on 2026-11-23: the command printed exactly the line below):

    venv/bin/python -c "from pathlib import Path; from docket.analysis.pdf_page import render_page; r = render_page(Path('tests/fixtures/committee_documents/ps_minutes_2026-09-22.pdf').read_bytes(), 1); print(r.page_count, r.width, r.height, r.mime, r.image[:4], r.image[8:12])"

    4 1200 1553 image/webp b'RIFF' b'WEBP'

M1 to M3, the layering check (expected: no output from either; the first names only the files that exist by then):

    git grep -n "db_cursor\|db()\|execute(" -- src/docket/services/minutes_viewer.py src/docket/adapters/source_file.py src/docket/analysis/pdf_page.py
    git diff origin/main -- src/docket/web/public.py | grep "^+" | grep -n "execute(\|db_cursor\|requests\."

M5, after the edits (expected: `1` from the first; from the second, `docs/DEBT.md`, the `0128` record and the new decision record, and a spec file only where its sentence names the row as the operator's look still to come):

    grep -c "^| D188 " docs/DEBT.md
    git grep -ln "D188" -- docs src

Commit after each coherent step. Every commit in a milestone session changes this plan file (add the evidence as you go), a Progress line's text is never reworded, and git hooks are never bypassed.

## Validation and Acceptance

### M1

Before the modules exist, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_source_file.py tests/unit/test_pdf_page.py -q -p no:cacheprovider` fails every test with an import error; record the summary line. After, the same command's summary line names no failure, the one-line render command in Concrete Steps prints `4 1200 1553 image/webp b'RIFF' b'WEBP'`, the first layering grep prints nothing, `git diff origin/main -- requirements.lock | grep "^[+-][a-z]"` prints nothing (no line that begins with a package name is added or removed; comments only), and `./tools/verify` passes.

What `tests/unit/test_source_file.py` asserts, with `requests.get` faked. A body beginning `%PDF-` is returned whole, and the call was made with `stream=True`, `allow_redirects=False`, `timeout=(source_file.CONNECT_TIMEOUT_S, source_file.READ_TIMEOUT_S)` and a `headers` mapping whose `User-Agent` is `source_file.USER_AGENT` (which contains `docket.pub`) and whose `Accept` is `application/pdf`; the fake's `iter_content` was asked for chunks of `source_file.CHUNK_BYTES`. A body of a byte-order mark, a newline and then `%PDF-1.7` is returned whole. An `http://` address raises `SourceFileError` with `host_down` False and calls nothing. A 302 and a 404 raise with `host_down` False; a 500 and a 503 raise with `host_down` True. A `Content-Length` above the cap raises before any chunk is read (the fake's `iter_content` was never called). A `Content-Length` of `abc`, and one of `-5`, do not raise by themselves: with a small PDF body the bytes are returned. A body that passes the cap while streaming (set `source_file.MAX_BYTES` to 10 for the test; the function reads it at call time) raises with `host_down` False. A body whose first 1,024 bytes do not contain `%PDF-` raises with `host_down` False. A `requests.ConnectionError` and a `requests.Timeout` from the fake each become `SourceFileError` with `host_down` True. When the module's clock (`source_file._now`, monkeypatched) passes the deadline between two chunks, it raises with `host_down` True. In every case the fake response's `close()` was called if a response was returned.

What `tests/unit/test_pdf_page.py` asserts. On the fixture: `page_count(data) == 4`; `render_page(data, 1)` has `page_count == 4`, `width == 1200`, `height == 1553`, `mime == "image/webp"`, `image[:4] == b"RIFF"` and `image[8:12] == b"WEBP"`; opened with `PIL.Image.open(io.BytesIO(image))`, the picture's `size` is `(1200, 1553)` and it is not empty of ink (`getextrema()` of its greyscale conversion has a minimum below 128). Page 4 renders. Pages 0 and 5 raise `PageOutOfRange` whose `page_count` is 4. `render_page(b"%PDF-1.4 not a pdf", 1)` and `page_count(b"%PDF-1.4 not a pdf")` raise `UnreadablePdf`. On blank pages made by `_blank_pdf` (the sizes are in points, the results in pixels, each printed by the author's run of this rule): 612 by 792 gives width and height (1200, 1553), and the decoded picture's top-left pixel, converted to `RGB`, is `(255, 255, 255)` (a page with no background is drawn on white); 1224 by 792 gives (1836, 1188), the minimum scale at work; 3000 by 792 gives (4000, 1056) and 612 by 14400 gives (170, 4000), the cap on each side at work; 20 by 20 gives (1200, 1200); 612 by 792 with a rotation of 90 gives (1200, 928). With `pdf_page.FORMATS` monkeypatched to `(("NOPE", "image/nope", {}),) + the original tuple's last entry` (a format the image library does not know, then PNG), `render_page(fixture, 1)` has `mime == "image/png"` and `image[:8] == b"\x89PNG\r\n\x1a\n"`.

### M2

Before the module exists, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/unit/test_minutes_viewer.py -q -p no:cacheprovider` fails every test with an import error; record the summary line. After, its summary line names no failure, the first layering grep prints nothing, and `./tools/verify` passes.

What the single-threaded tests assert, with a fake clock starting at 100.0, a fake sleep that advances it, and the four-page fixture as the fetched bytes unless said otherwise. `URL` is `https://a.example/minutes.pdf`.

`page_view(URL, 2)` returns a `PageView` with `page == 2`, `page_count == 4`, `mime == "image/webp"` and bytes beginning `RIFF`, after one fetch of exactly `URL`; a second call for page 3 of the same address fetches nothing more. `page_view(URL, 0)` and `page_view(URL, 2001)` raise `NoSuchPage` with no fetch at all. `page_view(URL, 5)` raises `NoSuchPage` after one fetch; a repeat fetches nothing more and does not draw (with `docket.analysis.pdf_page.render_page` wrapped by a counter, the count stays 0 across both calls). With the clock advanced 3,601 seconds after a fetch, a further call fetches again.

Failures. A fetch that raises `SourceFileError("gone", host_down=False)` gives `Unavailable`; a second call for the same address 10 seconds later gives `Unavailable` with the fetch count still 1; a call for a different address on the same host at that moment is fetched (the count becomes 2); and a call for the first address 61 seconds after its failure fetches again. A fetch of `https://a.example/one.pdf` that raises with `host_down=True` gives `Unavailable`; a call straight after for `https://a.example/two.pdf` gives `Unavailable` with the fetch count still 1; a call for `https://b.example/three.pdf` is fetched; and 61 seconds after the failure `https://a.example/two.pdf` is fetched. Bytes that are not a PDF (the fake returns `b"%PDF-1.4 not a pdf"`) give `Unavailable`, are not kept, are not fetched again within 60 seconds, and are fetched again at 61.

The cache. Addresses A, B, C and D on four different hosts are each asked for once (four fetches); A is asked for again (still four); E, on a fifth host, is asked for (five); A again is still five, because A was used more recently than B and B was the one dropped; B again is six. (Under the first version's rule, oldest fetched first, E would have dropped A and the count after "A again" would be six; the test asserts five there.) With `CACHE_BYTES` set to one more than the fixture's length, A then B then A is three fetches. With `CACHE_BYTES` set to 10, `page_view(A, 2)` still returns the page and `page_view(A, 3)` straight after fetches nothing more: the entry just stored is never the one dropped.

The gap. `https://a.example/one.pdf` is fetched at 100.0; the clock is moved to 100.3; `https://a.example/two.pdf` makes the fake sleep record one call of 0.7 (`pytest.approx`), which leaves the clock at 101.0; `https://A.EXAMPLE:443/three.pdf` straight after adds one call of 1.0 (the host is compared without its port and without regard to case); `https://b.example/four.pdf` straight after adds no sleep. The recorded sleeps are `[0.7, 1.0]`.

What the three two-thread tests assert. In each, the fake fetch for the address named "slow" sets an event `entered` and then waits on an event `release` (timeout 5 seconds) before returning the fixture; any other address returns the fixture at once.

One fetch for two callers: a thread calls `page_view(slow, 1)`; the test waits for `entered`; a second thread calls `page_view(slow, 2)`; the test sets `release` and joins both. Both threads hold a `PageView` (pages 1 and 2) and the fetch count is 1.

No lock across a fetch: the test first calls `page_view(other, 1)` for an address on a different host, so that it is cached. A thread calls `page_view(slow, 1)`; the test waits for `entered`; then, with `release` still unset, the test itself calls `page_view(other, 2)` and gets a `PageView`. Then it sets `release` and joins. (Under the first version's single lock, held across the fetch, that call would have waited for the lock and raised `Unavailable`.)

A wait that times out is not a failure remembered: `minutes_viewer.WAIT_S` is set to 0.05. A thread calls `page_view(slow, 1)`; the test waits for `entered`; the test calls `page_view(slow, 1)` itself and gets `Unavailable`; it sets `release` and joins the thread, which holds a `PageView`; it calls `page_view(slow, 1)` again and gets a `PageView`, with the fetch count 1. (Had the timed-out wait been remembered as a failure, that last call would raise `Unavailable`.)

### M3

Before the route exists, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_minutes_viewer.py tests/web/test_crawlers.py tests/unit/test_source_security.py -q -p no:cacheprovider` fails the new tests; record the summary line. After, its summary line names no failure, both layering greps print nothing, and `./tools/verify` passes.

What `tests/web/test_minutes_viewer.py` asserts. For the good Mobile meeting, `GET /al/mobile/meetings/<id>/minutes/page/2/` is 200; the response has no `Content-Disposition` header, `X-Robots-Tag` is `noindex`, and `Cache-Control` is `private, max-age=600`; the body contains `Minutes, page 2 of 4`, an `<a` tag with class `minutes-city-file` whose `href` is the stored address followed by `#page=2` with `target="_blank"` and `rel="noreferrer"`, an `<img` with class `minutes-page-image` whose `src` begins `data:image/webp;base64,` and whose base64 text decodes to bytes beginning `RIFF`, a link to `/al/mobile/meetings/<id>/minutes/page/1/` and one to `.../page/3/`, a link back to the meeting page, and `<meta name="robots" content="noindex">`; and the fake fetch was called once, with exactly the stored address. Page 1 has no link to page 0 and page 4 has no link to page 5. The same request with `?url=https://evil.example/x.pdf&page=3` appended is the same page 2 and the fake's recorded addresses are all the stored one. Page 0 and page 2001 are 404 with the fake never called; page 5 is 404 with the fake called once. The meeting with no `minutes_url`, the meeting with the address outside the allowlist, the meeting with the `http` address, the hidden meeting seen without a sign-in, the good meeting's id under `/al/birmingham/`, and an unknown meeting id are each 404 with the fake never called. The hidden meeting's page 2, asked for by a signed-in admin, is 200 with `Cache-Control: no-store` and the picture. With the fake raising `SourceFileError`, the response is 200 with `Cache-Control: no-store` and `X-Robots-Tag: noindex`, contains `Minutes, page 2` and not `of 4`, contains the `minutes-city-file` link to the stored address with `#page=2` and the words `could not open the city's file just now`, and contains no `<img` with class `minutes-page-image`; and the log (pytest's `caplog`) holds a warning whose message begins `minutes viewer: unavailable` and contains the meeting's id. The Birmingham meeting's page 1 is 200 with the Birmingham address in its city link. A test reads `src/docket/web/static/layout.css` and finds `.minutes-page-next` with `margin-left: auto`.

### M4

Before the templates change, `DATABASE_URL=$(tools/test-db) venv/bin/python -m pytest tests/web/test_mobile_minutes_votes.py tests/web/test_minutes_viewer.py tests/web/test_vote_result_block.py -q -p no:cacheprovider` fails the changed and added tests, except the new `http` test, which passes before and after because that vote's link does not change; record the summary line and which failed. After, its summary line names no failure; `git diff origin/main -- src/docket/web/templates/partials/_vote_result_block.html` shows changes only in the header comment and one added branch in `vote_source_link` (no line of an existing branch is removed: outside the header comment the diff has no line beginning `-`); and `./tools/verify` passes.

### M5

`./tools/verify` passes. `grep -c "^| D188 " docs/DEBT.md` prints `1` and the row's Trigger cell begins with the merge and lists the operator's steps below. `ls docs/decisions | tail -3` shows one new record whose number is above every other in the directory, and `grep -n "^superseded by" docs/decisions/0128-*.md` prints one line naming it. `git grep -n "own file address" -- docs/specs` prints no sentence that says a vote's link is always the city's file address (a sentence saying the viewer page links to the city's own file address, or that an `http` address keeps the direct link, is expected), and `git grep -n "content-disposition" -- docs/specs/votes.md docs/specs/civicclerk-ingest.md` prints only sentences that give the city's download header as the reason the viewer exists. Each of the documents named in M5's Plan of Work has a diff against `origin/main` (`git diff origin/main --stat -- docs ARCHITECTURE.md` lists them).

### The operator's readings before the merge

These are not part of any milestone and no milestone waits on them. They read production as it runs today and write nothing. Each is run in the WSL terminal on the Legion, in the main checkout of docket-pub (not a worktree), where the `railway` command is signed in. Whoever takes one writes what it printed into Surprises & Discoveries, dated, as the operator's reading; M5 puts any reading still missing onto the `D188` row.

1. What the web service runs.

        railway ssh --service docket-web "ps -eo pid,ppid,rss,args"

   The lines that contain `gunicorn` show the command it was started with. One line for the master and one worker line under it, with no `--workers`, `--threads` or `--worker-class` in the command, is one synchronous worker: the debt row about the stall stands as M5 words it. `--timeout 120` in the command means Railway runs the `Procfile`'s line; its absence means the `Dockerfile`'s. Anything else (more workers, threads) is written down as seen and the debt row says so.

2. Whether the PDF library draws, and the image library writes WebP, inside the running container.

        railway ssh --service docket-web "python -c \"import io, pypdfium2 as p; d = p.PdfDocument.new(); d.new_page(612, 792); i = d[0].render(scale=2).to_pil(); b = io.BytesIO(); i.save(b, 'WEBP', lossless=True); print(p.PYPDFIUM_INFO, i.size, b.getvalue()[:4])\""

   Expected, and what the Python part printed in this worktree on 2026-11-22: `5.8.0 (1224, 1584) b'RIFF'`. The `railway ssh` wrapping and its quoting were not run by the author (the harness refused the author's one `railway ssh`). An error naming `pypdfium2` or a missing library means every viewer page in production would be the unavailable state: that is a finding for a new session before the deploy, not after. An error from `save` alone means the viewer will send PNG, which works.

3. Which addresses the votes with a page point at. With the production database's address in `DATABASE_URL` and writes switched off (`PGOPTIONS="-c default_transaction_read_only=on" psql "$DATABASE_URL"`):

        SELECT split_part(m.minutes_url, '://', 1) AS scheme,
               split_part(split_part(m.minutes_url, '://', 2), '/', 1) AS host,
               count(DISTINCT m.id) AS meetings, count(*) AS votes, max(v.source_page) AS last_page
        FROM votes v JOIN meetings m ON m.id = v.meeting_id
        WHERE v.source_page IS NOT NULL
        GROUP BY 1, 2 ORDER BY 4 DESC;

   The design assumes one row: `https`, `mobileal.api.civicclerk.com`, with `last_page` far below 2,000. A row with scheme `http` means those votes keep the direct link, by design. A row with a NULL scheme and host is votes with a page on a meeting with no minutes address, which print no link today and will print none. A host that is not under `civicclerk.com` or another allowlisted domain prints no link today and will print none.

### The operator's steps, after the pull request merges

These are not part of any milestone. No session takes them; M5 writes them into the `D188` row.

1. In the WSL checkout of docket-pub on the Legion (the main checkout, not a worktree), on a clean `main` that holds the merge: `scripts/deploy.sh --service docket-web`. There is no migration and the worker needs no deploy.
2. In the Windows browser, open `https://docket.pub/al/mobile/meetings/1071/` (the meeting of 2026-11-03), and on the vote on resolution 40-948-2026 click "Minutes, page 5". Expected: a docket.pub page headed "Minutes, page 5 of 38" showing a picture of page 5, with nothing downloaded; "The city's own file (PDF) ↗" above the picture; "← Page 4" at the left and "Page 6 →" at the right, above and below the picture, that move a page each; "← Back to the meeting" that returns. Go to page 1 and see "Page 2 →" at the right edge, not the left.
3. Narrow the window to phone width (about 375 pixels) and see the picture fit the width with no sideways scrolling; then do step 2 on a phone.
4. Open an item page of that meeting whose vote link reads "Read minutes, page <n>" and click it; the same viewer opens at that page.
5. If a viewer page instead says docket.pub could not open the city's file, run `railway logs --service docket-web` in the WSL terminal and look for lines beginning `minutes viewer:`; they give the address, the reason (a timeout from Railway to the city, a refusal, the PDF library not loading) and the time taken. Write what they say on the `D188` row; that is a finding for a new session.
6. When steps 2 to 4 are as expected, delete the `D188` row. The link to the city's file still downloads; that is the city's doing and is expected.

## Idempotence and Recovery

Every step is an edit to files in the worktree and can be repeated. There is no migration, no production write, and no request to any city in any milestone: tests fake the fetch, and a session must not fetch a city's file to "see it work". The in-memory cache is emptied by restarting the process; `minutes_viewer.clear()` empties it in tests. If the viewer misbehaves in production, reverting M4's two template changes restores the old links while leaving the viewer route in place; reverting the merge restores everything. `tools/test-db --drop` removes a throwaway database a failed run left behind.

If a milestone will not fit in its session, split its Progress entry in place as `plans/PLANS.md` says (add a new line for the remainder; do not reword the existing line), record the split in the Decision Log, and stop.

## Artifacts and Notes

What the author measured on 2026-11-22 is in Surprises & Discoveries: the city's response headers for file 3854 (693,774 bytes, forced download, framing denied, 0.37 and 0.55 seconds from the development machine), the drawing figures (38 pages; page 5 at 1,200 pixels wide is 1200 by 1977, a 479,644-byte PNG or a 90,240-byte lossless WebP, drawn and encoded in under 0.1 seconds), the sizes the scaling rule gives for odd pages, and that file 3854 is the minutes of the 2026-11-03 meeting (`/al/mobile/meetings/1071/`). The downloaded file is in the author's scratch directory, outside the repository, and is not committed: the tests use the four-page Birmingham committee PDF already in `tests/fixtures/committee_documents/` and blank pages the tests make themselves.

The worst case for one reader request, from the constants. The fetch: the deadline of 8 seconds is looked at between chunks, and one read can last 4 seconds more, so 12 seconds. With one synchronous worker nothing waits for anything else: up to 1 second for the host gap, 12 for the fetch, about 0.1 to draw, 13.1 seconds, under gunicorn's 30-second default. With threads a request can first wait up to `WAIT_S`, 13 seconds, behind another fetch of the same file or the same host: 26.1 seconds, still under 30. A lossless WebP of 70 to 90 kB is about 95 to 120 kB of base64 in the page.

The review this revision answers was a document the operator gave the author, "ExecPlan Review: Minutes Page Viewer (docket.pub)", dated 2026-11-22; it is not in the repository, and everything taken from it is restated in the Decision Log and the revision note below.

## Interfaces and Dependencies

Libraries: `requests` (already used by every adapter) for the fetch; `pypdfium2` and `pillow` (already installed) to draw a page. No new package is installed. `pypdfium2` and `PIL` are imported inside the functions of `pdf_page.py`, not at module top, so that a failure to load the library's binary becomes `UnreadablePdf` and the unavailable state, not an import error that takes down the site.

In `src/docket/adapters/source_file.py`:

    class SourceFileError(Exception):
        """The file could not be fetched within the bounds, or is not a PDF."""
        def __init__(self, reason: str, *, host_down: bool = False): ...   # keeps host_down as an attribute

    CONNECT_TIMEOUT_S = 3.0
    READ_TIMEOUT_S = 4.0
    DEADLINE_S = 8.0
    MAX_BYTES = 25 * 1024 * 1024
    CHUNK_BYTES = 16 * 1024
    USER_AGENT = "docket.pub minutes viewer (+https://docket.pub)"

    _now = time.monotonic   # replaced in tests

    def fetch_pdf(url: str) -> bytes:
        """One GET of a city's PDF, one attempt. SourceFileError unless the address is https,
        the answer is a 200, the body is at most MAX_BYTES, arrives within DEADLINE_S, and
        has b'%PDF-' in its first 1,024 bytes. Follows no redirect."""

It refuses, before any request, an address that does not begin `https://` in any letter case. It calls `requests.get(url, stream=True, allow_redirects=False, timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S), headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"})`. Any status but 200 raises; `host_down` is True when the status is 500 or above and False otherwise (a 3xx is refused as any other non-200, which is how a redirect is not followed). A `Content-Length` header is read with `int()` inside a `try`; a value that is not a number, or is negative, is ignored and the count while streaming decides; a value above `MAX_BYTES` raises before the body is read. The body is read with `iter_content(chunk_size=CHUNK_BYTES)`; after each chunk the running length is checked against `MAX_BYTES` and `_now()` against the deadline, which is counted from before the request was sent; the deadline passing raises with `host_down` True. Any `requests.RequestException` is raised as `SourceFileError` with `host_down` True. The response is closed in a `finally`. `MAX_BYTES` and the other constants are read at call time, so a test can change them. It imports nothing from `docket.services` or `docket.web`.

In `src/docket/analysis/pdf_page.py`:

    @dataclass(frozen=True)
    class RenderedPage:
        image: bytes
        mime: str          # "image/webp", or "image/png" when WebP could not be written
        page_count: int
        width: int
        height: int

    class UnreadablePdf(Exception): ...

    class PageOutOfRange(Exception):
        def __init__(self, page: int, page_count: int): ...   # keeps both as attributes

    WIDTH_PX = 1200
    MIN_SCALE = 1.5
    MAX_SIDE_PX = 4000
    FORMATS = (("WEBP", "image/webp", {"lossless": True}), ("PNG", "image/png", {}))

    def page_count(pdf_bytes: bytes) -> int:
        """How many pages the PDF has. UnreadablePdf if it cannot be opened."""

    def render_page(pdf_bytes: bytes, page: int, *, width_px: int = WIDTH_PX) -> RenderedPage:
        """Page `page` (1-based) of a PDF as a picture, with the file's page count."""

`render_page` opens the bytes with `pypdfium2.PdfDocument(pdf_bytes)`, takes `len(pdf)` as the count, and raises `PageOutOfRange` unless `1 <= page <= count`. It reads the page's size in points, `w, h = pdf[page - 1].get_size()` (the library gives the size as displayed, so a rotated page's width is its displayed width), raises `UnreadablePdf` if either is not above zero, and computes `scale = max(width_px / w, MIN_SCALE)` and then `scale = min(scale, MAX_SIDE_PX / w, MAX_SIDE_PX / h)`. It renders with `.render(scale=scale).to_pil()` (the library's default fill is opaque white), converts the image to mode `RGB` if it is not already, and saves it to an `io.BytesIO` in the first format of `FORMATS` (read at call time) that does not raise, taking `width` and `height` from the image's `size`; if every format raises, that is `UnreadablePdf`. It closes the page and the document. The bodies of both functions run under one module-level `threading.Lock`, because the PDF library is not safe to call from two threads at once. `PageOutOfRange` is raised as itself; any other exception from the libraries (a failed import included) is raised as `UnreadablePdf`.

In `src/docket/services/minutes_viewer.py`:

    MAX_PAGE = 2000
    CACHE_FILES = 4
    CACHE_BYTES = 40 * 1024 * 1024
    CACHE_TTL_S = 3600.0
    FAILURE_TTL_S = 60.0
    HOST_GAP_S = 1.0
    WAIT_S = 13.0
    SLOW_FETCH_S = 3.0

    _fetch = source_file.fetch_pdf   # replaced in tests
    _now = time.monotonic
    _sleep = time.sleep

    @dataclass(frozen=True)
    class PageView:
        page: int
        page_count: int
        image: bytes
        mime: str
        width: int
        height: int

    class NoSuchPage(Exception): ...
    class Unavailable(Exception): ...

    def page_view(minutes_url: str, page: int) -> PageView: ...
    def clear() -> None:   # forget every cached file, failure, in-flight marker, host lock and host time; for tests

The module's state is four dictionaries and one lock. `_files` is a `collections.OrderedDict` from an address to an entry of `(data, page_count, fetched_at)`, least recently used first. `_failures` maps a key to the time a failure was recorded; a key is an address, or `"host:" + host` for a host that did not answer. `_inflight` maps an address to the `threading.Event` of the fetch now running for it. `_hosts` maps a host to a pair of a `threading.Lock` and the time the last request to that host returned or raised. `_state_lock` guards all four and is held only while they are read or changed: never across `_sleep`, `_fetch`, or anything in `pdf_page`. A host is `(urlsplit(url).hostname or "").lower()`, which leaves out the port. Every constant, and `_fetch`, `_now`, `_sleep`, `pdf_page.page_count` and `pdf_page.render_page`, are read through their module at call time, so a test's replacement is seen.

`page_view` works in this order. Raise `NoSuchPage` unless `1 <= page <= MAX_PAGE`. Then find the file's entry, in a loop that runs at most twice. Under the state lock: if a failure for this address or for its host is remembered and younger than `FAILURE_TTL_S`, raise `Unavailable`; if `_files` holds this address and the entry is younger than `CACHE_TTL_S`, move it to the recently used end and use it; if `_inflight` holds this address, take its event and become a waiter; otherwise put a new event in `_inflight` and become the fetcher. A waiter, outside the lock, waits on the event for `WAIT_S`; if the wait times out it raises `Unavailable` and records nothing; otherwise it goes round the loop once more, and if that second pass finds neither a failure nor an entry it raises `Unavailable`. The fetcher, outside the state lock, takes the host's lock with `acquire(timeout=WAIT_S)`; if it is not acquired, the outcome is `Unavailable` with nothing recorded. Holding the host's lock it sleeps, with `_sleep`, whatever remains of `HOST_GAP_S` since that host's last request ended, calls `_fetch(minutes_url)`, records `_now()` as the host's last time whether the fetch returned or raised, and releases the host's lock. A fetch that took longer than `SLOW_FETCH_S` and succeeded is logged as a warning beginning `minutes viewer: slow fetch` with the address, the bytes and the milliseconds. On `SourceFileError` it logs a warning beginning `minutes viewer:` with the address, the reason and the milliseconds, and under the state lock records a failure for the address, and for the host too when `host_down` is True; the outcome is `Unavailable`. On success it calls `pdf_page.page_count(data)`; `UnreadablePdf` there is logged and recorded as a failure for the address, and the outcome is `Unavailable`, with the bytes kept nowhere. Otherwise, under the state lock, it stores the entry at the recently used end and then drops entries from the least recently used end, never the one just stored, until at most `CACHE_FILES` files and `CACHE_BYTES` bytes remain or only the new entry is left. Whatever the outcome, in a `finally`, under the state lock, it removes the address from `_inflight` and sets the event, so that no waiter is left waiting on a fetch that ended.

With the entry in hand (held in a local variable, so that nothing another thread drops can take it away): raise `NoSuchPage` if `page` is above the entry's page count, without opening the PDF. Otherwise call `pdf_page.render_page(data, page)` outside every lock of this module: `PageOutOfRange` becomes `NoSuchPage`; `UnreadablePdf` is logged, and under the state lock the address's entry is removed if it is still this one and a failure is recorded for the address, and it becomes `Unavailable`. Return a `PageView` from the rendered page. The service imports `docket.adapters.source_file` and `docket.analysis.pdf_page` and nothing from `docket.web`, `docket.db` or `docket.services.query`.

In `src/docket/web/source_security.py`:

    def is_viewer_url(url: object, allowed_domains: frozenset[str] | None = None) -> bool:
        """True iff url begins https:// and is_url_safe says yes: an address the minutes page viewer may fetch."""

registered in `create_app` as the Jinja global `is_minutes_viewer_url`.

In `src/docket/web/public.py`:

    @bp.route("/al/<slug>/meetings/<int:meeting_id>/minutes/page/<int:page>/")
    def minutes_page(slug, meeting_id, page): ...

The endpoint name is `public.minutes_page`; M4's templates build the address with `url_for('public.minutes_page', slug=..., meeting_id=..., page=...)`. The template is `src/docket/web/templates/minutes_page.html`, with the class names `minutes-city-file`, `minutes-page-image`, `minutes-page-nav`, `minutes-page-prev` and `minutes-page-next` given in the Plan of Work.

Revision note, 2026-11-22 (authoring): this is the first version of the plan, written from the operator's goal and a scope brief that the plan folds into Purpose and Context instead of committing it as a file. Deliberately left out, as the brief's out-of-scope list has it: Birmingham's minutes links and the `#page=N` links of `partials/source_anchor_button.html` (Birmingham votes carry no page and its files were not reported as downloading; the viewer is city-neutral by construction but nothing is switched over for a city without vote pages); the `p. N` marks on minutes-versus-video discrepancies, which are a different page number from a different table; highlighting the vote's lines, searching inside the minutes, or a text layer; storing rendered pages or PDFs in Postgres or on disk; a Content-Security-Policy or other site-wide headers; the adjacent Mobile rows `D183` and `D189`; the deploy and the look on a desk and a phone, which are the operator's and are written as steps for the `D188` row; and the open GitHub issues, none of which names this link. The author also left out, and names for the closing milestone's debt rows: the meeting page's rail link "Official minutes", which still goes to the city's file; and paying `D192`, whose trigger the links milestone fires. Two refinements of the brief's defaults are in the Decision Log: a page past the file's end is a 404 only after the file is in hand, and the fetch goes through a new city-neutral adapter module, not `CivicClerkAdapter.fetch_file`.

Revision note, 2026-11-22 (review revision, before any milestone ran): the operator gave the author an outside review of the first version and asked for the plan to be changed as appropriate and for any thread worth pulling to be pulled. The author checked each of the review's points against the tree, a scratch script, the public site and one request to the city, and the outcome of each is in Surprises & Discoveries and the Decision Log. Changed because the review was right: the service holds no lock across a sleep, a fetch or a draw, and callers of one file share one fetch (the first version's single lock would have stalled every viewer request under threads, and changed the cache outside the lock); a malformed `Content-Length` no longer escapes as an error; the fetch names docket.pub, asks for a PDF, reads 16 kB chunks, and compares hosts without the port; the drawing's size is bounded on both sides and a wide sheet is not drawn below 1.5; the cache drops the least recently used file, keeps the page count, and never holds bytes that are not a PDF; the viewer is offered and answered only for `https` addresses, through one predicate, and an `http` address keeps its direct link; a hidden meeting's page is `no-store`; "Page 2 →" stays at the right on page 1; the logs carry the address, the reason, the time, the meeting and the page; `requirements.txt` says `pypdfium2>=5.0`; the closing milestone's debt rows name the no-redirect and User-Agent limits for future cities and the Cloudflare rule. Changed because pulling a thread found more than the review asked: the fetch's time bounds were wrong by their own rule (a read can outlast the deadline) and are now 3, 4 and 8 seconds with the true worst case stated; a host that does not answer is remembered for a minute for every address on it; and the picture is lossless WebP, a fifth of the PNG and the same pixels, with PNG as the fallback. Checked and left as it was: the macro's reach of `municipality` and `v.meeting_id` (already there); the white background (the library's default, now tested); rotation (size and render agree, now tested); the lock file (no hash check); a second cache of drawn pages and an application rate limit (declined, with reasons). Found by the author and not in the review: file 3854 is the 2026-11-03 minutes, so the review's worry about an unmeasured target file is closed, and the operator's steps now name the meeting's address. Not settled by this revision, because a session cannot read production: what the web service runs, whether the PDF library loads in the container, and the schemes of the stored addresses; they are three operator's readings under Validation and Acceptance, with what each answer means. The first milestone was cut in two, so there are now five milestones. Validation clauses re-read against the changed rules: every clause that said `png`, `data:image/png`, `timeout=(5.0, 10.0)`, "the cache holds four files" in fetch order, or named M2 to M4 by their old numbers was rewritten; the cache-order case and the three two-thread cases were each worked under the old rule and the new, and the sizes in M1's drawing clause are the ones the author's run of the stated rule printed.

Revision note, 2026-11-23 (M1 session): M1 was executed. Progress has its tick; Surprises & Discoveries has the starting state, the before and after test lines, the acceptance commands as run, and the removal check (48 tried, 43 caught, the 5 free ones named); the Decision Log has three M1 entries (tests import their module through a fixture, the tests added beyond Validation's list, and `SourceFileError.reason`, the place of the PDF-mark check and `pdf_page._lock`); Concrete Steps says the render command's line was observed; Outcomes says what exists after M1. No interface the plan states was changed.
