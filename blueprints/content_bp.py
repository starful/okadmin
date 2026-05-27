"""Run site content generation scripts from Work Hub."""
from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

from auth import requires_auth
from config import CONTENT_JOBS, get_service, repo_path, work_root_available
from content_csv import list_csv_files, load_csv, save_csv
from content_pipeline import (
    CONTENT_PIPELINES,
    _log_snippet,
    pipeline_last_run,
    pipeline_log_path,
    pipeline_run_caps,
    read_pipeline_status,
    run_pipeline,
    summarize_pipeline_status,
    tail_pipeline_log,
    write_pipeline_status,
)

content_bp = Blueprint("content", __name__, url_prefix="/api/content")

_running: dict[str, subprocess.Popen] = {}
_pipeline_running: dict[str, bool] = {}


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


@content_bp.route("/pipelines")
@requires_auth
def list_pipelines():
    items = []
    for site_id, meta in CONTENT_PIPELINES.items():
        svc = get_service(site_id)
        caps = pipeline_run_caps(site_id)
        last_meta = pipeline_last_run(site_id)
        items.append(
            {
                "site_id": site_id,
                "label": meta.get("label", site_id),
                "description": meta.get("description", ""),
                "limits": caps.get("parts", []),
                "limits_summary": caps.get("summary", ""),
                "available": bool(svc) and work_root_available(),
                "running": _pipeline_running.get(site_id, False),
                "last_ok": last_meta.get("last_run_ok"),
                "last_run_at": last_meta.get("last_run_at"),
                "last_run_display": last_meta.get("last_run_display"),
            }
        )
    return jsonify(items)


@content_bp.route("/pipeline/run", methods=["POST"])
@requires_auth
def pipeline_run():
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT not available"}), 503
    data = request.get_json(silent=True) or {}
    site_id = (data.get("site_id") or "").strip()
    if site_id not in CONTENT_PIPELINES:
        return jsonify({"error": "unknown pipeline"}), 400
    if _pipeline_running.get(site_id):
        return jsonify({"error": "already running"}), 409

    import threading

    def worker():
        _pipeline_running[site_id] = True
        try:
            result = run_pipeline(site_id)
            write_pipeline_status(site_id, result)
        except Exception as exc:
            write_pipeline_status(
                site_id,
                {"ok": False, "error": str(exc), "site_id": site_id},
            )
        finally:
            _pipeline_running[site_id] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify(
        {
            "ok": True,
            "started": True,
            "site_id": site_id,
            "log_path": str(pipeline_log_path(site_id)),
            "message": "파이프라인 시작 (로그에서 진행 상황 확인)",
        }
    )


@content_bp.route("/pipeline/log")
@requires_auth
def pipeline_log():
    site_id = (request.args.get("site_id") or "").strip()
    if not site_id:
        return jsonify({"error": "site_id required"}), 400
    return jsonify(
        {
            "text": tail_pipeline_log(site_id),
            "running": _pipeline_running.get(site_id, False),
        }
    )


@content_bp.route("/pipeline/result")
@requires_auth
def pipeline_result():
    site_id = (request.args.get("site_id") or "").strip()
    status = read_pipeline_status(site_id) or {}
    text = tail_pipeline_log(site_id)
    running = _pipeline_running.get(site_id, False)
    if running:
        summary = {
            "title": "실행 중",
            "ok": None,
            "lines": ["생성 스크립트 실행 중…"],
            "log_snippet": _log_snippet(text[-12000:] if text else ""),
        }
    else:
        summary = summarize_pipeline_status(status, text)
    last_meta = pipeline_last_run(site_id)
    return jsonify(
        {
            "running": running,
            "ok": status.get("ok") if not running else None,
            "error": status.get("error") or status.get("failed_step"),
            "steps": status.get("steps"),
            "message": status.get("message"),
            "summary": summary,
            "log_tail": text[-6000:] if text else "",
            "last_run_at": last_meta.get("last_run_at"),
            "last_run_display": last_meta.get("last_run_display"),
            "last_run_ok": last_meta.get("last_run_ok"),
        }
    )


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


@content_bp.route("/csv/files")
@requires_auth
def csv_files():
    return jsonify(list_csv_files())


@content_bp.route("/csv/data")
@requires_auth
def csv_data():
    site_id = (request.args.get("site_id") or "").strip()
    file_id = (request.args.get("file_id") or "").strip()
    if not site_id or not file_id:
        return jsonify({"error": "site_id and file_id required"}), 400
    data = load_csv(site_id, file_id)
    if data.get("error"):
        return jsonify(data), 404
    return jsonify(data)


@content_bp.route("/csv/data", methods=["PUT"])
@requires_auth
def csv_data_save():
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT not available"}), 503
    body = request.get_json(silent=True) or {}
    site_id = (body.get("site_id") or "").strip()
    file_id = (body.get("file_id") or "").strip()
    rows = body.get("rows")
    if not site_id or not file_id:
        return jsonify({"error": "site_id and file_id required"}), 400
    if not isinstance(rows, list):
        return jsonify({"error": "rows must be a list"}), 400
    headers = body.get("headers")
    if headers is not None and not isinstance(headers, list):
        return jsonify({"error": "headers must be a list"}), 400
    result = save_csv(site_id, file_id, rows, headers=headers)
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)
