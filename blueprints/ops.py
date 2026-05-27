"""Auto register ops panel API."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from auth import requires_auth
from config import (
    auto_register_project_ids,
    AUTO_REGISTER_SCHEDULE,
    AUTO_REGISTER_SCRIPT,
    AUTO_REGISTER_STATUS_SCRIPT,
    COL_META,
    LOG_DIR,
    META_DOC_ID,
    STATE_FILE,
    WORK_ROOT,
    auto_register_projects,
    work_root_available,
)
from firestore_db import firestore_unavailable_message, get_db

ops_bp = Blueprint("ops", __name__, url_prefix="/api/ops")


def _tail_log(n: int = 25) -> str:
    if not LOG_DIR.is_dir():
        return ""
    logs = sorted(LOG_DIR.glob("auto-register-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return ""
    text = logs[0].read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return "\n".join(lines[-n:])


@ops_bp.route("/auto-register/status")
@requires_auth
def auto_register_status():
    last_run = ""
    if STATE_FILE.is_file():
        last_run = STATE_FILE.read_text(encoding="utf-8").strip()

    meta_last = None
    db = get_db()
    if db:
        try:
            doc = db.collection(COL_META).document(META_DOC_ID).get()
            if doc.exists:
                meta_last = (doc.to_dict() or {}).get("auto_register_last_run")
        except Exception:
            pass

    launchctl_snippet = ""
    if AUTO_REGISTER_STATUS_SCRIPT.is_file() and work_root_available():
        try:
            proc = subprocess.run(
                ["bash", str(AUTO_REGISTER_STATUS_SCRIPT)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            launchctl_snippet = proc.stdout[-4000:] if proc.stdout else proc.stderr or ""
        except Exception as e:
            launchctl_snippet = f"(status script error: {e})"

    return jsonify(
        {
            "work_root_ok": work_root_available(),
            "last_run_file": last_run,
            "last_run_meta": meta_last,
            "schedule": [{"day": d, "project": p} for d, p in AUTO_REGISTER_SCHEDULE],
            "projects": auto_register_projects(),
            "log_tail": _tail_log(),
            "launchctl_snippet": launchctl_snippet,
            "script_path": str(AUTO_REGISTER_SCRIPT),
        }
    )


@ops_bp.route("/auto-register/run", methods=["POST"])
@requires_auth
def auto_register_run():
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT / ops not available on this host"}), 503
    if not AUTO_REGISTER_SCRIPT.is_file():
        return jsonify({"error": f"missing {AUTO_REGISTER_SCRIPT}"}), 503

    data = request.get_json(silent=True) or {}
    force = bool(data.get("force"))
    project = (data.get("project") or data.get("site_id") or "").strip()
    allowed = auto_register_project_ids()
    if project and project not in allowed:
        return jsonify(
            {
                "error": f"unknown project: {project}",
                "allowed": allowed,
            }
        ), 400
    if project and not re.match(r"^[a-zA-Z0-9._-]+$", project):
        return jsonify({"error": "invalid project id"}), 400
    if project and not (WORK_ROOT / project).is_dir():
        return jsonify({"error": f"no directory: {WORK_ROOT / project}"}), 400

    cmd = ["bash", str(AUTO_REGISTER_SCRIPT)]
    if force:
        cmd.append("--force")
    if project:
        cmd.extend(["--project", project])

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(WORK_ROOT),
        )
        # Run in background for long deploys
        msg = "auto_register started"
        if project:
            msg = f"auto_register started for {project}"
        return jsonify(
            {
                "ok": True,
                "message": msg,
                "pid": proc.pid,
                "project": project or None,
                "command": cmd,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ops_bp.route("/auto-register/meta", methods=["POST"])
@requires_auth
def auto_register_meta():
    """Optional: sync last-run to Firestore for shared visibility."""
    db = get_db()
    if db is None:
        return jsonify({"error": firestore_unavailable_message()}), 503
    from firebase_admin import firestore as fs

    today = datetime.now().strftime("%Y-%m-%d")
    db.collection(COL_META).document(META_DOC_ID).set(
        {"auto_register_last_run": today, "updated_at": fs.SERVER_TIMESTAMP},
        merge=True,
    )
    return jsonify({"ok": True, "auto_register_last_run": today})
