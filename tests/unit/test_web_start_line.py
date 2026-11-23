"""The line that starts the web service, in ``Dockerfile`` (which production
runs) and in ``Procfile`` (which a reader would take for it), pinned (plan
``site-answers-while-a-page-loads``, M1).

Three things are held here. The text of both lines: migrations first, then
``exec gunicorn`` with one worker, four threads, and the two database limits
handed to the web process through gunicorn's ``--env``. What gunicorn does
with the ``Dockerfile``'s options: a real gunicorn, started on this machine
with them and a stub application, answers a second request while a first is
still held, and hands the application the two settings. And what the database
library does with the settings: a connection opened under them reports a
30-second statement limit.

No request leaves the machine, and the stub keeps the behavioural half free
of the docket application.
"""

import json
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

LINE_ENV = {"PGOPTIONS": "-c statement_timeout=30000", "PGCONNECT_TIMEOUT": "10"}

STUB = '''\
import os
import time


def app(environ, start_response):
    path = environ.get("PATH_INFO", "")
    body = b"ok"
    if path == "/slow":
        folder = os.environ["STUB_DIR"]
        open(os.path.join(folder, "slow_entered"), "w").close()
        release = os.path.join(folder, "release_slow")
        end = time.monotonic() + 4
        while not os.path.exists(release) and time.monotonic() < end:
            time.sleep(0.02)
    elif path == "/env":
        body = (
            os.environ.get("PGOPTIONS", "-") + "|" + os.environ.get("PGCONNECT_TIMEOUT", "-")
        ).encode()
    start_response(
        "200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))]
    )
    return [body]
'''


def start_line(name: str) -> str:
    """The web start line of ``Dockerfile`` or ``Procfile`` as one string."""
    lines = (ROOT / name).read_text().splitlines()
    if name == "Dockerfile":
        cmd = [line for line in lines if line.startswith("CMD ")][-1]
        return json.loads(cmd[len("CMD "):])[-1]
    web = [line for line in lines if line.startswith("web:")][0]
    return web[len("web:"):].strip()


def _gunicorn_part(name: str) -> str:
    parts = [part.strip() for part in start_line(name).split("&&")]
    (part,) = [p for p in parts if p.startswith(("gunicorn ", "exec gunicorn "))]
    return part


def gunicorn_tokens(name: str) -> list[str]:
    """The gunicorn command of the start line as the shell would split it,
    without a leading ``exec``."""
    tokens = shlex.split(_gunicorn_part(name))
    if tokens[0] == "exec":
        tokens = tokens[1:]
    return tokens


def line_env(name: str) -> dict[str, str]:
    """The ``NAME=VALUE`` settings the line gives gunicorn through ``--env``."""
    tokens = gunicorn_tokens(name)
    out = {}
    for i, token in enumerate(tokens[:-1]):
        if token == "--env":
            key, _, value = tokens[i + 1].partition("=")
            out[key] = value
    return out


@pytest.mark.parametrize("name", ["Dockerfile", "Procfile"])
def test_start_line_asks_for_one_worker_and_four_threads(name):
    import gunicorn.config
    import gunicorn.workers.gthread

    tokens = gunicorn_tokens(name)
    assert tokens.count("--workers") == 1
    assert tokens[tokens.index("--workers") + 1] == "1"
    assert tokens.count("--threads") == 1
    assert tokens[tokens.index("--threads") + 1] == "4"
    assert "--worker-class" not in tokens
    assert "-k" not in tokens
    assert _gunicorn_part(name).startswith("exec gunicorn ")
    assert line_env(name) == LINE_ENV

    cfg = gunicorn.config.Config()
    parsed = cfg.parser().parse_args(tokens[1:])
    for key, value in vars(parsed).items():
        if value is None or key == "args":
            continue
        cfg.set(key.lower(), value)
    assert cfg.threads == 4
    assert cfg.workers == 1
    assert cfg.worker_class is gunicorn.workers.gthread.ThreadWorker


def test_both_start_lines_run_the_migrations_then_the_same_application():
    for name in ("Dockerfile", "Procfile"):
        first = start_line(name).split("&&")[0].strip()
        assert first == "python -m docket.migrations.runner", name
        tokens = gunicorn_tokens(name)
        assert tokens[:2] == ["gunicorn", "docket.web:create_app()"], name
        assert tokens[tokens.index("--bind") + 1] == "0.0.0.0:${PORT:-5000}", name


def _get(url: str, timeout: float) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read().decode()


def test_the_dockerfile_options_answer_a_second_request_while_one_is_held(tmp_path):
    (tmp_path / "stubapp.py").write_text(STUB)
    log = tmp_path / "gunicorn.log"

    options = gunicorn_tokens("Dockerfile")[2:]
    at = options.index("--bind")
    options = options[:at] + options[at + 2:]

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("WEB_CONCURRENCY", "GUNICORN_CMD_ARGS", "PGOPTIONS", "PGCONNECT_TIMEOUT")
    }
    env["STUB_DIR"] = str(tmp_path)

    def log_text() -> str:
        return log.read_text() if log.exists() else "(no gunicorn log)"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "gunicorn", "stubapp:app", *options,
            "--bind", "127.0.0.1:0",
            "--chdir", str(tmp_path),
            "--no-control-socket",
            "--error-logfile", str(log),
        ],
        env=env,
    )
    try:
        port = None
        end = time.monotonic() + 20
        while time.monotonic() < end:
            text = log_text()
            if "Listening at: http://127.0.0.1:" in text and "Booting worker with pid" in text:
                after = text.split("Listening at: http://127.0.0.1:", 1)[1]
                digits = ""
                for ch in after:
                    if not ch.isdigit():
                        break
                    digits += ch
                port = int(digits)
                break
            time.sleep(0.05)
        assert port is not None, log_text()
        base = f"http://127.0.0.1:{port}"

        slow: dict = {}

        def ask_slow():
            try:
                slow["answer"] = _get(base + "/slow", 15)
            except BaseException as exc:  # kept, and re-raised by the test
                slow["error"] = exc
            slow["finished"] = time.monotonic()

        thread = threading.Thread(target=ask_slow)
        thread.start()
        try:
            entered = tmp_path / "slow_entered"
            end = time.monotonic() + 10
            while not entered.exists() and time.monotonic() < end:
                time.sleep(0.01)
            assert entered.exists(), log_text()

            fast = _get(base + "/fast", 10)
            fast_finished = time.monotonic()
        finally:
            (tmp_path / "release_slow").write_text("")
            thread.join()

        if "error" in slow:
            raise slow["error"]
        assert slow["answer"] == (200, "ok")
        assert fast == (200, "ok")
        assert fast_finished < slow["finished"], (
            "/fast was answered only after /slow: the options answer one request at a time"
        )

        assert _get(base + "/env", 10) == (200, "-c statement_timeout=30000|10")
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(10)


def test_a_connection_under_the_dockerfile_settings_has_a_30_second_statement_limit(monkeypatch):
    from docket.db import db

    settings = line_env("Dockerfile")
    assert "PGOPTIONS" in settings
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW statement_timeout")
            assert cur.fetchone()[0] == "30s"
