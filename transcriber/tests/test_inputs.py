import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from transcriber import cli, inputs
from transcriber.audio import AudioFetchError
from transcriber.engine import DiarTurn, RawSegment, Word, build_output


class _Eng:
    name = "faster-whisper"; asr_model = "large-v3"; diarization_model = "pyannote/speaker-diarization-3.1"


def _raw():
    words = [Word(0.5, 1.0, " Good", 0.9), Word(1.0, 1.4, " morning.", 0.8),
             Word(2.0, 2.5, " Council", 0.9), Word(2.5, 3.0, " Member", 0.9), Word(3.0, 3.6, " O", 0.7),
             Word(3.6, 4.0, "'Quinn.", 0.7)]
    return [RawSegment(0.0, 4.0, " Good morning. Council Member O'Quinn.", -0.2, 0.01, words=words),
            RawSegment(10.0, 11.0, " Thank you for watching.", -0.8, 0.3)]


TURNS = [DiarTurn(0.0, 1.8, "SPEAKER_01"), DiarTurn(1.8, 11.0, "SPEAKER_00")]
EMB = {"SPEAKER_00": [0.1, 0.2], "SPEAKER_01": [0.3, 0.4]}


def test_raw_and_diarization_round_trip(tmp_path):
    rp, dp = tmp_path / "7" / "raw.json", tmp_path / "7" / "diarization.json"
    inputs.write_raw(rp, _raw(), meeting_id=7, initial_prompt="Birmingham City Council.",
                     audio_duration_s=200.0, audio_sha256="ab" * 32, engine=_Eng())
    inputs.write_diarization(dp, TURNS, EMB)
    meta, raw = inputs.read_raw(rp)
    assert raw == _raw()
    assert meta["meeting_id"] == 7 and meta["initial_prompt"] == "Birmingham City Council."
    assert meta["asr_model"] == "large-v3" and meta["audio_sha256"] == "ab" * 32
    assert inputs.read_diarization(dp) == (TURNS, EMB)


def test_replay_matches_build_output(tmp_path):
    inputs.write_raw(inputs.raw_path(tmp_path, 7), _raw(), meeting_id=7, initial_prompt="",
                     audio_duration_s=200.0, audio_sha256="ab" * 32, engine=_Eng())
    inputs.write_diarization(inputs.diarization_path(tmp_path, 7), TURNS, EMB)
    replayed = inputs.replay(tmp_path, 7, 3)
    direct = build_output(7, 3, _Eng(), _raw(), TURNS, EMB, 200.0, "ab" * 32, None, initial_prompt="")
    assert replayed.to_json() == direct.to_json()
    assert [s.text for s in replayed.segments if not s.is_silence] == ["Good morning.", "Council Member O'Quinn."]


class _Runner:
    """Records ffmpeg calls; writes the output file (last argument) unless told to fail."""
    def __init__(self, fail_on: str | None = None):
        self.calls = []; self.fail_on = fail_on
    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if self.fail_on and self.fail_on in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        Path(cmd[-1]).write_bytes(b"x" * 100)
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_get_audio_fetches_and_keeps_flac_then_serves_from_cache(tmp_path):
    fetched = []
    def fetch(src, wav):
        fetched.append(src); Path(wav).write_bytes(b"RIFF" + b"\0" * 100)
    wav, flac = tmp_path / "work" / "7.wav", tmp_path / "7" / "audio.flac"
    wav.parent.mkdir()
    run = _Runner()
    assert inputs.get_audio("https://clip", wav, flac, fetch=fetch, runner=run) is False
    assert fetched == ["https://clip"] and flac.exists() and not flac.with_name("audio.flac.part").exists()
    wav.unlink()
    assert inputs.get_audio("https://clip", wav, flac, fetch=fetch, runner=run) is True
    assert fetched == ["https://clip"] and wav.exists()          # no second download
    assert run.calls[-1][run.calls[-1].index("-i") + 1] == str(flac)


def test_get_audio_refetches_when_cached_flac_is_unreadable(tmp_path):
    flac = tmp_path / "7" / "audio.flac"; flac.parent.mkdir(); flac.write_bytes(b"junk")
    wav = tmp_path / "7.wav"
    fetched = []
    def fetch(src, w):
        fetched.append(src); Path(w).write_bytes(b"RIFF")
    run = _Runner(fail_on="pcm_s16le")      # the decode fails, the re-encode succeeds
    assert inputs.get_audio("https://clip", wav, flac, fetch=fetch, runner=run) is False
    assert fetched == ["https://clip"] and flac.read_bytes() == b"x" * 100


def test_get_audio_keeps_going_when_flac_cannot_be_written(tmp_path):
    wav, flac = tmp_path / "7.wav", tmp_path / "7" / "audio.flac"
    def fetch(src, w):
        Path(w).write_bytes(b"RIFF")
    assert inputs.get_audio("https://clip", wav, flac, fetch=fetch, runner=_Runner(fail_on="flac")) is False
    assert wav.exists() and not flac.exists()


def test_get_audio_fetch_failure_raises(tmp_path):
    def fetch(src, w):
        raise AudioFetchError("HTTP 403")
    with pytest.raises(AudioFetchError):
        inputs.get_audio("https://clip", tmp_path / "7.wav", tmp_path / "7" / "audio.flac",
                         fetch=fetch, runner=_Runner())


@pytest.fixture
def cfg(tmp_path):
    return cli.Config(since=date(2025, 10, 28), limit=10, max_hours=None, host="test",
                      work_dir=tmp_path / "work", archive_dir=tmp_path / "archive",
                      dry_run_file=None, version="0.4.0")


class _Conn:
    def __init__(self): self.rollbacks = 0
    def commit(self): raise AssertionError("the cache and capture passes never commit")
    def rollback(self): self.rollbacks += 1


def _wire(monkeypatch, *, source="1969"):
    monkeypatch.setattr(cli.tdb, "meeting_source", lambda conn, mid: source)
    monkeypatch.setattr(cli.tdb, "roster_for_meeting", lambda conn, mid: ["Darrell O'Quinn"])
    def fake_fetch(src, out_wav, **kw):
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True); Path(out_wav).write_bytes(b"RIFF")
    monkeypatch.setattr(cli, "fetch_audio", fake_fetch)
    monkeypatch.setattr(inputs, "store_flac", lambda wav, flac, **kw: (flac.parent.mkdir(parents=True, exist_ok=True),
                                                                      flac.write_bytes(b"fLaC")))
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: 200.0)
    monkeypatch.setattr(cli, "sha256_file", lambda p: "ab" * 32)


def test_cache_audio_fetches_once_and_skips_ineligible(monkeypatch, cfg):
    _wire(monkeypatch)
    cfg.work_dir.mkdir(parents=True)
    assert cli.cache_audio(_Conn(), cfg, 8) == "fetched"
    assert inputs.audio_path(cfg.archive_dir, 8).exists()
    assert not (cfg.work_dir / "8.wav").exists()
    assert cli.cache_audio(_Conn(), cfg, 8) == "cached"
    monkeypatch.setattr(cli.tdb, "meeting_source", lambda conn, mid: None)
    assert cli.cache_audio(_Conn(), cfg, 2544) == "ineligible"


class _FakeEngine:
    name = "fake"; asr_model = "tiny"; diarization_model = None
    def transcribe(self, wav, prompt):
        self.prompt = prompt; return _raw()
    def diarize(self, wav):
        return TURNS, EMB


def test_capture_inputs_writes_both_files_without_db_writes(monkeypatch, cfg):
    _wire(monkeypatch)
    monkeypatch.setattr(cli, "get_audio", lambda src, wav, flac, **kw: Path(wav).parent.mkdir(parents=True, exist_ok=True)
                        or Path(wav).write_bytes(b"RIFF") and True)
    conn, eng = _Conn(), _FakeEngine()
    assert cli.capture_inputs(conn, eng, cfg, 8) == "captured"
    meta, raw = inputs.read_raw(inputs.raw_path(cfg.archive_dir, 8))
    assert raw == _raw() and "O'Quinn" in meta["initial_prompt"] and meta["audio_duration_s"] == 200.0
    assert inputs.read_diarization(inputs.diarization_path(cfg.archive_dir, 8)) == (TURNS, EMB)
    assert conn.rollbacks == 1 and not (cfg.work_dir / "8.wav").exists()
    # the replay of what was captured is a valid upload
    cli.replay_meeting(cfg, 8)
    out = json.loads((cfg.archive_dir / "8" / "replay.json").read_text())
    assert out["meeting_id"] == 8 and out["version"] == cli.TRANSCRIPT_VERSION


def test_process_claim_writes_raw_and_diarization(monkeypatch, cfg):
    from tests.test_cli_loop import FakeConn, FakeDB, FakeEngine, _claim, _wire as wire_loop
    fdb = FakeDB([_claim(1)]); wire_loop(monkeypatch, fdb)
    monkeypatch.setattr(inputs, "store_flac", lambda wav, flac, **kw: None)
    assert cli.run_loop(FakeConn(), FakeEngine(), cfg)["uploaded"] == 1
    assert inputs.raw_path(cfg.archive_dir, 101).exists()
    assert inputs.diarization_path(cfg.archive_dir, 101).exists()


def test_main_replay_needs_no_database(monkeypatch, tmp_path):
    archive = tmp_path / "archive"
    inputs.write_raw(inputs.raw_path(archive, 7), _raw(), meeting_id=7, initial_prompt="",
                     audio_duration_s=200.0, audio_sha256="ab" * 32, engine=_Eng())
    inputs.write_diarization(inputs.diarization_path(archive, 7), TURNS, EMB)
    monkeypatch.delenv("TRANSCRIBER_DATABASE_URL", raising=False)
    monkeypatch.setenv("TRANSCRIBER_ARCHIVE_DIR", str(archive))
    monkeypatch.setenv("TRANSCRIBER_WORK_DIR", str(tmp_path / "work"))
    assert cli.main(["--replay", "7"]) == 0
    assert (archive / "7" / "replay.json").exists()
    assert cli.main(["--replay", "99"]) == 1          # no inputs archived for 99
