"""Tiny CRUD for the controlled outlets vocabulary."""
from __future__ import annotations

from docket.db import db_cursor


def create_outlet(*, slug: str, name: str, homepage: str | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO outlets (slug, name, homepage) VALUES (%s, %s, %s) RETURNING id",
            (slug, name, homepage),
        )
        return cur.fetchone()['id']


def update_outlet(outlet_id: int, *, name: str | None = None,
                  homepage: str | None = None) -> None:
    fields = {}
    if name is not None:
        fields['name'] = name
    if homepage is not None:
        fields['homepage'] = homepage
    if not fields:
        return
    assignments = ', '.join(f"{k} = %s" for k in fields)
    with db_cursor() as cur:
        cur.execute(
            f"UPDATE outlets SET {assignments} WHERE id = %s",
            tuple(fields.values()) + (outlet_id,),
        )


def deactivate_outlet(outlet_id: int) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE outlets SET is_active = FALSE WHERE id = %s", (outlet_id,))


def activate_outlet(outlet_id: int) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE outlets SET is_active = TRUE WHERE id = %s", (outlet_id,))
