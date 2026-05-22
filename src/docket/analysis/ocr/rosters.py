"""Runtime roster builder for the OCR pipeline.

al-muni stored Birmingham's roster in hardcoded ``LAYOUT_2021`` / ``LAYOUT_2025``
constants. docket builds the roster on demand from ``council_members``, scoped
by ``meeting_date`` against ``term_start`` / ``term_end``. The result is an
``OCRRoster`` carrying both the ``CouncilLayout`` (active-on-date members for
the spatial matcher) and a ``member_map`` (OCR string → council_member_id) so
the persistence layer in ``docket.services.video_ocr`` can resolve members
without re-querying or fuzzy-matching surnames.

CouncilLayout + LayoutRow live here (single source of truth); layout.py
re-exports them for back-compat with the OCR matcher's existing imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.db import db_cursor


# --- Layout dataclasses (moved here from layout.py — single source of truth) ---


@dataclass(frozen=True)
class LayoutRow:
    """One row of council members on the vote display (left column + optional right).

    Row order is preserved only as a convenience for building the
    canonical name list; it is not tied to pixel positions.
    """

    left: str
    right: str | None = None


@dataclass(frozen=True)
class CouncilLayout:
    """Active council on a given meeting date, as the OCR spatial matcher sees them."""

    city: str
    rows: tuple[LayoutRow, ...]
    max_members: int

    @property
    def member_names(self) -> list[str]:
        names: list[str] = []
        for row in self.rows:
            names.append(row.left)
            if row.right is not None:
                names.append(row.right)
        return names


@dataclass(frozen=True)
class OCRRoster:
    """Pair of (layout, member_map). Layout drives the OCR spatial matcher;
    member_map lets the persistence layer resolve OCR names to DB IDs."""

    layout: CouncilLayout
    member_map: dict[str, int]


def _to_initial_lastname(full_name: str) -> str:
    """``"Carole Smitherman"`` → ``"C. Smitherman"``. Defensive on single-token names."""
    tokens = full_name.split()
    if len(tokens) < 2:
        return full_name
    return f"{tokens[0][0]}. {tokens[-1]}"


def build_roster_for_meeting(meeting_id: int) -> OCRRoster:
    """Construct the OCR roster for a meeting from ``council_members``.

    Half-open date range (``>= term_start AND < term_end + 1 day``) avoids the
    BETWEEN-inclusivity foot-gun on transition days where one member's
    ``term_end`` and the successor's ``term_start`` are the same date.

    Determinism: ordered by ``name, district_id, id``. Layout uses left-column-only
    LayoutRows since we don't know the spatial pairing of left/right columns from
    DB data — and the OCR matcher reads ``.member_names`` (flattened), not row positions.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT cm.id, cm.name, cm.district_id
              FROM council_members cm
              JOIN meetings m ON m.municipality_id = cm.municipality_id
             WHERE m.id = %s
               AND m.meeting_date >= cm.term_start
               AND m.meeting_date < COALESCE(cm.term_end, m.meeting_date + INTERVAL '1 day')
             ORDER BY cm.name, cm.district_id, cm.id
            """,
            [meeting_id],
        )
        rows = cur.fetchall()

    member_map: dict[str, int] = {}
    layout_rows: list[LayoutRow] = []
    for r in rows:
        ocr_name = _to_initial_lastname(r["name"])
        # If two members produce the same OCR key (rare; same initial + same surname),
        # keep the first by ordering.
        if ocr_name not in member_map:
            member_map[ocr_name] = r["id"]
            layout_rows.append(LayoutRow(left=ocr_name))

    layout = CouncilLayout(
        city="birmingham",
        rows=tuple(layout_rows),
        max_members=len(member_map),
    )
    return OCRRoster(layout=layout, member_map=member_map)
