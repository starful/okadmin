"""Unified calendar API (TODO + ops events)."""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from auth import requires_auth
from calendar_service import (
    all_calendar_events,
    calendar_days_view,
    default_calendar_range,
    event_to_fullcalendar,
    parse_calendar_id,
    todo_to_fullcalendar,
)
from config import (
    CALENDAR_WINDOW_DAYS,
    COL_OPS_EVENTS,
    COL_TODOS,
    EVENT_KINDS,
)
from firestore_db import doc_to_dict, firestore_unavailable_message, get_db

calendar_bp = Blueprint("calendar", __name__, url_prefix="/api/calendar")


def _require_db():
    db = get_db()
    if db is None:
        return None, (jsonify({"error": firestore_unavailable_message()}), 503)
    return db, None


@calendar_bp.route("/days")
@requires_auth
def calendar_days():
    """Day-grouped work log (default: today ± CALENDAR_WINDOW_DAYS)."""
    db, err = _require_db()
    if err:
        return err
    anchor_s = request.args.get("anchor")
    start_s = request.args.get("start")
    end_s = request.args.get("end")
    anchor_d: date | None = None
    if anchor_s:
        try:
            anchor_d = date.fromisoformat(anchor_s[:10])
        except ValueError:
            return jsonify({"error": "invalid anchor date"}), 400
        start_d = anchor_d - timedelta(days=CALENDAR_WINDOW_DAYS)
        end_d = anchor_d + timedelta(days=CALENDAR_WINDOW_DAYS)
    elif start_s and end_s:
        try:
            start_d = date.fromisoformat(start_s[:10])
            end_d = date.fromisoformat(end_s[:10])
        except ValueError:
            return jsonify({"error": "invalid start/end date"}), 400
    else:
        anchor_d = date.today()
        start_d, end_d = default_calendar_range()
    if start_d > end_d:
        return jsonify({"error": "start after end"}), 400
    if anchor_d is None:
        anchor_d = start_d + timedelta(days=(end_d - start_d).days // 2)
    return jsonify(calendar_days_view(db, start_d, end_d, anchor=anchor_d))


@calendar_bp.route("/events")
@requires_auth
def calendar_events():
    db, err = _require_db()
    if err:
        return err
    return jsonify(all_calendar_events(db))


@calendar_bp.route("/events", methods=["POST"])
@requires_auth
def calendar_create():
    db, err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    kind = data.get("kind") or "manual"
    title = (data.get("title") or "").strip()
    start_at = data.get("start_at") or data.get("start")
    if not title or not start_at:
        return jsonify({"error": "title and start_at required"}), 400

    from firebase_admin import firestore as fs

    if kind == "todo":
        payload = {
            "title": title,
            "body": data.get("notes") or data.get("body") or "",
            "site_id": data.get("site_id") or "",
            "status": data.get("status") or "open",
            "priority": data.get("priority") or "normal",
            "due_at": start_at,
            "created_at": fs.SERVER_TIMESTAMP,
        }
        ref = db.collection(COL_TODOS).add(payload)[1]
        return jsonify(todo_to_fullcalendar(doc_to_dict(ref.get()))), 201

    if kind not in EVENT_KINDS:
        kind = "manual"
    all_day = bool(data.get("all_day")) or "T" not in str(start_at)
    if all_day and "T" in str(start_at):
        start_at = str(start_at)[:10]
    payload = {
        "title": title,
        "site_id": data.get("site_id") or "",
        "kind": kind,
        "start_at": start_at,
        "end_at": data.get("end_at") or data.get("end") or "",
        "all_day": all_day,
        "notes": data.get("notes") or "",
        "created_at": fs.SERVER_TIMESTAMP,
    }
    ref = db.collection(COL_OPS_EVENTS).add(payload)[1]
    return jsonify(event_to_fullcalendar(doc_to_dict(ref.get()))), 201


@calendar_bp.route("/events/<cal_id>", methods=["PUT"])
@requires_auth
def calendar_update(cal_id: str):
    db, err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    collection, record_id = parse_calendar_id(cal_id)

    if collection == "todos":
        ref = db.collection(COL_TODOS).document(record_id)
        if not ref.get().exists:
            return jsonify({"error": "not found"}), 404
        allowed = {"title", "body", "site_id", "status", "priority", "due_at"}
        patch = {k: data[k] for k in allowed if k in data}
        if data.get("start_at"):
            patch["due_at"] = data["start_at"]
        if data.get("notes"):
            patch["body"] = data["notes"]
        if patch:
            from firebase_admin import firestore as fs

            if patch.get("status") == "done":
                patch["completed_at"] = fs.SERVER_TIMESTAMP
            ref.update(patch)
        return jsonify(todo_to_fullcalendar(doc_to_dict(ref.get())))

    ref = db.collection(COL_OPS_EVENTS).document(record_id)
    if not ref.get().exists:
        return jsonify({"error": "not found"}), 404
    allowed = {"title", "site_id", "kind", "start_at", "end_at", "all_day", "notes"}
    patch = {k: data[k] for k in allowed if k in data}
    if data.get("start"):
        patch["start_at"] = data["start"]
    if data.get("end"):
        patch["end_at"] = data["end"]
    if patch:
        ref.update(patch)
    return jsonify(event_to_fullcalendar(doc_to_dict(ref.get())))


@calendar_bp.route("/events/<cal_id>", methods=["DELETE"])
@requires_auth
def calendar_delete(cal_id: str):
    db, err = _require_db()
    if err:
        return err
    collection, record_id = parse_calendar_id(cal_id)
    col = COL_TODOS if collection == "todos" else COL_OPS_EVENTS
    ref = db.collection(col).document(record_id)
    if not ref.get().exists:
        return jsonify({"error": "not found"}), 404
    ref.delete()
    return jsonify({"ok": True})
