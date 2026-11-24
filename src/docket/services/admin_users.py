"""The admin's write to their own ``admin_users`` row."""
from __future__ import annotations

from docket.db import db_cursor


def set_display_name(admin_user_id, display_name: str | None) -> None:
    """Store the byline name of one admin; ``None`` clears it.

    ``admin_user_id`` goes to the statement as given, with no conversion and
    no check: the route passes whatever its session holds under
    ``admin_user`` (plan `admin-routes-call-services` carried that as it
    found it).
    """
    with db_cursor() as cur:
        cur.execute(
            "UPDATE admin_users SET display_name = %s WHERE id = %s",
            (display_name, admin_user_id),
        )
