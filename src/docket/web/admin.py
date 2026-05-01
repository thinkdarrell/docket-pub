"""Admin routes — roster management and data operations."""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from docket.db import db, db_cursor
from docket.services import query

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def require_login():
    """All admin routes require authentication."""
    # Auth blueprint handles /admin/login and /admin/logout itself
    from flask import session

    if request.endpoint and request.endpoint.startswith("admin."):
        if "admin_user" not in session:
            return redirect(url_for("auth.login", next=request.path))


# --- Council member management ----------------------------------------------


@bp.route("/members/")
def list_members():
    """List all council members across all cities."""
    municipalities = query.list_municipalities()
    members_by_city = {}
    for muni in municipalities:
        members_by_city[muni["slug"]] = {
            "municipality": muni,
            "members": query.list_council_members(muni["slug"], active_only=False),
        }

    return render_template(
        "admin/members.html",
        members_by_city=members_by_city,
    )


@bp.route("/members/add", methods=["GET", "POST"])
def add_member():
    """Add a new council member."""
    municipalities = query.list_municipalities()

    if request.method == "POST":
        slug = request.form["municipality"]
        name = request.form["name"].strip()
        district_name = request.form.get("district", "").strip()
        email = request.form.get("email", "").strip() or None
        photo_url = request.form.get("photo_url", "").strip() or None

        if not name or not slug:
            abort(400)

        muni = query.get_municipality(slug)
        if not muni:
            abort(404)

        with db_cursor() as cur:
            # Resolve district if provided
            district_id = None
            if district_name:
                cur.execute(
                    "SELECT id FROM districts WHERE municipality_id = %s AND name = %s",
                    (muni["id"], district_name),
                )
                row = cur.fetchone()
                if row:
                    district_id = row["id"]

            cur.execute(
                """
                INSERT INTO council_members
                    (municipality_id, district_id, name, email, photo_url, active)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                """,
                (muni["id"], district_id, name, email, photo_url),
            )

        return redirect(url_for("admin.list_members"))

    # GET — show form
    # Fetch districts for each municipality
    districts_by_city = {}
    for muni in municipalities:
        with db_cursor() as cur:
            cur.execute(
                "SELECT name FROM districts WHERE municipality_id = %s ORDER BY number",
                (muni["id"],),
            )
            districts_by_city[muni["slug"]] = [row["name"] for row in cur.fetchall()]

    return render_template(
        "admin/member_form.html",
        municipalities=municipalities,
        districts_by_city=districts_by_city,
        member=None,
    )


@bp.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
def edit_member(member_id):
    """Edit an existing council member."""
    member = query.get_council_member(member_id)
    if not member:
        abort(404)

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form.get("email", "").strip() or None
        photo_url = request.form.get("photo_url", "").strip() or None
        active = request.form.get("active") == "on"

        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE council_members
                    SET name = %s, email = %s, photo_url = %s, active = %s
                    WHERE id = %s
                    """,
                    (name, email, photo_url, active, member_id),
                )

        return redirect(url_for("admin.list_members"))

    return render_template(
        "admin/member_form.html",
        member=member,
        municipalities=None,
        districts_by_city=None,
    )


@bp.route("/members/<int:member_id>/deactivate", methods=["POST"])
def deactivate_member(member_id):
    """Deactivate a council member (term ended)."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE council_members SET active = FALSE WHERE id = %s",
                (member_id,),
            )

    return redirect(url_for("admin.list_members"))
