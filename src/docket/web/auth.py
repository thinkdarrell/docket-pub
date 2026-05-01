"""Admin authentication — session-based login."""

from __future__ import annotations

import functools

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from docket.db import db_cursor

bp = Blueprint("auth", __name__, url_prefix="/admin")


def login_required(view):
    """Decorator that redirects unauthenticated users to the login page."""

    @functools.wraps(view)
    def wrapped(**kwargs):
        if "admin_user" not in session:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)

    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Admin login page."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with db_cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash FROM admin_users WHERE username = %s",
                (username,),
            )
            user = cur.fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["admin_user"] = user["username"]
            next_url = request.args.get("next", url_for("admin.list_members"))
            # Prevent open redirect — only allow relative paths
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("admin.list_members")
            return redirect(next_url)

        flash("Invalid username or password.", "error")

    return render_template("admin/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    """Log out the current admin user."""
    session.clear()
    return redirect(url_for("auth.login"))
