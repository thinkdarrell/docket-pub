"""Tests for the worker scheduler entry point."""

import sys
from unittest.mock import patch

import pytest

from docket.worker import scheduler


def test_build_scheduler_registers_all_jobs():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {
        "ingest_all", "video_ocr", "ai_items", "ai_meetings", "vote_matching",
        "repair_empty_agendas", "process_badges", "calibration_report",
        "process_batches", "refresh_backfill_ratio_mv", "prune_analytics",
    }


def test_build_scheduler_process_batches_every_30_minutes():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("process_batches")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["minute"] == "0,30"


def test_build_scheduler_uses_supplied_timezone():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("ingest_all")
    assert str(job.trigger.timezone) == "America/Chicago"


@pytest.mark.parametrize("job_id,expected_hour", [
    ("repair_empty_agendas", 5),
    ("ingest_all",           6),
    ("ai_items",             7),
    ("ai_meetings",          8),
    ("vote_matching",        9),
    ("process_badges",       9),
    ("calibration_report",  11),
    ("prune_analytics",      4),
])
def test_build_scheduler_job_hours(job_id, expected_hour):
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job(job_id)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == str(expected_hour)


def test_build_scheduler_prune_analytics_runs_on_first_of_month():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("prune_analytics")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["day"] == "1"
    assert fields["minute"] == "0"


def test_build_scheduler_calibration_report_at_00_minutes():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("calibration_report")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["minute"] == "0"


def test_build_scheduler_process_badges_at_30_minutes():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("process_badges")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["minute"] == "30"


def test_build_scheduler_repair_runs_only_on_monday():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("repair_empty_agendas")
    fields = {f.name: str(f) for f in job.trigger.fields}
    # APScheduler day_of_week is 0=mon..6=sun
    assert fields["day_of_week"] == "0"


def test_run_once_task_invokes_named_task():
    with patch.dict("docket.worker.scheduler.TASKS",
                    {"ingest_all": lambda: setattr(test_run_once_task_invokes_named_task, "_called", True)},
                    clear=True):
        scheduler.run_once_task("ingest_all")
    assert getattr(test_run_once_task_invokes_named_task, "_called", False) is True


def test_run_once_task_unknown_name_exits():
    with pytest.raises(SystemExit) as exc_info:
        scheduler.run_once_task("not_a_real_task")
    assert exc_info.value.code != 0


def test_main_with_run_once_dispatches_and_exits(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["scheduler.py", "--run-once", "ingest_all"])
    called = {"v": False}
    monkeypatch.setattr(scheduler, "run_once_task",
                        lambda name: called.__setitem__("v", name))
    scheduler.main()
    assert called["v"] == "ingest_all"
