"""Citizen-facing labels for ``data_quality`` and ``processing_status``.

These ``str``-Enum classes mirror PostgreSQL's ``data_quality_enum`` and
``processing_status_enum`` (defined in migration 013) and carry a single
source of truth for the human-readable copy that surfaces on the
data-debt page and in its RSS feed.

Why an enum here, not a Jinja global:

- ``filters.py`` is reserved for *functional* transformations
  (URL encoding, date formatting, dollar tier metadata, etc.). UI copy
  doesn't belong there.
- Inlining the dict in two templates (HTML + RSS) is a drift trap —
  the strings would slowly diverge.
- The enum makes the labels Python-testable without rendering a
  template, and any future surface (admin queue, JSON API,
  notifications) gets the same translation for free.

Use from a route::

    from docket.models.data_quality import friendly_label
    friendly = friendly_label(item)  # item is a dict from list_data_debt_items

Or directly on an enum instance::

    DataQuality.NO_TEXT_LAYER.label

Surfaces consume the precomputed string via
``item["friendly_label"]`` — no template-side enum knowledge required.
"""

from __future__ import annotations

import enum


class DataQuality(str, enum.Enum):
    """Mirror of ``data_quality_enum`` (migration 013).

    Inherits from ``str`` so the values round-trip cleanly through
    JSONB and string-typed DB columns and still compare equal to the
    raw SQL strings (``DataQuality.OK == "ok"`` is True).
    """

    OK = "ok"
    NO_TEXT_LAYER = "no_text_layer"
    NO_AGENDA_TEXT = "no_agenda_text"
    EMPTY = "empty"
    FOREIGN_LANGUAGE = "foreign_language"

    @property
    def label(self) -> str:
        """Citizen-friendly explanation. Single source of truth."""
        return _DATA_QUALITY_LABELS[self]


_DATA_QUALITY_LABELS: dict[DataQuality, str] = {
    DataQuality.OK: "Machine-readable.",
    DataQuality.NO_TEXT_LAYER:
        "Source PDF is scanned — needs OCR before we can read it.",
    DataQuality.NO_AGENDA_TEXT:
        "Agenda body never reached our archive — likely a fetch error.",
    DataQuality.EMPTY: "Source document came back empty.",
    DataQuality.FOREIGN_LANGUAGE:
        "Source text is not in English — translation pending.",
}


class ProcessingStatus(str, enum.Enum):
    """Mirror of ``processing_status_enum`` (migration 013).

    Only ``failed_permanent`` carries a citizen-facing label today —
    every other status is internal pipeline state. The enum exists for
    symmetry (and so admin views can reuse the same pattern).
    """

    PENDING = "pending"
    PROCEDURAL_SKIPPED = "procedural_skipped"
    DATA_QUALITY_SKIPPED = "data_quality_skipped"
    EXTRACTED = "extracted"
    REWRITTEN = "rewritten"
    BADGED = "badged"
    COMPLETED = "completed"
    FAILED_RETRY = "failed_retry"
    FAILED_PERMANENT = "failed_permanent"
    CROSS_STAGE_CONFLICT = "cross_stage_conflict"
    WITHDRAWN = "withdrawn"

    @property
    def label(self) -> str:
        """Citizen-friendly label, or empty string for internal states."""
        return _PROCESSING_STATUS_LABELS.get(self, "")


_PROCESSING_STATUS_LABELS: dict[ProcessingStatus, str] = {
    ProcessingStatus.FAILED_PERMANENT:
        "Automated reading gave up after multiple retries.",
}


_FALLBACK_LABEL = "Source content needs review."


def friendly_label(item: dict) -> str:
    """Return the citizen-facing label for a data-debt row.

    Precedence (matches the previous template-local macro behavior):

    1. ``data_quality`` is set and not ``ok`` → the data-quality label.
    2. ``processing_status`` is ``failed_permanent`` → that label.
    3. Otherwise → generic "needs review" fallback.

    Robust to:

    - Either string values (DB → dict round-trip via psycopg's
      ``::text`` cast in :func:`docket.services.query.list_data_debt_items`)
      or actual enum instances.
    - Unknown values falling outside the enum (e.g., a future enum
      value seeded before this module is updated). Returns the
      generic fallback rather than raising — production data debt
      MUST render even if the enum drifts.
    """
    dq_raw = item.get("data_quality")
    ps_raw = item.get("processing_status")

    if dq_raw and dq_raw != "ok" and dq_raw != DataQuality.OK:
        try:
            return DataQuality(dq_raw).label
        except ValueError:
            return _FALLBACK_LABEL

    if ps_raw == "failed_permanent" or ps_raw == ProcessingStatus.FAILED_PERMANENT:
        return ProcessingStatus.FAILED_PERMANENT.label

    return _FALLBACK_LABEL
