"""Unit tests for F5 fix-up additions.

Covers the small, pure-Python pieces of the F5 fix-up that don't need a
Flask app or DB:

- ``cdata_safe`` Jinja filter (Override 4 / S-NEW-2): ``]]>``
  sequences inside RSS CDATA blocks must split into
  ``]]]]><![CDATA[>`` so scraped municipal text can never break out
  of the section and produce invalid XML.
- ``DataQuality`` / ``ProcessingStatus`` enum (Override 3 / R3):
  each enum value carries a citizen-friendly ``.label`` property; the
  enum is the single source of truth, replacing the previous
  template-local ``friendly_labels`` dict.
- Module-level Locks on the public-route caches (Override 2 / R1 +
  D4): structural test that the locks exist and are
  ``threading.Lock`` instances.
"""

from __future__ import annotations

import threading
import xml.etree.ElementTree as ET

import pytest

from docket.models.data_quality import (
    DataQuality,
    ProcessingStatus,
    friendly_label,
)
from docket.web import public as public_module
from docket.web.filters import cdata_safe


# ---------------------------------------------------------------------------
# Override 4 / S-NEW-2 — cdata_safe
# ---------------------------------------------------------------------------


def test_cdata_safe_passes_through_clean_input():
    assert cdata_safe("hello world") == "hello world"


def test_cdata_safe_handles_none():
    assert cdata_safe(None) == ""


def test_cdata_safe_coerces_non_string():
    assert cdata_safe(42) == "42"


def test_cdata_safe_neutralizes_close_sequence():
    """The textbook escape: ``]]>`` becomes ``]]]]><![CDATA[>``."""
    out = cdata_safe("trouble: ]]> in the middle")
    assert "]]>" not in out.replace("]]]]><![CDATA[>", "")
    assert out == "trouble: ]]]]><![CDATA[> in the middle"


def test_cdata_safe_handles_multiple_close_sequences():
    out = cdata_safe("a]]>b]]>c")
    assert out.count("]]]]><![CDATA[>") == 2


def test_cdata_safe_output_roundtrips_through_xml_parser():
    """The filter's whole point: wrapping the sanitized output in a
    fresh CDATA section must produce well-formed XML, even when the
    original input contained the close sequence."""
    raw_input = "Public Hearing on Item ]]> with rogue tokens"
    sanitized = cdata_safe(raw_input)
    xml_doc = (
        '<?xml version="1.0"?>'
        f"<root><desc><![CDATA[{sanitized}]]></desc></root>"
    )
    root = ET.fromstring(xml_doc)
    desc = root.find("desc")
    assert desc is not None
    # The original tokens round-trip — readers see the original
    # content, not the ``]]]]><![CDATA[>`` artifact.
    assert desc.text == raw_input


# ---------------------------------------------------------------------------
# Override 3 / R3 — DataQuality + ProcessingStatus enums
# ---------------------------------------------------------------------------


def test_data_quality_enum_str_compat():
    """``str``-mixin: the enum members compare equal to their raw SQL
    string values so DB-rounded-tripped strings work uniformly."""
    assert DataQuality.OK == "ok"
    assert DataQuality.NO_TEXT_LAYER == "no_text_layer"


def test_data_quality_label_no_text_layer():
    assert "OCR" in DataQuality.NO_TEXT_LAYER.label


def test_data_quality_label_no_agenda_text():
    assert "fetch" in DataQuality.NO_AGENDA_TEXT.label.lower()


def test_data_quality_label_empty():
    assert "empty" in DataQuality.EMPTY.label.lower()


def test_data_quality_label_foreign_language():
    assert "translation" in DataQuality.FOREIGN_LANGUAGE.label.lower()


def test_processing_status_failed_permanent_label():
    assert "gave up" in ProcessingStatus.FAILED_PERMANENT.label.lower()


def test_processing_status_internal_states_have_empty_label():
    """Only ``failed_permanent`` carries a citizen-facing label."""
    assert ProcessingStatus.PENDING.label == ""
    assert ProcessingStatus.EXTRACTED.label == ""
    assert ProcessingStatus.COMPLETED.label == ""


# ---------------------------------------------------------------------------
# friendly_label() helper — used in both HTML and RSS routes
# ---------------------------------------------------------------------------


def test_friendly_label_uses_data_quality_first():
    item = {"data_quality": "no_text_layer", "processing_status": "pending"}
    assert "OCR" in friendly_label(item)


def test_friendly_label_falls_back_to_failed_permanent():
    item = {"data_quality": None, "processing_status": "failed_permanent"}
    assert "gave up" in friendly_label(item).lower()


def test_friendly_label_ignores_ok_data_quality():
    """``ok`` should not surface a debt label — the row shouldn't even
    be in the queue, but the helper guards anyway."""
    item = {"data_quality": "ok", "processing_status": "completed"}
    # No data-quality issue + status not failed_permanent → generic.
    assert friendly_label(item) == "Source content needs review."


def test_friendly_label_unknown_enum_value_returns_fallback():
    """A future enum value not yet known to this module must NOT crash."""
    item = {"data_quality": "freshly_minted_state"}
    assert friendly_label(item) == "Source content needs review."


def test_friendly_label_handles_missing_keys():
    item = {}
    assert friendly_label(item) == "Source content needs review."


# ---------------------------------------------------------------------------
# Override 2 / R1 + D4 — locks on both caches
# ---------------------------------------------------------------------------


def test_overview_lock_exists_and_is_a_lock():
    """Symmetric thread safety: the city-overview cache has a lock."""
    assert hasattr(public_module, "_overview_lock")
    # Creating a fresh Lock just to grab its type — Lock is a factory,
    # not a class, so isinstance against the result is the canonical check.
    lock_type = type(threading.Lock())
    assert isinstance(public_module._overview_lock, lock_type)


def test_rss_lock_exists_and_is_a_lock():
    """The RSS cache has a sibling lock."""
    assert hasattr(public_module, "_rss_lock")
    lock_type = type(threading.Lock())
    assert isinstance(public_module._rss_lock, lock_type)


def test_rss_cached_serializes_concurrent_misses():
    """Concurrency test: two simultaneous cache misses on the same key
    must call ``render_fn`` exactly once, with the second waiter
    short-circuiting on the post-acquire double-check."""
    # Use a unique cache key + a controlled render barrier so the test
    # is deterministic without real RSS traffic.
    public_module._rss_cache.pop("concurrency-test-key", None)

    barrier = threading.Event()
    proceed = threading.Event()
    call_count = {"n": 0}

    def slow_render():
        call_count["n"] += 1
        # Block until the second thread has had time to enter the
        # function and queue at the lock.
        barrier.set()
        proceed.wait(timeout=2.0)
        return "<rendered/>"

    results = []

    def call():
        results.append(public_module._rss_cached("concurrency-test-key", slow_render))

    t1 = threading.Thread(target=call)
    t1.start()
    # Wait for thread 1 to enter render_fn under the lock.
    assert barrier.wait(timeout=2.0)

    # Thread 2 enters _rss_cached now: cache is still empty (thread 1
    # hasn't returned), so it acquires the lock and the post-acquire
    # double-check sees the populated cache after thread 1 releases.
    t2 = threading.Thread(target=call)
    t2.start()

    proceed.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert call_count["n"] == 1, "render_fn must run only once under the lock"
    assert results == ["<rendered/>", "<rendered/>"]
    public_module._rss_cache.pop("concurrency-test-key", None)
