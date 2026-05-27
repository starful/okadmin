"""Operations schedule API (Firestore) for FullCalendar."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import requires_auth
from config import COL_OPS_EVENTS, EVENT_COLORS, EVENT_KINDS
from firestore_db import doc_to_dict, firestore_unavailable_message, get_db

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api/ops-events")


def _require_db():
    db = get_db()
    if db is None:
        return None, (jsonify({"error": firestore_unavailable_message()}), 503)
    return db, None


@schedule_bp.route("/", methods=["GET"])
@requires_auth
def list_events():
    db, err = _require_db()
    if err:
        return err
    items = [doc_to_dict(d) for d in db.collection(COL_OPS_EVENTS).stream()]
    return jsonify(items)


@schedule_bp.route("/", methods=["POST"])
@requires_auth
def create_event():
    db, err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    start_at = data.get("start_at") or data.get("start")
    if not title or not start_at:
        return jsonify({"error": "title and start_at required"}), 400
    kind = data.get("kind") or "manual"
    if kind not in EVENT_KINDS:
        kind = "manual"
    from firebase_admin import firestore as fs

    payload = {
        "title": title,
        "site_id": data.get("site_id") or "",
        "kind": kind,
        "start_at": start_at,
        "end_at": data.get("end_at") or data.get("end") or "",
        "all_day": bool(data.get("all_day")),
        "notes": data.get("notes") or "",
        "created_at": fs.SERVER_TIMESTAMP,
    }
    ref = db.collection(COL_OPS_EVENTS).add(payload)[1]
    return jsonify(doc_to_dict(ref.get())), 201


@schedule_bp.route("/<event_id>", methods=["PUT"])
@requires_auth
def update_event(event_id: str):
    db, err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    ref = db.collection(COL_OPS_EVENTS).document(event_id)
    if not ref.get().exists:
        return jsonify({"error": "not found"}), 404
    allowed = {"title", "site_id", "kind", "start_at", "end_at", "all_day", "notes"}
    patch = {k: data[k] for k in allowed if k in data}
    if "start" in data:
        patch["start_at"] = data["start"]
    if "end" in data:
        patch["end_at"] = data["end"]
    if patch:
        ref.update(patch)
    return jsonify(doc_to_dict(ref.get()))


@schedule_bp.route("/<event_id>", methods=["DELETE"])
@requires_auth
def delete_event(event_id: str):
    db, err = _require_db()
    if err:
        return err
    ref = db.collection(COL_OPS_EVENTS).document(event_id)
    if not ref.get().exists:
        return jsonify({"error": "not found"}), 404
    ref.delete()
    return jsonify({"ok": True})


def event_to_fullcalendar(doc: dict) -> dict:
    kind = doc.get("kind") or "manual"
    color = EVENT_COLORS.get(kind, "#888780")
    title = doc.get("title") or ""
    if doc.get("site_id"):
        title = f"{doc['site_id']} · {title}"
    fc = {
        "id": doc["id"],
        "title": title,
        "start": doc.get("start_at"),
        "backgroundColor": color,
        "borderColor": "transparent",
        "textColor": "#fff",
        "extendedProps": doc,
    }
    if doc.get("end_at"):
        fc["end"] = doc["end_at"]
    if doc.get("all_day"):
        fc["allDay"] = True
    return fc


@schedule_bp.route("/calendar")
@requires_auth
def calendar_feed():
    """Legacy URL — same feed as /api/calendar/events."""
    from calendar_service import all_calendar_events

    db, err = _require_db()
    if err:
        return err
    return jsonify(all_calendar_events(db))
