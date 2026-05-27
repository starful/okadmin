"""TODO API (Firestore)."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import requires_auth
from config import COL_TODOS
from firestore_db import doc_to_dict, firestore_unavailable_message, get_db

todos_bp = Blueprint("todos", __name__, url_prefix="/api/todos")


def _require_db():
    db = get_db()
    if db is None:
        return None, (jsonify({"error": firestore_unavailable_message()}), 503)
    return db, None


@todos_bp.route("/", methods=["GET"])
@requires_auth
def list_todos():
    db, err = _require_db()
    if err:
        return err
    status = request.args.get("status")
    site_id = request.args.get("site_id")
    items = [doc_to_dict(d) for d in db.collection(COL_TODOS).stream()]
    if site_id:
        items = [i for i in items if i.get("site_id") == site_id]
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return jsonify(items)


@todos_bp.route("/", methods=["POST"])
@requires_auth
def create_todo():
    db, err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    from firebase_admin import firestore as fs

    payload = {
        "title": title,
        "body": data.get("body") or "",
        "site_id": data.get("site_id") or "",
        "status": data.get("status") or "open",
        "priority": data.get("priority") or "normal",
        "due_at": data.get("due_at") or "",
        "created_at": fs.SERVER_TIMESTAMP,
    }
    ref = db.collection(COL_TODOS).add(payload)[1]
    doc = ref.get()
    return jsonify(doc_to_dict(doc)), 201


@todos_bp.route("/<todo_id>", methods=["PUT"])
@requires_auth
def update_todo(todo_id: str):
    db, err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    ref = db.collection(COL_TODOS).document(todo_id)
    if not ref.get().exists:
        return jsonify({"error": "not found"}), 404
    allowed = {"title", "body", "site_id", "status", "priority", "due_at"}
    patch = {k: data[k] for k in allowed if k in data}
    if patch:
        from firebase_admin import firestore as fs

        if patch.get("status") == "done":
            patch["completed_at"] = fs.SERVER_TIMESTAMP
        ref.update(patch)
    return jsonify(doc_to_dict(ref.get()))


@todos_bp.route("/<todo_id>", methods=["DELETE"])
@requires_auth
def delete_todo(todo_id: str):
    db, err = _require_db()
    if err:
        return err
    ref = db.collection(COL_TODOS).document(todo_id)
    if not ref.get().exists:
        return jsonify({"error": "not found"}), 404
    ref.delete()
    return jsonify({"ok": True})
