"""The admin's writes to the council roster.

The three statements behind /admin/members/add, /admin/members/<id>/edit
and /admin/members/<id>/deactivate. Each function is one transaction.
"""
from __future__ import annotations

from docket.db import db_cursor


def add_member(*, municipality_id: int, name: str, district_name: str,
               email: str | None, photo_url: str | None) -> None:
    """Insert an active member, under the city's district of that name.

    The district is looked up only when ``district_name`` is not empty; a
    name the city has no district for stores a NULL district.
    """
    with db_cursor() as cur:
        district_id = None
        if district_name:
            cur.execute(
                "SELECT id FROM districts WHERE municipality_id = %s AND name = %s",
                (municipality_id, district_name),
            )
            row = cur.fetchone()
            if row:
                district_id = row["id"]

        cur.execute(
            """
            INSERT INTO council_members
                (municipality_id, district_id, name, email, photo_url, active)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            """,
            (municipality_id, district_id, name, email, photo_url),
        )


def update_member(member_id: int, *, name: str, email: str | None,
                  photo_url: str | None, active: bool) -> None:
    """Set the four editable fields of one member. An unknown id changes nothing."""
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE council_members
            SET name = %s, email = %s, photo_url = %s, active = %s
            WHERE id = %s
            """,
            (name, email, photo_url, active, member_id),
        )


def deactivate_member(member_id: int) -> None:
    """Mark one member inactive (term ended). An unknown id changes nothing."""
    with db_cursor() as cur:
        cur.execute(
            "UPDATE council_members SET active = FALSE WHERE id = %s",
            (member_id,),
        )
