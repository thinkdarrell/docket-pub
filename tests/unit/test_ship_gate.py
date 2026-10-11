from docket.services.discrepancies import ship_gate


def _rows(spec):
    """spec: list of (meeting_id, state) in reviewed order."""
    return [{"meeting_id": m, "review_state": s} for m, s in spec]


def test_empty_window_is_not_met():
    g = ship_gate([])
    assert g == {"approved": 0, "rejected": 0, "total": 0, "meetings": 0, "ratio": 0.0, "window_complete": False, "gate_met": False}


def test_thirty_candidates_close_the_window_first():
    rows = _rows([(1, "approved")] * 25 + [(2, "rejected")] * 5 + [(3, "rejected")] * 20)
    g = ship_gate(rows)
    assert g["total"] == 30 and g["meetings"] == 2 and g["window_complete"]
    assert g["ratio"] == 0.833 and g["gate_met"]


def test_ten_meetings_close_the_window_first():
    rows = _rows([(m, "approved" if m % 2 else "rejected") for m in range(1, 13)])   # 12 meetings, one row each
    g = ship_gate(rows)
    assert g["meetings"] == 10 and g["total"] == 10 and g["window_complete"]
    assert g["ratio"] == 0.5 and not g["gate_met"]


def test_open_window_reports_ratio_but_not_met():
    g = ship_gate(_rows([(1, "approved")] * 9))
    assert g["ratio"] == 1.0 and not g["window_complete"] and not g["gate_met"]
