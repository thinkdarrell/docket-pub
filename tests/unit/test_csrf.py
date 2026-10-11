# tests/unit/test_csrf.py
import pytest
from flask import Flask, session

from docket.web import csrf


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "t"
    app.config["TESTING"] = True
    csrf.register(app)

    @app.route("/tok")
    def tok():
        return csrf.csrf_token()

    @app.route("/post", methods=["POST"])
    def post():
        csrf.validate_csrf()
        return "ok"
    return app


def test_token_is_stable_within_a_session_and_exposed_to_jinja(app):
    c = app.test_client()
    a, b = c.get("/tok").get_data(as_text=True), c.get("/tok").get_data(as_text=True)
    assert a == b and len(a) == 64
    assert app.jinja_env.globals["csrf_token"] is csrf.csrf_token


def test_post_without_token_is_400_and_with_token_is_ok(app):
    c = app.test_client()
    tok = c.get("/tok").get_data(as_text=True)
    assert c.post("/post").status_code == 400
    assert c.post("/post", data={"csrf_token": "wrong"}).status_code == 400
    assert c.post("/post", data={"csrf_token": tok}).status_code == 200
    assert c.post("/post", headers={"X-CSRF-Token": tok}).status_code == 200
