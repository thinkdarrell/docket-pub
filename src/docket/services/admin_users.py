"""The admin's write to their own ``admin_users`` row."""
from __future__ import annotations

from docket.db import db_cursor


def set_display_name(admin_user_id: int, display_name: str | None) -> None:
    """Store the byline name of one admin; ``None`` clears it.

    ``admin_user_id`` is ``admin_users.id``, which the profile route reads
    from the session a login filled (plan
    `admin-profile-and-coverage-after-login`, M1).
    """
    with db_cursor() as cur:
        cur.execute(
            "UPDATE admin_users SET display_name = %s WHERE id = %s",
            (display_name, admin_user_id),
        )
