"""Run site content generation scripts from Work Hub."""
from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

from auth import requires_auth
from config import CONTENT_JOBS, get_service, repo_path, work_root_available

content_bp = Blueprint("content", __name__, url_prefix="/api/content")

_running: dict[str, subprocess.Popen] = {}


@content_bp.route("/jobs")
@requires_auth
def list_jobs():
    sites = []
    for site_id, jobs in CONTENT_JOBS.items():
        svc = get_service(site_id)
        sites.append(
            {
                "site_id": site_id,
                "label": svc.get("label", site_id) if svc else site_id,
                "jobs": jobs,
                "available": bool(svc) and work_root_available(),
            }
        )
    return jsonify(sites)


@content_bp.route("/run", methods=["POST"])
@requires_auth
def run_job():
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT not available"}), 503
    data = request.get_json(silent=True) or {}
    site_id = (data.get("site_id") or "").strip()
    job_id = (data.get("job_id") or "").strip()
    svc = get_service(site_id)
    if not svc:
        return jsonify({"error": "unknown site"}), 404
    jobs = CONTENT_JOBS.get(site_id) or []
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    cwd = repo_path(svc)
    if not cwd.is_dir():
        return jsonify({"error": f"missing {cwd}"}), 503

    key = f"{site_id}:{job_id}"
    if key in _running and _running[key].poll() is None:
        return jsonify({"error": "already running", "key": key}), 409

    log_dir = Path(__file__).resolve().parents[1] / "data" / "content_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{site_id}_{job_id}.log"

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n--- run {job_id} ---\n")
        proc = subprocess.Popen(
            job["command"],
            shell=True,
            cwd=str(cwd),
            stdout=logf,
            stderr=subprocess.STDOUT,
            text=True,
        )
    _running[key] = proc
    return jsonify(
        {
            "ok": True,
            "pid": proc.pid,
            "site_id": site_id,
            "job_id": job_id,
            "command": job["command"],
            "cwd": str(cwd),
            "log_path": str(log_path),
        }
    )


@content_bp.route("/log")
@requires_auth
def job_log():
    site_id = request.args.get("site_id", "")
    job_id = request.args.get("job_id", "")
    log_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "content_logs"
        / f"{site_id}_{job_id}.log"
    )
    if not log_path.is_file():
        return jsonify({"text": ""})
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return jsonify({"text": text[-12000:]})


@content_bp.route("/status")
@requires_auth
def job_status():
    out = {}
    for key, proc in list(_running.items()):
        out[key] = {"pid": proc.pid, "running": proc.poll() is None}
    return jsonify(out)
