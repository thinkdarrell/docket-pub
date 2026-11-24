# 0137 — Admin routes ask services; a service says not-found by its return value; a transaction block moves whole

## Decision

`src/docket/web/admin.py` executes no statement and does not import `docket.db`: every read and write behind an `/admin/` route is a function under `src/docket/services/`, and `tests/unit/test_admin_module_has_no_sql.py` fails when one comes back. A service says "no such row" by its return value (`None`, or `False` where the function otherwise returns a bool) and the route calls `abort(404)`; a service does not import Flask and raises no exception class of its own for this. When SQL moves out of a web module, each `with db()` or `with db_cursor()` block becomes one service function that opens one transaction with the same statements in the same order; blocks are not merged and not split.

## Rationale

`ARCHITECTURE.md` says the service layer owns every transaction, and row `D7` of `docs/DEBT.md` listed the web modules that broke the rule. `admin.py` was the largest (27 transaction blocks, 54 statements) and the row went overdue for it twice, because two plans edited the module and neither moved its SQL nor said it was leaving it. Plan `admin-routes-call-services` moved all of it at the operator's stated goal, with no response changed. The four other modules stay on the row.

Not-found as a return value, and not an exception or an `abort` inside the service: a service that aborts must import Flask, which `ARCHITECTURE.md` rules out (a service does not render and nothing under `services/` imports from `web/`), and the worker and the CLIs call services too. A new exception class would be a second convention beside the one `docket.services.query` already had, where a missing row is `None` and the caller aborts. The convention is safe only because of what was read in the module before the move: in every not-found path the check comes before any write, so returning early writes nothing, exactly as the rollback after `abort` did. A later function that can find the row missing after it has written cannot use the early return: `db()` commits when its block ends without an exception, so what it had written would stay. `add_manual_badge` returns `bool | None` (`None` not found, `True` inserted, `False` already attached); a three-valued string was proposed and not taken, since the route is its one caller and one convention for every function is easier to hold.

A block moves whole because a transaction boundary is behaviour. The errors-queue retry reads an item, updates it and writes its audit row in one transaction; split, an audit row could exist without its update. Merging two blocks changes what a failure between them leaves behind, which is why the add-member form still asks for each city's district names in a transaction of its own, and why the AI dashboard's two summaries are two functions. Three tidyings were allowed because their observable result is identical, and no others: two pairs of lookups that differed only in columns became one function each, and the explicit `conn.commit()` of the hide and unhide blocks was dropped, since `db()` commits when its block ends.

Homes. Reads go in `src/docket/services/query.py`, under the comment heading `Reads behind the admin pages (docket.web.admin)`; writes go to the service that already wrote the table (`badges.py`, `non_meetings.py`, `video_ocr.py`) and, where none did, to `council_members_writer.py`, `admin_users.py` and `errors_queue.py`. `query.py` grew from 4,294 lines to 4,689, and whoever pays `D7` for the other modules weighs a module of its own for the admin reads first. One import is inside a function on purpose: `rescan_meeting_ocr` imports `docket.services.video_ocr` when it is called, because that module loads numpy, OpenCV and pytesseract when imported and, named at the top of `admin.py`, made every web process load them at start (188 more modules and 33 MB more resident memory on the development machine). Do not hoist it. What it leaves is row `D214`.

"Moved unchanged" was checked, not assumed. Route tests for paths that had none were written and passed against the old module before each move; no existing admin test file was edited; and every rule of every moved statement was taken out of a copy of the code, one at a time, to see that a service test failed: 242 of 253 removals did, and the eleven that did not are each named in the plan with why no test can tell the clause from its absence (a column default, a cascade, a cast the driver undoes, a guard a second guard repeats, an order the planner already gives). The move also carried two defects it did not mend, because mending is a change of behaviour: three routes pass a username where `admin_users.id` is expected and fail on a real login (`D212`), and the coverage list can label a subject with another table's title (`D213`).

The pin is one test on one module, read with Python's `ast`. It is not the `boundary-lint` capability of `docs/capabilities/index.md`, which would hold the rule for every web module and is still only specced.

## Date

2026-11-24, plan `admin-routes-call-services`, at the operator's stated goal ("start on d7 for admin.py").

## Status

accepted
