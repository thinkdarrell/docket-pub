# src/docket/web/admin_transcripts.py
"""Admin: discrepancy review queue, held transcripts, speaker correction (Task 15)."""
from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from docket.db import db_cursor
from docket.services import discrepancies as D
from docket.services import speaker_correction as SC
from docket.web.csrf import validate_csrf

bp = Blueprint("admin_transcripts", __name__, url_prefix="/admin")
PAGE = 50
CATEGORIES = ("vote_outcome", "omission", "addition", "wording", "sequence", "speaker")


@bp.before_request
def _guard():
    if request.endpoint and request.endpoint.startswith("admin_transcripts."):
        if "admin_user" not in session:
            return redirect(url_for("auth.login", next=request.path))
        validate_csrf()


def _back():
    ref = urlsplit(request.headers.get("Referer") or "")
    ref_local = (ref.path + (f"?{ref.query}" if ref.query else "")) if ref.netloc == request.host else None
    for cand in (request.form.get("next"), ref_local):
        if cand and cand.startswith("/") and not cand.startswith("//"):
            return cand
    return url_for("admin_transcripts.review_discrepancies")


@bp.route("/review/discrepancies")
def review_discrepancies():
    state = request.args.get("state", "proposed")
    category = request.args.get("category") or None
    meeting_id = request.args.get("meeting_id", type=int)
    offset = max(0, request.args.get("offset", 0, type=int))
    held = D.held_transcripts() if state == "held" else []
    rows = [] if state == "held" else D.list_queue(state=state, category=category, meeting_id=meeting_id, limit=PAGE + 1, offset=offset)
    next_offset = offset + PAGE if len(rows) > PAGE else None
    return render_template("admin/review_discrepancies.html", rows=rows[:PAGE], held=held, state=state, category=category,
                           meeting_id=meeting_id, offset=offset, next_offset=next_offset, categories=CATEGORIES,
                           gate=D.approval_ratio(), states=D.QUEUE_STATES + ("held",))


def _fail(discrepancy_id: int, e: Exception):
    """A state race or a bad excerpt is a reviewer-facing message, not an error page."""
    flash(f"Discrepancy #{discrepancy_id} not changed: {e}", "error")
    return redirect(_back())


@bp.post("/review/discrepancies/<int:discrepancy_id>/approve")
def approve(discrepancy_id: int):
    try:
        D.approve(discrepancy_id, session.get("admin_user", "unknown"), request.form.get("note"))
    except LookupError:
        abort(404)
    except D.DiscrepancyStateError as e:
        return _fail(discrepancy_id, e)
    flash(f"Discrepancy #{discrepancy_id} approved.")
    return redirect(_back())


@bp.post("/review/discrepancies/<int:discrepancy_id>/reject")
def reject(discrepancy_id: int):
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        abort(400, "reason required")
    try:
        D.reject(discrepancy_id, session.get("admin_user", "unknown"), reason)
    except D.DiscrepancyStateError as e:
        return _fail(discrepancy_id, e)
    flash(f"Discrepancy #{discrepancy_id} rejected.")
    return redirect(_back())


@bp.post("/review/discrepancies/<int:discrepancy_id>/edit-approve")
def edit_approve(discrepancy_id: int):
    try:
        D.edit_and_approve(discrepancy_id, session.get("admin_user", "unknown"),
                           request.form.get("admin_title", ""), request.form.get("admin_description", ""),
                           request.form.get("transcript_excerpt"), request.form.get("minutes_excerpt"))
    except LookupError:
        abort(404)
    except (D.CitationNotFound, D.DiscrepancyStateError) as e:
        return _fail(discrepancy_id, e)
    flash(f"Discrepancy #{discrepancy_id} edited and approved. Only what docket.pub shows changed; the model text is kept.")
    return redirect(_back())


@bp.post("/transcripts/<int:meeting_id>/retry")
def retry_transcript(meeting_id: int):
    try:
        status = D.retry_transcript(meeting_id)
    except D.DiscrepancyStateError as e:
        flash(f"Transcript for meeting {meeting_id} not changed: {e}", "error")
        return redirect(_back())
    flash(f"Transcript for meeting {meeting_id} reset to {status}; the next cron tick picks it up.")
    return redirect(_back())


@bp.route("/transcripts/<int:meeting_id>/speakers")
def speaker_correction(meeting_id: int):
    clusters = SC.list_clusters(meeting_id)
    if not clusters:
        abort(404)
    with db_cursor() as cur:
        cur.execute("""SELECT m.id, m.title, m.meeting_date, mu.slug FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id
                        WHERE m.id = %s""", [meeting_id])
        meeting = dict(cur.fetchone())
    return render_template("admin/speaker_correction.html", meeting=meeting, clusters=clusters,
                           roster=SC.roster_options(meeting_id), roles=SC.ROLES)


@bp.post("/transcripts/<int:meeting_id>/speakers/<cluster_label>")
def reassign_speaker(meeting_id: int, cluster_label: str):
    member = request.form.get("council_member_id", type=int)
    try:
        SC.reassign(meeting_id, cluster_label, council_member_id=member, display_name=request.form.get("display_name"),
                    role=request.form.get("role", "unknown"), actor=session.get("admin_user", "unknown"))
    except ValueError as e:
        abort(400, str(e))
    except LookupError:
        abort(404)
    flash(f"Cluster {cluster_label} reassigned.")
    return redirect(url_for("admin_transcripts.speaker_correction", meeting_id=meeting_id))


@bp.post("/transcripts/<int:meeting_id>/speakers/<cluster_label>/release")
def release_speaker(meeting_id: int, cluster_label: str):
    try:
        SC.release(meeting_id, cluster_label)
    except LookupError:
        abort(404)
    flash(f"Cluster {cluster_label} released; the next speaker run may re-resolve it.")
    return redirect(url_for("admin_transcripts.speaker_correction", meeting_id=meeting_id))
