"""Tests for the cron worker task wrappers."""

from unittest.mock import patch, MagicMock

import pytest

from docket.services.member_votes import ResolveResult
from docket.worker import tasks


# --- _safe_run ---------------------------------------------------------------

def test_safe_run_pings_start_then_success_on_clean_run():
    inner = MagicMock()
    with patch("docket.worker.tasks.health.ping") as mock_ping:
        tasks._safe_run("ingest_all", inner)
    inner.assert_called_once_with()
    statuses = [c.args[1] for c in mock_ping.call_args_list]
    assert statuses == ["start", "success"]


def test_safe_run_pings_fail_with_traceback_on_exception():
    def boom():
        raise ValueError("kaboom")

    with patch("docket.worker.tasks.health.ping") as mock_ping:
        tasks._safe_run("ingest_all", boom)  # must not raise

    statuses = [c.args[1] for c in mock_ping.call_args_list]
    assert statuses == ["start", "fail"]
    fail_call = mock_ping.call_args_list[-1]
    assert "ValueError" in fail_call.kwargs["body"]
    assert "kaboom" in fail_call.kwargs["body"]


def test_safe_run_does_not_re_raise():
    """APScheduler's default error logging is noisy; we own error reporting via Healthchecks."""
    def boom():
        raise RuntimeError("nope")

    with patch("docket.worker.tasks.health.ping"):
        # The assertion is "this line returns" — i.e. no exception escapes _safe_run.
        result = tasks._safe_run("ingest_all", boom)
    assert result is None


# --- task_city_calendar -------------------------------------------------------

def test_city_calendar_calls_refresh_all_and_logs_the_count(caplog):
    with patch("docket.worker.tasks.city_calendar.refresh_all", return_value=1) as mock_refresh, \
         caplog.at_level("INFO"):
        tasks._do_city_calendar()
    mock_refresh.assert_called_once_with()
    assert any("city_calendar: refreshed 1 cities" in r.getMessage() for r in caplog.records)


def test_city_calendar_is_registered_and_safe_run_wrapped():
    with patch("docket.worker.tasks.health.ping") as mock_ping, \
         patch("docket.worker.tasks.city_calendar.refresh_all", return_value=0):
        tasks.TASKS["city_calendar"]()
    assert [c.args for c in mock_ping.call_args_list] == [("city_calendar", "start"), ("city_calendar", "success")]


# --- task_non_meetings --------------------------------------------------------
# Plan committee-clips-named-or-hidden, M4. The service is patched by name on
# the tasks module, so these fail before the task exists.

def test_non_meetings_logs_the_ids_hidden_and_held_back_per_city(caplog):
    result = {"birmingham": ([3192, 3193], [2618]), "elsewhere": ([], [])}
    with patch("docket.worker.tasks.non_meetings.hide_non_meetings", return_value=result) as mock_hide, \
         caplog.at_level("INFO", logger="docket.worker.tasks"):
        tasks._do_non_meetings()
    mock_hide.assert_called_once_with()
    lines = [r.getMessage() for r in caplog.records]
    assert any("birmingham" in m and "[3192, 3193]" in m and "[2618]" in m for m in lines)
    assert any("elsewhere" in m and "[]" in m for m in lines)


def test_non_meetings_is_registered_and_safe_run_wrapped():
    with patch("docket.worker.tasks.health.ping") as mock_ping, \
         patch("docket.worker.tasks.non_meetings.hide_non_meetings", return_value={}):
        tasks.TASKS["non_meetings"]()
    assert [c.args for c in mock_ping.call_args_list] == [("non_meetings", "start"), ("non_meetings", "success")]


def test_non_meetings_has_its_healthcheck_variable():
    from docket.worker import health

    assert health.TASK_UUID_ENV["non_meetings"] == "HEALTHCHECK_NON_MEETINGS_UUID"


# --- task_youtube_ingest -----------------------------------------------------

def test_youtube_ingest_logs_and_returns_when_the_key_is_unset(caplog):
    with patch("docket.worker.tasks.config.YOUTUBE_API_KEY", None), \
         patch("docket.worker.tasks.youtube_meetings.sync_city") as mock_sync, \
         caplog.at_level("WARNING"):
        tasks._do_youtube_ingest()
    mock_sync.assert_not_called()
    assert any("YOUTUBE_API_KEY" in r.getMessage() for r in caplog.records)


def test_youtube_ingest_is_registered_and_safe_run_wrapped():
    with patch("docket.worker.tasks.health.ping") as mock_ping, \
         patch("docket.worker.tasks.config.YOUTUBE_API_KEY", None):
        tasks.TASKS["youtube_ingest"]()
    assert [c.args for c in mock_ping.call_args_list] == [("youtube_ingest", "start"), ("youtube_ingest", "success")]


def test_youtube_ingest_runs_each_city_with_a_channel_and_survives_quota(caplog):
    from docket.adapters.youtube import QuotaExceeded

    fake_cursor = MagicMock()
    fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
    fake_cursor.__exit__ = MagicMock(return_value=False)
    fake_cursor.fetchall.return_value = [{"slug": "birmingham"}, {"slug": "elsewhere"}]
    with patch("docket.worker.tasks.config.YOUTUBE_API_KEY", "k"), \
         patch("docket.worker.tasks.db_cursor", return_value=fake_cursor), \
         patch("docket.worker.tasks.youtube_meetings.sync_city",
               side_effect=[QuotaExceeded(403, "quotaExceeded"), MagicMock(counts={"create": 1})]) as mock_sync, \
         caplog.at_level("INFO"):
        tasks._do_youtube_ingest()
    assert [c.args[0] for c in mock_sync.call_args_list] == ["birmingham", "elsewhere"]
    assert any("quota" in r.getMessage().lower() for r in caplog.records)


# --- task_ingest_all ---------------------------------------------------------

def test_ingest_all_loops_active_municipalities():
    with patch("docket.worker.tasks.active_slugs", return_value=["birmingham", "mobile"]), \
         patch("docket.worker.tasks.ingest_municipality") as mock_ingest:
        tasks._do_ingest_all()

    assert mock_ingest.call_args_list[0].args == ("birmingham",)
    assert mock_ingest.call_args_list[1].args == ("mobile",)


def test_ingest_all_continues_on_per_city_failure():
    """If Birmingham fails, Mobile should still get a chance."""
    def maybe_fail(slug):
        if slug == "birmingham":
            raise RuntimeError("bham broke")

    with patch("docket.worker.tasks.active_slugs", return_value=["birmingham", "mobile"]), \
         patch("docket.worker.tasks.ingest_municipality", side_effect=maybe_fail) as mock_ingest:
        tasks._do_ingest_all()  # must not raise

    assert mock_ingest.call_count == 2


# --- task_ingest_afternoon ---------------------------------------------------
# Plan recordings-seen-the-day-posted, M1. The afternoon ingest visits the
# cities AFTERNOON_INGEST_SLUGS names that are also active, and no other.

_ACTIVE = ["birmingham", "homewood", "mobile", "vestavia_hills"]


def _ingest_result(**counts):
    values = dict(meetings_found=7, meetings_inserted=1, meetings_updated=2,
                  agenda_items_inserted=3, votes_inserted=4, errors=[])
    values.update(counts)
    return MagicMock(**values)


def test_ingest_afternoon_ingests_only_the_configured_active_cities(caplog):
    with patch("docket.worker.tasks.config.AFTERNOON_INGEST_SLUGS", ("birmingham",), create=True), \
         patch("docket.worker.tasks.active_slugs", return_value=list(_ACTIVE)), \
         patch("docket.worker.tasks.ingest_municipality", return_value=_ingest_result(errors=["a", "b"])) as mock_ingest, \
         caplog.at_level("INFO", logger="docket.worker.tasks"):
        tasks._do_ingest_afternoon()

    assert [c.args for c in mock_ingest.call_args_list] == [("birmingham",)]
    assert [c.kwargs for c in mock_ingest.call_args_list] == [{}]
    lines = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert "ingest_afternoon birmingham: found=7 inserted=1 updated=2 items=3 votes=4 errors=2" in lines


def test_ingest_afternoon_visits_the_configured_cities_in_the_configured_order():
    with patch("docket.worker.tasks.config.AFTERNOON_INGEST_SLUGS", ("mobile", "birmingham"), create=True), \
         patch("docket.worker.tasks.active_slugs", return_value=list(_ACTIVE)), \
         patch("docket.worker.tasks.ingest_municipality", return_value=_ingest_result()) as mock_ingest:
        tasks._do_ingest_afternoon()

    assert [c.args for c in mock_ingest.call_args_list] == [("mobile",), ("birmingham",)]


def test_ingest_afternoon_skips_a_configured_city_that_is_not_active(caplog):
    with patch("docket.worker.tasks.config.AFTERNOON_INGEST_SLUGS", ("hoover", "birmingham"), create=True), \
         patch("docket.worker.tasks.active_slugs", return_value=list(_ACTIVE)), \
         patch("docket.worker.tasks.ingest_municipality", return_value=_ingest_result()) as mock_ingest, \
         caplog.at_level("INFO", logger="docket.worker.tasks"):
        tasks._do_ingest_afternoon()

    assert [c.args for c in mock_ingest.call_args_list] == [("birmingham",)]
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == ["ingest_afternoon: hoover is not an active municipality; skipped"]


def test_ingest_afternoon_continues_on_per_city_failure(caplog):
    def maybe_fail(slug):
        if slug == "birmingham":
            raise RuntimeError("bham broke")
        return _ingest_result()

    with patch("docket.worker.tasks.config.AFTERNOON_INGEST_SLUGS", ("birmingham", "mobile"), create=True), \
         patch("docket.worker.tasks.active_slugs", return_value=list(_ACTIVE)), \
         patch("docket.worker.tasks.ingest_municipality", side_effect=maybe_fail) as mock_ingest, \
         caplog.at_level("INFO", logger="docket.worker.tasks"):
        tasks._do_ingest_afternoon()  # must not raise

    assert [c.args for c in mock_ingest.call_args_list] == [("birmingham",), ("mobile",)]
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert [r.getMessage() for r in errors] == ["ingest failed for birmingham"]
    assert errors[0].exc_info is not None
    infos = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert infos == ["ingest_afternoon mobile: found=7 inserted=1 updated=2 items=3 votes=4 errors=0"]


def test_ingest_afternoon_does_nothing_when_no_city_is_configured(caplog):
    with patch("docket.worker.tasks.config.AFTERNOON_INGEST_SLUGS", (), create=True), \
         patch("docket.worker.tasks.active_slugs") as mock_active, \
         patch("docket.worker.tasks.ingest_municipality") as mock_ingest, \
         caplog.at_level("INFO", logger="docket.worker.tasks"):
        tasks._do_ingest_afternoon()

    mock_ingest.assert_not_called()
    mock_active.assert_not_called()
    assert [r.getMessage() for r in caplog.records] == [
        "ingest_afternoon: no cities configured (AFTERNOON_INGEST_SLUGS is empty)"
    ]
    assert caplog.records[0].levelname == "INFO"


def test_ingest_afternoon_is_registered_and_safe_run_wrapped():
    with patch("docket.worker.tasks.health.ping") as mock_ping, \
         patch("docket.worker.tasks.config.AFTERNOON_INGEST_SLUGS", (), create=True):
        tasks.TASKS["ingest_afternoon"]()
    assert [c.args for c in mock_ping.call_args_list] == [
        ("ingest_afternoon", "start"), ("ingest_afternoon", "success")
    ]


# --- config: the afternoon ingest's cities ------------------------------------

def test_config_csv_strips_parts_and_drops_empty_ones():
    from docket import config

    assert config._csv("birmingham, mobile,,") == ("birmingham", "mobile")
    assert config._csv("") == ()
    assert config._csv(" , ") == ()


def test_config_afternoon_ingest_slugs_defaults_to_birmingham():
    """Read in a fresh interpreter, because config reads the variable at import."""
    import os
    import subprocess
    import sys

    def read(env_value):
        env = {k: v for k, v in os.environ.items() if k != "AFTERNOON_INGEST_SLUGS"}
        if env_value is not None:
            env["AFTERNOON_INGEST_SLUGS"] = env_value
        out = subprocess.run(
            [sys.executable, "-c",
             "from docket import config; print(repr(config.AFTERNOON_INGEST_SLUGS))"],
            env=env, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    assert read(None) == "('birmingham',)"
    assert read("") == "()"
    assert read("birmingham, mobile") == "('birmingham', 'mobile')"


# --- task wrappers call into the right service -------------------------------

def test_ai_items_invokes_run_once_with_items_stage():
    with patch("docket.worker.tasks.run_once") as mock_run:
        tasks._do_ai_items()
    assert mock_run.call_args.kwargs["stage"] == "items"
    assert mock_run.call_args.kwargs["limit"] == 200
    assert mock_run.call_args.kwargs["notes"] == "cron_items"


def test_ai_meetings_invokes_run_once_with_meetings_stage():
    with patch("docket.worker.tasks.run_once") as mock_run:
        tasks._do_ai_meetings()
    assert mock_run.call_args.kwargs["stage"] == "meetings"
    assert mock_run.call_args.kwargs["limit"] == 50
    assert mock_run.call_args.kwargs["notes"] == "cron_meetings"


def test_ai_items_swallows_budget_exceeded():
    """BudgetExceededError is expected behavior, not a failure for Healthchecks."""
    from docket.ai.worker import BudgetExceededError
    with patch("docket.worker.tasks.run_once",
               side_effect=BudgetExceededError("over cap")):
        tasks._do_ai_items()  # must not raise


def test_ai_meetings_swallows_budget_exceeded():
    """BudgetExceededError is expected behavior, not a failure for Healthchecks."""
    from docket.ai.worker import BudgetExceededError
    with patch("docket.worker.tasks.run_once",
               side_effect=BudgetExceededError("over cap")):
        tasks._do_ai_meetings()  # must not raise


def test_vote_matching_invokes_match_all_unmatched():
    with patch("docket.worker.tasks.match_all_unmatched") as mock_match:
        mock_match.return_value = {
            "meetings": 1, "timestamp_matched": 0,
            "substantive_matched": 2, "consent_matched": 5,
        }
        tasks._do_vote_matching()
    mock_match.assert_called_once()


def test_repair_invokes_repair_empty_agendas():
    with patch("docket.worker.tasks.repair_empty_agendas") as mock_repair:
        mock_repair.return_value = 3
        tasks._do_repair_empty_agendas()
    mock_repair.assert_called_once()


def test_briefing_facts_calls_recompute_all_flagged(caplog):
    with patch("docket.worker.tasks.briefing.recompute_all_flagged") as mock_recompute:
        mock_recompute.return_value = 1
        with caplog.at_level("INFO", logger="docket.worker.tasks"):
            tasks._do_briefing_facts()
    mock_recompute.assert_called_once_with()
    assert any("briefing_facts: recomputed 1 cities" in r.message for r in caplog.records)


def test_resolve_member_votes_invokes_service():
    with patch("docket.worker.tasks.resolve_unresolved_member_votes") as mock_resolve:
        mock_resolve.return_value = ResolveResult(3, 2, {"Georgia": 2})
        tasks._do_resolve_member_votes()
    mock_resolve.assert_called_once()


# --- TASKS registry ----------------------------------------------------------

def test_tasks_registry_has_all_jobs():
    expected = {
        "ingest_all", "video_ocr", "ai_items", "ai_meetings", "vote_matching",
        "repair_empty_agendas", "process_badges", "calibration_report",
        "process_batches", "refresh_backfill_ratio_mv", "prune_analytics",
        "recast_post_meeting_ai", "transcript_pipeline", "resolve_member_votes",
        "briefing_facts", "city_calendar", "youtube_ingest", "non_meetings",
        "committee_documents", "ingest_afternoon",
    }
    assert set(tasks.TASKS.keys()) == expected
