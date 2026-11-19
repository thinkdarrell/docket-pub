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
        "recast_post_meeting_ai", "transcript_pipeline", "resolve_member_votes",
        "briefing_facts", "city_calendar", "youtube_ingest", "non_meetings",
        "committee_documents",
        "ingest_afternoon", "youtube_ingest_afternoon", "non_meetings_afternoon",
    }
    assert len(sched.get_jobs()) == 22


@pytest.mark.parametrize("job_id,expected,task", [
    ("ingest_afternoon",         ("16", "30", "*"), "ingest_afternoon"),
    ("youtube_ingest_afternoon", ("16", "45", "*"), "youtube_ingest"),
    ("non_meetings_afternoon",   ("16", "55", "*"), "non_meetings"),
])
def test_build_scheduler_afternoon_pass(job_id, expected, task):
    """The afternoon pass: a Birmingham-only ingest, then second jobs on the
    morning's youtube_ingest and non_meetings tasks.
    Plan `recordings-seen-the-day-posted`, M1."""
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job(job_id)
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"], fields["day_of_week"]) == expected
    assert job.coalesce is True
    assert job.max_instances == 1
    assert job.func is scheduler.TASKS[task]


@pytest.mark.parametrize("job_id,expected", [
    ("ingest_all",     ("6", "0")),
    ("youtube_ingest", ("6", "45")),
    ("non_meetings",   ("6", "55")),
])
def test_build_scheduler_morning_pass_is_unchanged(job_id, expected):
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job(job_id)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == expected


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
    ("resolve_member_votes", 8),
    ("process_badges",       9),
    ("calibration_report",  11),
    ("prune_analytics",      4),
    ("recast_post_meeting_ai", 4),
    ("briefing_facts",       9),
    ("city_calendar",        5),
    ("youtube_ingest",       6),
    ("non_meetings",         6),
    ("committee_documents",  7),
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


def test_build_scheduler_resolve_member_votes_at_45_minutes():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("resolve_member_votes")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["minute"] == "45"


def test_build_scheduler_process_badges_at_30_minutes():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("process_badges")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["minute"] == "30"


def test_build_scheduler_briefing_facts_at_45_minutes():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("briefing_facts")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["minute"] == "45"


def test_build_scheduler_city_calendar_at_30_minutes_before_ingest():
    """05:30 so the calendar rows exist before ingest_all (06:00) resolves against them."""
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("city_calendar")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "5"
    assert fields["minute"] == "30"
    assert fields["day_of_week"] == "*"


def test_build_scheduler_youtube_ingest_at_06_45():
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("youtube_ingest")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("6", "45")
    assert job.coalesce is True and job.max_instances == 1


def test_build_scheduler_non_meetings_at_06_55_after_youtube_ingest():
    """06:55, after youtube_ingest (06:45) has attached any recording that names a clip."""
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("non_meetings")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"], fields["day_of_week"]) == ("6", "55", "*")
    assert job.coalesce is True and job.max_instances == 1


def test_build_scheduler_committee_documents_at_07_15_after_youtube_ingest():
    """07:15, after youtube_ingest (06:45) has created or matched the day's
    recordings, so a new document finds its meeting. Plan `committee-documents`, M6."""
    sched = scheduler.build_scheduler(timezone="America/Chicago")
    job = sched.get_job("committee_documents")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"], fields["day_of_week"]) == ("7", "15", "*")
    assert job.coalesce is True and job.max_instances == 1
    assert job.func is scheduler.TASKS["committee_documents"]


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


def test_main_warns_which_tasks_have_no_heartbeat(monkeypatch, caplog):
    """Startup names the tasks whose failure would page no one (issue #89)."""
    import logging
    from unittest.mock import MagicMock

    from docket.worker import health, scheduler

    for env_var in health.TASK_UUID_ENV.values():
        monkeypatch.delenv(env_var, raising=False)
    fake_sched = MagicMock()
    fake_sched.get_jobs.return_value = []
    monkeypatch.setattr(scheduler, "build_scheduler", lambda timezone: fake_sched)
    monkeypatch.setattr("sys.argv", ["scheduler"])
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: None)

    with caplog.at_level(logging.WARNING, logger=scheduler.log.name):
        scheduler.main()

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("video_ocr" in m and "HEALTHCHECK" in m for m in warnings)
    fake_sched.start.assert_called_once()


# --- --list: the schedule printed from the code -----------------------------
# Plan `recordings-seen-the-day-posted`, M2.

EXPECTED_LIST = [
    "prune_analytics prune_analytics cron[day='1', hour='4', minute='0']",
    "refresh_backfill_ratio_mv refresh_backfill_ratio_mv cron[hour='4', minute='30']",
    "recast_post_meeting_ai recast_post_meeting_ai cron[hour='4', minute='45']",
    "repair_empty_agendas repair_empty_agendas cron[day_of_week='0', hour='5', minute='0']",
    "city_calendar city_calendar cron[hour='5', minute='30']",
    "ingest_all ingest_all cron[hour='6', minute='0']",
    "video_ocr video_ocr cron[hour='6', minute='30']",
    "youtube_ingest youtube_ingest cron[hour='6', minute='45']",
    "non_meetings non_meetings cron[hour='6', minute='55']",
    "ai_items ai_items cron[hour='7', minute='0']",
    "committee_documents committee_documents cron[hour='7', minute='15']",
    "ai_meetings ai_meetings cron[hour='8', minute='0']",
    "resolve_member_votes resolve_member_votes cron[hour='8', minute='45']",
    "vote_matching vote_matching cron[hour='9', minute='0']",
    "process_badges process_badges cron[hour='9', minute='30']",
    "briefing_facts briefing_facts cron[hour='9', minute='45']",
    "transcript_pipeline transcript_pipeline cron[hour='10', minute='0']",
    "calibration_report calibration_report cron[hour='11', minute='0']",
    "ingest_afternoon ingest_afternoon cron[hour='16', minute='30']",
    "youtube_ingest_afternoon youtube_ingest cron[hour='16', minute='45']",
    "non_meetings_afternoon non_meetings cron[hour='16', minute='55']",
    "process_batches process_batches cron[minute='0,30']",
]


def test_list_jobs_prints_every_job_in_time_of_day_order():
    """One line per job, `<job id> <task name> <trigger>`, earliest first; a
    job with no single hour (process_batches) comes last."""
    lines = scheduler.list_jobs()
    assert len(lines) == len(scheduler.build_scheduler().get_jobs())
    assert lines[0] == "prune_analytics prune_analytics cron[day='1', hour='4', minute='0']"
    assert lines[-1] == "process_batches process_batches cron[minute='0,30']"
    ids = [line.split(" ")[0] for line in lines]
    assert ids.index("ingest_all") < ids.index("ingest_afternoon")
    assert lines == EXPECTED_LIST


def test_list_jobs_names_the_task_a_second_job_runs():
    """A second job on a morning task is listed under its own id with the
    name of the task it runs, found by identity in TASKS."""
    lines = scheduler.list_jobs()
    assert "youtube_ingest_afternoon youtube_ingest cron[hour='16', minute='45']" in lines
    assert "non_meetings_afternoon non_meetings cron[hour='16', minute='55']" in lines


def test_list_jobs_sorts_by_hour_then_minute_then_job_id(monkeypatch):
    """Jobs at one time of day are listed by job id, and the hour and the
    minute are compared as numbers (10 after 9, not before it)."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    def build(timezone="America/Chicago"):
        sched = BlockingScheduler(timezone=timezone)
        for job_id, kw in [
            ("zeta",    {"hour": 9, "minute": 5}),
            ("alpha",   {"hour": 9, "minute": 5}),
            ("ten",     {"hour": 10, "minute": 0}),
            ("late",    {"hour": 9, "minute": 10}),
            ("several", {"hour": 9, "minute": "0,30"}),
            ("hourly",  {"minute": 1}),
        ]:
            sched.add_job(scheduler.TASKS["ingest_all"],
                          CronTrigger(timezone=timezone, **kw), id=job_id)
        return sched

    monkeypatch.setattr(scheduler, "build_scheduler", build)
    ids = [line.split(" ")[0] for line in scheduler.list_jobs()]
    # "several" has no single minute, so it follows every single minute of its
    # hour; "hourly" has no single hour, so it follows every single hour.
    assert ids == ["alpha", "zeta", "late", "several", "ten", "hourly"]


def test_list_jobs_builds_the_scheduler_in_the_given_timezone(monkeypatch):
    seen = []
    real = scheduler.build_scheduler

    def spy(timezone="America/Chicago"):
        seen.append(timezone)
        return real(timezone=timezone)

    monkeypatch.setattr(scheduler, "build_scheduler", spy)
    scheduler.list_jobs("America/New_York")
    assert seen == ["America/New_York"]


def test_main_with_list_prints_the_schedule_and_starts_nothing(monkeypatch, capsys, caplog):
    """--list prints a header and the lines, starts no scheduler, pings no
    check, runs no task and warns of nothing."""
    import logging

    from apscheduler.schedulers.blocking import BlockingScheduler

    def fail(*a, **kw):
        raise AssertionError("--list must start, run and ping nothing")

    monkeypatch.setattr(sys, "argv", ["scheduler", "--list"])
    monkeypatch.setattr(BlockingScheduler, "start", fail)
    monkeypatch.setattr(scheduler, "run_once_task", fail)
    monkeypatch.setattr(scheduler.health, "ping", fail)
    monkeypatch.setattr(scheduler.health, "unmonitored_tasks", fail)
    monkeypatch.setattr(scheduler.config, "WORKER_TIMEZONE", "America/New_York")
    built_in = []
    real_build = scheduler.build_scheduler

    def build(timezone="America/Chicago"):
        built_in.append(timezone)
        return real_build(timezone=timezone)

    monkeypatch.setattr(scheduler, "build_scheduler", build)

    with caplog.at_level(logging.INFO):
        scheduler.main()

    assert built_in == ["America/New_York"]

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "timezone=America/New_York jobs=22"
    assert out[1:] == EXPECTED_LIST
    # APScheduler logs each add_job at INFO under its own logger; the worker's
    # own logger (the startup lines, the unmonitored-tasks WARNING) says nothing.
    assert [r for r in caplog.records if r.name == scheduler.log.name] == []


def test_main_refuses_list_together_with_run_once(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["scheduler", "--list", "--run-once", "ingest_all"])
    monkeypatch.setattr(scheduler, "run_once_task",
                        lambda name: pytest.fail("ran a task"))
    with pytest.raises(SystemExit) as exc_info:
        scheduler.main()
    assert exc_info.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_no_docstring_outside_the_scheduler_states_a_worker_clock_time():
    """scheduler.py owns the times; the task and service docstrings name the
    order and the reason. The pattern is the plan's acceptance grep."""
    import re
    from pathlib import Path

    src = Path(scheduler.__file__).resolve().parents[1]
    pattern = re.compile(r"\b(0[4-9]|1[01]|16):[0-5][0-9]\b")
    hits = [
        f"{rel}:{n}: {line.strip()}"
        for rel in ("worker/tasks.py", "services/non_meetings.py", "services/city_calendar.py")
        for n, line in enumerate((src / rel).read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert hits == []
