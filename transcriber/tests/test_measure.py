"""The measuring pass (plan video-links-land-on-the-moment, M3), with every fetch stubbed.

No test here downloads anything or runs the matcher: `measure.source_for` and
`measure.fetch_audio` are stand-ins that write a few bytes, the three `measure.align`
functions return fixed values (the matcher itself is test_align.py's), and the database is a
recorder in the style of FakeDB in test_cli_loop.py. `transcriber.measure` is imported inside
each test so the file collects before the module exists.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import psycopg2.errors

from transcriber import cli
from transcriber.audio import AudioFetchError
from transcriber.db import AlignmentCandidate

GRANICUS = "https://bhamal.granicus.com/DownloadFile.php?view_id=2&clip_id="


def _measurement(status="passed", reason=None):
    from transcriber.align import Measurement
    return Measurement(status=status, reason=reason, offset_s=635.48, granicus_start_s=635.48,
                       granicus_end_s=4078.7, score=23.6, runner_up=6.0, windows=12,
                       windows_confirmed=10)


def _cand(row_id, video_id, meeting_id, clip):
    return AlignmentCandidate(row_id, video_id, meeting_id, clip, date(2026, 10, 27))


class FakeConn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeDB:
    """Stands in for the three transcriber.db functions the pass calls."""

    def __init__(self, candidates, *, read_error=None, save_error_at=None, backlog_error=None):
        self.candidates = list(candidates)
        self.read_error, self.save_error_at, self.backlog_error = read_error, save_error_at, backlog_error
        self.reads = []
        self.saved = []

    def alignment_candidates(self, conn, *, method_version, limit, retry_failed_days=7):
        self.reads.append((method_version, limit))
        if self.read_error is not None:
            raise self.read_error
        return self.candidates[:limit]

    def alignment_backlog(self, conn, *, method_version, retry_failed_days=7):
        if self.backlog_error is not None:
            raise self.backlog_error
        return len(self.candidates) - len({s.cand.meeting_video_id for s in self.saved})

    def save_alignment(self, conn, cand, *, method_version, status, reason=None, measurement=None):
        if self.save_error_at == len(self.saved):
            raise psycopg2.errors.UndefinedTable('relation "meeting_video_alignments" does not exist')
        self.saved.append(SimpleNamespace(cand=cand, version=method_version, status=status,
                                          reason=reason, measurement=measurement, commits=conn.commits))

    def statuses(self):
        return [(s.cand.video_id, s.status) for s in self.saved]


def _cfg(tmp_path):
    return cli.Config(since=date(2025, 10, 28), limit=10, max_hours=None, host="test",
                      work_dir=tmp_path / "work", archive_dir=tmp_path / "archive",
                      dry_run_file=None, version="0.5.0")


def _wire(monkeypatch, fdb, *, youtube_errors=None, granicus_errors=None, results=None, on_measure=None):
    """Replace everything the pass reaches outside itself; returns what the stand-ins saw.

    `youtube_errors` maps a video id to the exception its download raises (after leaving a
    partial file, as yt-dlp would), `granicus_errors` a clip id to the exception its fetch
    raises, `results` a video id to the Measurement its match returns (a passing one otherwise);
    `on_measure(video_id)` runs after each match.
    """
    from transcriber import measure
    youtube_errors, granicus_errors, results = youtube_errors or {}, granicus_errors or {}, results or {}
    seen = SimpleNamespace(downloads=[], fetches=[], measured=[], sleeps=[])
    for name in ("alignment_candidates", "alignment_backlog", "save_alignment"):
        monkeypatch.setattr(measure.tdb, name, getattr(fdb, name))

    def fake_source_for(external_id, work_dir, *, audio_format="bestaudio/best"):
        seen.downloads.append((external_id, audio_format))
        video_id = external_id[len("yt-"):]
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        if video_id in youtube_errors:
            (Path(work_dir) / f"{external_id}.webm.part").write_bytes(b"\0")
            raise youtube_errors[video_id]
        path = Path(work_dir) / f"{external_id}.webm"
        path.write_bytes(b"\0" * 64)
        return str(path)

    def fake_fetch_audio(source, out_wav, **kw):
        seen.fetches.append((source, Path(out_wav).name, kw.get("rate")))
        if source.startswith(GRANICUS) and source[len(GRANICUS):] in granicus_errors:
            raise granicus_errors[source[len(GRANICUS):]]
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        Path(out_wav).write_bytes(b"RIFF" + b"\0" * 100)
        return Path(out_wav)

    def fake_read_wav(path):
        assert Path(path).exists(), f"{path} was read before it was written"
        return Path(path).name

    def fake_measure(granicus, youtube):
        video_id = youtube[1][len("align-yt-"):-len(".wav")]
        seen.measured.append((granicus, youtube))
        if on_measure is not None:
            on_measure(video_id)
        return results.get(video_id) or _measurement()

    monkeypatch.setattr(measure, "source_for", fake_source_for)
    monkeypatch.setattr(measure, "fetch_audio", fake_fetch_audio)
    monkeypatch.setattr(measure.align, "read_wav", fake_read_wav)
    monkeypatch.setattr(measure.align, "features", lambda samples: ("features", samples))
    monkeypatch.setattr(measure.align, "measure", fake_measure)
    return seen


def _left_in(folder):
    return sorted(p.name for p in Path(folder).rglob("*")) if Path(folder).exists() else []


def _granicus_fetches(seen):
    return [source for source, _, _ in seen.fetches if source.startswith(GRANICUS)]


def test_each_candidate_is_measured_once_saved_once_and_the_work_folder_is_left_empty(
        monkeypatch, tmp_path, caplog):
    from transcriber import align, measure
    cfg, conn = _cfg(tmp_path), FakeConn()
    fdb = FakeDB([_cand(11, "FR84h22hQvA", 3184, "2026"), _cand(12, "uvqFjIfPLLU", 3170, "2024")])
    rollbacks_at_measure = []
    seen = _wire(monkeypatch, fdb, results={"uvqFjIfPLLU": _measurement("rejected", "windows")},
                 on_measure=lambda video_id: rollbacks_at_measure.append(conn.rollbacks))
    with caplog.at_level(logging.INFO):
        counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)

    assert counts == {"passed": 1, "rejected": 1, "failed": 0}
    assert fdb.reads == [(align.ALIGN_METHOD_VERSION, 20)]
    assert fdb.statuses() == [("FR84h22hQvA", "passed"), ("uvqFjIfPLLU", "rejected")]
    first, second = fdb.saved
    assert first.version == align.ALIGN_METHOD_VERSION and first.reason is None
    assert first.measurement == _measurement()
    assert second.reason == "windows" and second.measurement.status == "rejected"
    assert first.commits < second.commits <= conn.commits - 1     # each row committed on its own
    assert rollbacks_at_measure == [1, 1]     # the candidate read's transaction ended before any download
    assert conn.rollbacks == 2                # and the backlog read's after it
    assert seen.downloads == [("yt-FR84h22hQvA", measure.MEASURE_YTDLP_FORMAT),
                              ("yt-uvqFjIfPLLU", measure.MEASURE_YTDLP_FORMAT)]
    assert measure.MEASURE_YTDLP_FORMAT == "worstaudio/bestaudio/worst"
    assert seen.fetches == [
        (GRANICUS + "2026", "align-3184.wav", 8000),
        (str(cfg.work_dir / "yt-FR84h22hQvA.webm"), "align-yt-FR84h22hQvA.wav", 8000),
        (GRANICUS + "2024", "align-3170.wav", 8000),
        (str(cfg.work_dir / "yt-uvqFjIfPLLU.webm"), "align-yt-uvqFjIfPLLU.wav", 8000),
    ]
    assert seen.measured == [(("features", "align-3184.wav"), ("features", "align-yt-FR84h22hQvA.wav")),
                             (("features", "align-3170.wav"), ("features", "align-yt-uvqFjIfPLLU.wav"))]
    assert seen.sleeps == [measure.MEASURE_PAUSE_S, measure.MEASURE_PAUSE_S] == [3.0, 3.0]
    assert _left_in(cfg.work_dir) == []
    assert ("measure meeting 3184 clip 2026 video FR84h22hQvA: passed offset=635.48s "
            "covers=635.5-4078.7s score=23.6 runner_up=6.0 windows=10/12") in caplog.messages
    assert ("measure meeting 3170 clip 2024 video uvqFjIfPLLU: rejected (windows) offset=635.48s "
            "covers=635.5-4078.7s score=23.6 runner_up=6.0 windows=10/12") in caplog.messages
    assert caplog.messages[-1] == "measure done {'passed': 1, 'rejected': 1, 'failed': 0} remaining=0"


def test_two_recordings_of_one_meeting_fetch_the_granicus_audio_once_and_get_a_row_each(
        monkeypatch, tmp_path):
    from transcriber import measure
    cfg, conn = _cfg(tmp_path), FakeConn()
    fdb = FakeDB([_cand(21, "96jZkW4zv7U", 72, "1831"), _cand(22, "E0cpl0Snx20", 72, "1831")])
    seen = _wire(monkeypatch, fdb)
    counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)

    assert counts == {"passed": 2, "rejected": 0, "failed": 0}
    assert _granicus_fetches(seen) == [GRANICUS + "1831"]
    assert seen.sleeps == [3.0]
    assert fdb.statuses() == [("96jZkW4zv7U", "passed"), ("E0cpl0Snx20", "passed")]
    assert [g for g, _ in seen.measured] == [("features", "align-72.wav")] * 2   # the same features twice
    assert _left_in(cfg.work_dir) == []

    # a meeting's recordings need not be adjacent in the candidate order (a failure being
    # retried sorts after the never-measured); they are still measured together
    fdb = FakeDB([_cand(21, "96jZkW4zv7U", 72, "1831"), _cand(23, "ara-4Ve6XCU", 3150, "2017"),
                  _cand(22, "E0cpl0Snx20", 72, "1831")])
    seen = _wire(monkeypatch, fdb)
    counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)
    assert counts == {"passed": 3, "rejected": 0, "failed": 0}
    assert _granicus_fetches(seen) == [GRANICUS + "1831", GRANICUS + "2017"]
    assert fdb.statuses() == [("96jZkW4zv7U", "passed"), ("E0cpl0Snx20", "passed"), ("ara-4Ve6XCU", "passed")]


def test_youtube_fetch_error_saves_failed_with_its_reason_and_the_next_recording_is_measured(
        monkeypatch, tmp_path, caplog):
    from transcriber import measure
    cfg, conn = _cfg(tmp_path), FakeConn()
    fdb = FakeDB([_cand(31, "abc", 501, "2001"), _cand(32, "def", 502, "2002")])
    message = "yt-dlp could not download https://www.youtube.com/watch?v=abc: Sign in to confirm"
    seen = _wire(monkeypatch, fdb, youtube_errors={"abc": AudioFetchError(message)})
    with caplog.at_level(logging.INFO):
        counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)

    assert counts == {"passed": 1, "rejected": 0, "failed": 1}
    assert fdb.statuses() == [("abc", "failed"), ("def", "passed")]
    failed = fdb.saved[0]
    assert failed.reason.startswith("AudioFetchError: ") and message in failed.reason
    assert failed.measurement is None
    assert _left_in(cfg.work_dir) == []                       # the partial download went too
    assert f"measure meeting 501 clip 2001 video abc: failed (AudioFetchError: {message})" in caplog.messages
    assert caplog.messages[-1] == "measure done {'passed': 1, 'rejected': 0, 'failed': 1} remaining=0"


def test_three_youtube_fetch_failures_in_a_row_stop_the_pass_before_the_fourth_meeting(
        monkeypatch, tmp_path, caplog):
    from transcriber import measure
    assert measure.MEASURE_MAX_CONSECUTIVE_FAILURES == 3
    cfg, conn = _cfg(tmp_path), FakeConn()
    four = [_cand(40 + i, f"vid{i}", 600 + i, str(2100 + i)) for i in range(1, 5)]
    fdb = FakeDB(four)
    errors = {f"vid{i}": AudioFetchError("HTTP Error 403: Forbidden") for i in range(1, 5)}
    seen = _wire(monkeypatch, fdb, youtube_errors=errors)
    with caplog.at_level(logging.INFO):
        counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)

    assert counts == {"passed": 0, "rejected": 0, "failed": 3}
    assert fdb.statuses() == [("vid1", "failed"), ("vid2", "failed"), ("vid3", "failed")]
    assert _granicus_fetches(seen) == [GRANICUS + "2101", GRANICUS + "2102", GRANICUS + "2103"]
    assert any(r.levelno == logging.WARNING and "in a row" in r.getMessage() for r in caplog.records)
    assert caplog.messages[-1] == "measure done {'passed': 0, 'rejected': 0, 'failed': 3} remaining=1"
    assert _left_in(cfg.work_dir) == []

    # "in a row": a measured recording between failures sets the count back, so five are all tried
    fdb = FakeDB([_cand(50 + i, f"mix{i}", 700 + i, str(2200 + i)) for i in range(1, 6)])
    errors = {f"mix{i}": AudioFetchError("HTTP Error 403: Forbidden") for i in (1, 2, 4, 5)}
    _wire(monkeypatch, fdb, youtube_errors=errors,
          results={"mix3": _measurement("rejected", "score")})
    counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)
    assert counts == {"passed": 0, "rejected": 1, "failed": 4}
    assert [status for _, status in fdb.statuses()] == ["failed", "failed", "rejected", "failed", "failed"]


def test_a_limit_of_zero_reads_nothing(monkeypatch, tmp_path):
    from transcriber import measure
    cfg, conn = _cfg(tmp_path), FakeConn()
    fdb = FakeDB([_cand(61, "abc", 801, "2301")])
    seen = _wire(monkeypatch, fdb)
    for limit in (0, -1):
        assert measure.measure_pass(conn, cfg, limit=limit, sleep=seen.sleeps.append) == {
            "passed": 0, "rejected": 0, "failed": 0}
    assert fdb.reads == [] and fdb.saved == [] and seen.fetches == [] and seen.downloads == []
    assert (conn.commits, conn.rollbacks) == (0, 0)


def test_a_set_stop_flag_and_a_passed_deadline_each_stop_the_pass_before_the_next_recording(
        monkeypatch, tmp_path):
    from transcriber import measure
    cfg = _cfg(tmp_path)
    # two recordings of one meeting, then a second meeting
    cands = [_cand(71, "partA", 901, "2401"), _cand(72, "partB", 901, "2401"), _cand(73, "next", 902, "2402")]

    # Ctrl-C while the first recording is being measured
    stop = SimpleNamespace(requested=False)
    fdb = FakeDB(cands)
    seen = _wire(monkeypatch, fdb, on_measure=lambda video_id: setattr(stop, "requested", True))
    counts = measure.measure_pass(FakeConn(), cfg, limit=20, stop=stop, sleep=seen.sleeps.append)
    assert counts == {"passed": 1, "rejected": 0, "failed": 0}
    assert fdb.statuses() == [("partA", "passed")]            # the row in hand was still saved
    assert seen.downloads == [("yt-partA", measure.MEASURE_YTDLP_FORMAT)]
    assert _granicus_fetches(seen) == [GRANICUS + "2401"]
    assert _left_in(cfg.work_dir) == []

    # a flag set before the pass starts: nothing is fetched at all
    fdb = FakeDB(cands)
    seen = _wire(monkeypatch, fdb)
    counts = measure.measure_pass(FakeConn(), cfg, limit=20, stop=SimpleNamespace(requested=True),
                                  sleep=seen.sleeps.append)
    assert counts == {"passed": 0, "rejected": 0, "failed": 0}
    assert fdb.saved == [] and seen.fetches == [] and seen.downloads == []

    # --max-hours: the deadline passes while the second recording is being measured
    now = [100.0]
    fdb = FakeDB(cands)
    seen = _wire(monkeypatch, fdb,
                 on_measure=lambda video_id: now.__setitem__(0, 5000.0) if video_id == "partB" else None)
    counts = measure.measure_pass(FakeConn(), cfg, limit=20, deadline=3700.0, clock=lambda: now[0],
                                  sleep=seen.sleeps.append)
    assert counts == {"passed": 2, "rejected": 0, "failed": 0}
    assert fdb.statuses() == [("partA", "passed"), ("partB", "passed")]
    assert _granicus_fetches(seen) == [GRANICUS + "2401"]     # the next meeting's clip was never asked for
    assert _left_in(cfg.work_dir) == []

    # a deadline exactly reached has not passed (run_loop's own comparison is strict too)
    fdb = FakeDB(cands[:1])
    seen = _wire(monkeypatch, fdb)
    counts = measure.measure_pass(FakeConn(), cfg, limit=20, deadline=100.0, clock=lambda: 100.0,
                                  sleep=seen.sleeps.append)
    assert counts == {"passed": 1, "rejected": 0, "failed": 0}


def test_insufficient_privilege_on_the_candidate_read_is_swallowed_after_a_rollback(
        monkeypatch, tmp_path, caplog):
    from transcriber import measure
    cfg, conn = _cfg(tmp_path), FakeConn()
    denied = psycopg2.errors.InsufficientPrivilege("permission denied for table meeting_video_alignments\n")
    fdb = FakeDB([_cand(81, "abc", 1001, "2501")], read_error=denied)
    seen = _wire(monkeypatch, fdb)
    with caplog.at_level(logging.INFO):
        counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)
    assert counts == {"passed": 0, "rejected": 0, "failed": 0}
    assert conn.rollbacks == 1 and conn.commits == 0
    assert seen.fetches == [] and fdb.saved == []
    skipped = [r for r in caplog.records if r.getMessage().startswith("measure: skipped (")]
    assert [r.levelno for r in skipped] == [logging.WARNING]
    assert skipped[0].getMessage() == "measure: skipped (permission denied for table meeting_video_alignments)"
    assert not any(m.startswith("measure done") for m in caplog.messages)

    # the same handling mid-pass: a database error on the second save ends the pass with the
    # counts so far and nothing left in the work folder
    cands = [_cand(82, "one", 1002, "2502"), _cand(83, "two", 1003, "2503"), _cand(84, "three", 1004, "2504")]
    conn, fdb = FakeConn(), FakeDB(cands, save_error_at=1)
    seen = _wire(monkeypatch, fdb)
    counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)
    assert counts == {"passed": 1, "rejected": 0, "failed": 0}
    assert fdb.statuses() == [("one", "passed")] and conn.rollbacks >= 2
    assert _granicus_fetches(seen) == [GRANICUS + "2502", GRANICUS + "2503"]
    assert _left_in(cfg.work_dir) == []

    # and an error that is no database error and escapes the per-recording handling
    conn, fdb = FakeConn(), FakeDB(cands[:1], backlog_error=RuntimeError("no backlog today"))
    seen = _wire(monkeypatch, fdb)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)
    assert counts == {"passed": 1, "rejected": 0, "failed": 0}
    assert "measure: skipped (RuntimeError: no backlog today)" in caplog.messages


def test_an_archived_audio_flac_is_the_granicus_source_and_no_granicus_url_is_fetched(
        monkeypatch, tmp_path):
    from transcriber import inputs, measure
    cfg, conn = _cfg(tmp_path), FakeConn()
    flac = inputs.audio_path(cfg.archive_dir, 3184)
    flac.parent.mkdir(parents=True)
    flac.write_bytes(b"fLaC")
    fdb = FakeDB([_cand(91, "FR84h22hQvA", 3184, "2026")])
    seen = _wire(monkeypatch, fdb)
    counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)

    assert counts == {"passed": 1, "rejected": 0, "failed": 0}
    assert seen.fetches[0] == (str(flac), "align-3184.wav", 8000)
    assert _granicus_fetches(seen) == []
    assert seen.sleeps == []                                  # no request to Granicus, no pause owed
    assert _left_in(cfg.work_dir) == []
    assert _left_in(cfg.archive_dir) == ["3184", "audio.flac"] and flac.read_bytes() == b"fLaC"


def test_main_measures_before_the_engine_loads_and_meeting_id_skips_the_measuring(monkeypatch, tmp_path):
    import transcriber.engine
    events, kept = [], {}
    conn = FakeConn()

    class RecordingEngine:
        def __init__(self, **kw):
            events.append("engine")

    class QuietStop:                       # the real _Stop installs signal handlers
        requested = False

    def fake_connect(url):
        events.append("connect")
        return conn

    def fake_measure_pass(conn_, cfg, **kw):
        events.append("measure")
        kept["measure"] = (conn_, cfg, kw)
        return {"passed": 0, "rejected": 0, "failed": 0}

    def fake_run_loop(conn_, engine, cfg, **kw):
        events.append("loop")
        kept["loop"] = (conn_, engine, cfg, kw)
        return {"uploaded": 0, "failed": 0, "low_speech": 0}

    monkeypatch.setattr(cli, "load_dotenv", lambda: None)      # the checkout's own .env stays out of it
    for name in ("TRANSCRIBER_MEASURE_LIMIT", "TRANSCRIBER_LIMIT", "TRANSCRIBER_SINCE",
                 "TRANSCRIBER_RETRY_FAILED", "TRANSCRIBER_MAX_CONSECUTIVE_FAILURES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRANSCRIBER_DATABASE_URL", "postgresql://transcriber@db.invalid/railway?sslmode=require")
    monkeypatch.setenv("TRANSCRIBER_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("TRANSCRIBER_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(cli.tdb, "connect", fake_connect)
    monkeypatch.setattr(cli, "measure_pass", fake_measure_pass)
    monkeypatch.setattr(transcriber.engine, "FasterWhisperEngine", RecordingEngine)
    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    monkeypatch.setattr(cli, "_Stop", QuietStop)

    assert cli.main([]) == 0
    assert events == ["connect", "measure", "engine", "loop"]
    m_conn, m_cfg, m_kw = kept["measure"]
    l_conn, l_engine, l_cfg, l_kw = kept["loop"]
    assert m_conn is conn and l_conn is conn and conn.closed
    assert isinstance(l_engine, RecordingEngine)
    assert m_kw["limit"] == 20 == m_cfg.measure_limit          # the default
    assert m_kw["deadline"] is None                            # no --max-hours
    assert isinstance(m_kw["stop"], QuietStop) and l_kw["stop_flag"] is m_kw["stop"]   # one Ctrl-C for both
    assert isinstance(l_kw["started"], float)
    assert m_cfg.version == "0.5.0"

    events.clear()
    assert cli.main(["--measure-limit", "7", "--max-hours", "2"]) == 0
    assert events == ["connect", "measure", "engine", "loop"]
    assert kept["measure"][2]["limit"] == 7
    assert kept["measure"][2]["deadline"] == kept["loop"][3]["started"] + 2 * 3600   # one clock for both

    events.clear()
    monkeypatch.setenv("TRANSCRIBER_MEASURE_LIMIT", "3")
    assert cli.main([]) == 0
    assert kept["measure"][2]["limit"] == 3

    events.clear()
    assert cli.main(["--meeting-id", "5"]) == 1                # nothing uploaded, as exit_code says
    assert events == ["connect", "engine", "loop"]             # no measure_pass
    assert kept["loop"][3] == {}                               # run_loop called as it is today


def test_granicus_fetch_error_on_a_meeting_with_three_recordings_saves_three_failed_rows_and_goes_on(
        monkeypatch, tmp_path, caplog):
    from transcriber import measure
    cfg, conn = _cfg(tmp_path), FakeConn()
    fdb = FakeDB([_cand(101, "part1", 1101, "2601"), _cand(102, "part2", 1101, "2601"),
                  _cand(103, "part3", 1101, "2601"), _cand(104, "whole", 1102, "2602")])
    message = "ffmpeg could not read https://bhamal.granicus.com/...: HTTP error 404 Not Found"
    seen = _wire(monkeypatch, fdb, granicus_errors={"2601": AudioFetchError(message)})
    with caplog.at_level(logging.INFO):
        counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)

    # three failed rows, one failed fetch: counted by rows the pass would have ended here
    assert counts == {"passed": 1, "rejected": 0, "failed": 3}
    assert fdb.statuses() == [("part1", "failed"), ("part2", "failed"), ("part3", "failed"),
                              ("whole", "passed")]
    assert all(s.reason == f"AudioFetchError: {message}" and s.measurement is None for s in fdb.saved[:3])
    assert seen.downloads == [("yt-whole", measure.MEASURE_YTDLP_FORMAT)]   # no YouTube audio for the broken clip
    assert sum(m.startswith("measure meeting 1101 clip 2601 video part") for m in caplog.messages) == 3
    assert seen.sleeps == [3.0, 3.0]                          # Granicus was asked twice, and paused for twice
    assert _left_in(cfg.work_dir) == []


def test_an_unexpected_error_on_one_recording_saves_failed_with_its_class_name_and_goes_on(
        monkeypatch, tmp_path):
    from transcriber import measure
    cfg, conn = _cfg(tmp_path), FakeConn()
    fdb = FakeDB([_cand(111, "abc", 1201, "2701"), _cand(112, "def", 1202, "2702")])
    seen = _wire(monkeypatch, fdb, youtube_errors={"abc": RuntimeError("boom")})
    counts = measure.measure_pass(conn, cfg, limit=20, sleep=seen.sleeps.append)

    assert counts == {"passed": 1, "rejected": 0, "failed": 1}
    assert fdb.statuses() == [("abc", "failed"), ("def", "passed")]
    assert fdb.saved[0].reason == "RuntimeError: boom" and fdb.saved[0].measurement is None
    assert _left_in(cfg.work_dir) == []
