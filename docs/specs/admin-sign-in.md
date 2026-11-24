# Admin sign-in and the admin session

How an admin signs in to `/admin/`, what the session then holds, and which routes read which part of it. Present tense. The admin area's pages themselves have no spec; `calibration.md` and `meeting-types.md` cover the two that do.

## Signing in

`POST /admin/login` (`src/docket/web/auth.py`) reads `username` and `password` from the form, selects the `admin_users` row with that username, and checks the password against the row's `password_hash`. On a match it clears the session and stores two keys, then redirects to the `next` query parameter when that is a path on this site (it begins with one `/`), and to `/admin/members/` otherwise. On no match it shows the form again with status 200 and the message "Invalid username or password." `POST /admin/logout` clears the session and redirects to the form.

The session is Flask's signed cookie. The application sets no permanent lifetime for it, so it lasts as long as the browser keeps the cookie.

## The two keys

`admin_user` is the username, a string. `admin_user_id` is `admin_users.id`, an integer. They are not interchangeable: a statement that compares `admin_users.id`, or writes a column that references it, is given `admin_user_id` and never `admin_user`.

`admin_user` is what says a request is signed in. The guard of the admin blueprint (`require_login` in `src/docket/web/admin.py`), the `login_required` decorator of `auth.py` and the guard of `src/docket/web/admin_transcripts.py` each send a request whose session has no `admin_user` to `/admin/login?next=<the path asked for>`, and the public meeting pages show a hidden meeting only to a session that has it. Routes that record who acted write it as the actor's label.

`admin_user_id` is read where a row is tied to the admin:

- `GET /admin/profile` shows the username and display name of the `admin_users` row with that id.
- `POST /admin/profile/display-name` stores the posted name, stripped, on that row; an empty name is stored as NULL.
- `POST /admin/coverage` stores it as the new coverage entry's `author_id`. An entry saved with `publish_now` is published under that admin's display name, or the username when the display name is NULL; the byline is copied at first publish and a later change of display name does not alter it.
- `POST /admin/meetings/<id>/type` and `POST /admin/meetings/<id>/hide` pass it to the service as the admin who acted.

## A session without the id

A login always stores both keys, so a session with `admin_user` and no `admin_user_id` comes only from a cookie older than the second key or from a session built by hand. The three profile and coverage routes above answer such a session with a redirect to `/admin/login`, before reading the form and with no `next` parameter (two of the three are POST routes, which the GET after a login could not reach). The session is not cleared, so the other admin pages still answer it; signing in again stores both keys. Nothing is flashed or logged when this happens. The meeting-type and hide routes have no such guard and pass on an absent id as none.

## How it is checked

`tests/integration/test_auth_session.py` signs in through the form and asserts both keys. `tests/integration/test_admin_profile.py` and `tests/integration/test_admin_coverage.py` sign in the same way, by posting to `/admin/login`, so their sessions hold what a login stores; only the test of a session without the id writes a session by hand. The shared fixture `authed_admin_client` in `tests/integration/conftest.py` writes `admin_user` alone, which suits a route that reads only the label and would not suit one that reads the id.

## Known limits

Not seen on production: no session has signed in there, and the operator's look after the deploy is row `D216` of `docs/DEBT.md`. The admin POST routes carry no CSRF token (`D14`). A session whose `admin_user_id` names a row that no longer exists is not handled apart from one that does; no code deletes an `admin_users` row.
