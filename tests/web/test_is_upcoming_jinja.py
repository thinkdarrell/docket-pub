from datetime import date, time

import pytest


@pytest.fixture
def app():
    from docket.web import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


def test_is_upcoming_is_a_jinja_global(app):
    assert "is_upcoming" in app.jinja_env.globals


def test_is_upcoming_renders_truthy_for_future_meeting(app):
    """Pure attribute-access shape (Meeting / RawMeeting dataclass)."""
    class _M:
        def __init__(self, md, st=None):
            self.meeting_date = md
            self.start_time = st

    with app.test_request_context():
        tmpl = app.jinja_env.from_string(
            "{% if is_upcoming(m) %}UP{% else %}OVER{% endif %}"
        )
        # Pick a date well in the future so wall-clock doesn't matter.
        assert tmpl.render(m=_M(date(2099, 1, 1))) == "UP"
        assert tmpl.render(m=_M(date(2000, 1, 1))) == "OVER"


def test_is_upcoming_accepts_dict_rows(app):
    """psycopg DictRow shape (what list_upcoming_meetings returns)."""
    with app.test_request_context():
        tmpl = app.jinja_env.from_string(
            "{% if is_upcoming(m) %}UP{% else %}OVER{% endif %}"
        )
        assert tmpl.render(
            m={"meeting_date": date(2099, 1, 1), "start_time": None}
        ) == "UP"
        assert tmpl.render(
            m={"meeting_date": date(2000, 1, 1), "start_time": None}
        ) == "OVER"


def test_is_upcoming_handles_none_meeting(app):
    """Templates may receive None (e.g., empty rail state). Should not raise."""
    with app.test_request_context():
        tmpl = app.jinja_env.from_string(
            "{% if is_upcoming(m) %}UP{% else %}OVER{% endif %}"
        )
        assert tmpl.render(m=None) == "OVER"
