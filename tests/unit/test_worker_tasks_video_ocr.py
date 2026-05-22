"""Verify the cron-task wrapper around _do_video_ocr."""
from unittest.mock import patch

import pytest

from docket.worker.tasks import TASKS, task_video_ocr


def test_video_ocr_in_tasks_dict():
    assert "video_ocr" in TASKS
    assert TASKS["video_ocr"] is task_video_ocr


def test_task_video_ocr_calls_safe_run():
    """task_video_ocr() delegates to _safe_run("video_ocr", _do_video_ocr)."""
    with patch("docket.worker.tasks._safe_run") as safe_run:
        task_video_ocr()
    safe_run.assert_called_once()
    args = safe_run.call_args.args
    assert args[0] == "video_ocr"


def test_do_video_ocr_processes_up_to_5_meetings():
    """The inner loop calls _claim_next_ocr_meeting up to 5 times, exiting
    early if None is returned."""
    from docket.worker import tasks as tasks_mod

    calls = [
        {"id": 1, "external_id": "1", "meeting_date": None},
        {"id": 2, "external_id": "2", "meeting_date": None},
        None,
    ]
    with (
        patch.object(tasks_mod, "_claim_next_ocr_meeting", side_effect=calls) as claim,
        patch.object(tasks_mod, "_ocr_one_meeting", return_value={"meeting_id": 0, "votes": 0}) as ocr,
    ):
        tasks_mod._do_video_ocr()
    assert claim.call_count == 3   # 2 meetings + 1 None
    assert ocr.call_count == 2


def test_do_video_ocr_caps_at_5_when_queue_is_long():
    """Even if 10 meetings are pending, we only process 5 per tick."""
    from docket.worker import tasks as tasks_mod

    calls = [{"id": i, "external_id": str(i), "meeting_date": None} for i in range(1, 11)]
    with (
        patch.object(tasks_mod, "_claim_next_ocr_meeting", side_effect=calls) as claim,
        patch.object(tasks_mod, "_ocr_one_meeting", return_value={"meeting_id": 0, "votes": 0}) as ocr,
    ):
        tasks_mod._do_video_ocr()
    assert claim.call_count == 5
    assert ocr.call_count == 5
