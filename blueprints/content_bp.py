"""Run site content generation scripts from Work Hub."""
from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

from auth import requires_auth
from config import CONTENT_JOBS, get_service, repo_path, work_root_available
from git_ops import deploy_job_status
from content_csv import list_csv_files, load_csv, save_csv
from content_pipeline import (
    CONTENT_PIPELINES,
    _log_snippet,
    pipeline_last_run,
    pipeline_log_path,
    pipeline_run_caps,
    read_pipeline_status,
    run_csv_expand,
    run_pipeline,
    run_post_pipeline_deploy,
    summarize_pipeline_status,
    tail_pipeline_log,
    write_pipeline_status,
)
from pipeline_backlog import read_backlog_snapshot, refresh_backlog_snapshot, refresh_all_backlog_snapshots
from firestore_db import get_db
from ops_calendar import record_ops_calendar_event

content_bp = Blueprint("content", __name__, url_prefix="/api/content")

_running: dict[str, subprocess.Popen] = {}
_pipeline_running: dict[str, bool] = {}
_pipeline_phase: dict[str, str] = {}  # generate | deploy
_pipeline_deploy_job: dict[str, str] = {}  # site_id -> deploy job_id


def _pipeline_calendar_notes(result: dict) -> str:
    parts: list[str] = []
    if result.get("error"):
        parts.append(f"error: {str(result['error'])[:400]}")
    for step in result.get("steps") or []:
        name = step.get("label") or step.get("step") or "?"
        mark = "ok" if step.get("ok") else "fail"
        parts.append(f"{name}: {mark}")
    deploy = result.get("deploy") or {}
    if deploy.get("skipped"):
        parts.append("deploy: skip")
    elif deploy:
        msg = deploy.get("message") or deploy.get("state") or deploy.get("error") or ""
        parts.append(f"deploy: {msg}"[:200])
    return "\n".join(parts)[:2000]


def _record_pipeline_calendar(site_id: str, result: dict) -> dict | None:
    svc = get_service(site_id)
    label = (svc or {}).get("label", site_id)
    ok = bool(result.get("ok"))
    title = f"콘텐츠 · {label}" if ok else f"콘텐츠 실패 · {label}"
    if ok:
        title = f"✓ {title}"
    return record_ops_calendar_event(
        site_id=site_id,
        kind="content",
        title=title,
        notes=_pipeline_calendar_notes(result),
    )


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
        backlog = read_backlog_snapshot(site_id)
        items.append(
            {
                "site_id": site_id,
                "label": meta.get("label", site_id),
                "description": meta.get("description", ""),
                "limits": caps.get("parts", []),
                "limits_summary": caps.get("summary", ""),
                "backlog": backlog,
                "available": bool(svc) and work_root_available(),
                "running": _pipeline_running.get(site_id, False),
                "phase": _pipeline_phase.get(site_id) if _pipeline_running.get(site_id) else None,
                "last_ok": last_meta.get("last_run_ok"),
                "last_run_at": last_meta.get("last_run_at"),
                "last_run_display": last_meta.get("last_run_display"),
            }
        )
    return jsonify(items)


@content_bp.route("/ai-spend")
@requires_auth
def ai_spend_summary():
    from ai_spend import spend_summary

    return jsonify(spend_summary())


@content_bp.route("/pipeline/backlog/refresh", methods=["POST"])
@requires_auth
def pipeline_backlog_refresh():
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT not available"}), 503
    data = request.get_json(silent=True) or {}
    only = (data.get("site_id") or "").strip()
    if only:
        if only not in CONTENT_PIPELINES:
            return jsonify({"error": "unknown pipeline"}), 400
        result = refresh_backlog_snapshot(only)
        return jsonify(result)
    return jsonify(refresh_all_backlog_snapshots())


@content_bp.route("/pipeline/csv-expand", methods=["POST"])
@requires_auth
def pipeline_csv_expand():
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT not available"}), 503
    data = request.get_json(silent=True) or {}
    site_id = (data.get("site_id") or "").strip()
    if site_id not in CONTENT_PIPELINES:
        return jsonify({"error": "unknown pipeline"}), 400
    if _pipeline_running.get(site_id):
        return jsonify({"error": "pipeline already running"}), 409
    insight_count = data.get("insight_count")
    guide_count = data.get("guide_count")
    school_count = data.get("school_count")
    university_count = data.get("university_count")
    expand = run_csv_expand(
        site_id,
        insight_count=insight_count,
        guide_count=guide_count,
        school_count=school_count,
        university_count=university_count,
    )
    if not expand.get("ok"):
        return jsonify(expand), 400
    backlog = refresh_backlog_snapshot(site_id)
    expand["backlog"] = backlog
    return jsonify(expand)


def _optional_nonneg_int(data: dict, key: str) -> int | None:
    if key not in data:
        return None
    try:
        return max(0, int(data[key]))
    except (TypeError, ValueError):
        return None


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

    insight_count = _optional_nonneg_int(data, "insight_count")
    guide_count = _optional_nonneg_int(data, "guide_count")
    school_count = _optional_nonneg_int(data, "school_count")
    university_count = _optional_nonneg_int(data, "university_count")

    def worker():
        _pipeline_running[site_id] = True
        _pipeline_phase[site_id] = "generate"
        try:
            result = run_pipeline(
                site_id,
                insight_count=insight_count,
                guide_count=guide_count,
                school_count=school_count,
                university_count=university_count,
            )
            if result.get("ok"):
                _pipeline_phase[site_id] = "deploy"

                def _on_deploy_started(job_id: str, _info: dict) -> None:
                    _pipeline_deploy_job[site_id] = job_id

                deploy = run_post_pipeline_deploy(site_id, on_job_started=_on_deploy_started)
                result["deploy"] = deploy
                deploy_ok = deploy.get("skipped") or deploy.get("state") == "success"
                if not deploy_ok:
                    result["ok"] = False
                    result["error"] = deploy.get("error") or deploy.get("message") or "deploy failed"
            result["calendar_event"] = _record_pipeline_calendar(site_id, result)
            write_pipeline_status(site_id, result)
            try:
                refresh_backlog_snapshot(site_id)
            except Exception:
                pass
        except Exception as exc:
            fail = {"ok": False, "error": str(exc), "site_id": site_id}
            fail["calendar_event"] = _record_pipeline_calendar(site_id, fail)
            write_pipeline_status(site_id, fail)
        finally:
            _pipeline_running[site_id] = False
            _pipeline_phase.pop(site_id, None)
            _pipeline_deploy_job.pop(site_id, None)

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


@content_bp.route("/pipeline/backfill-calendar", methods=["POST"])
@requires_auth
def pipeline_backfill_calendar():
    """Record today's finished pipeline runs on the work calendar (one-off catch-up)."""
    from datetime import date

    today = date.today().isoformat()
    data = request.get_json(silent=True) or {}
    only = (data.get("site_id") or "").strip()
    sites = [only] if only else list(CONTENT_PIPELINES.keys())
    recorded: list[str] = []
    skipped: list[str] = []

    for site_id in sites:
        if site_id not in CONTENT_PIPELINES:
            skipped.append(site_id)
            continue
        status = read_pipeline_status(site_id)
        if not status:
            skipped.append(site_id)
            continue
        finished = str(status.get("finished_at") or status.get("last_run_at") or "")[:10]
        if finished != today:
            skipped.append(site_id)
            continue
        ev = _record_pipeline_calendar(site_id, status)
        if ev:
            recorded.append(site_id)

    return jsonify(
        {
            "ok": True,
            "date": today,
            "recorded": recorded,
            "skipped": skipped,
            "calendar_skipped": not recorded and get_db() is None,
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
    phase = _pipeline_phase.get(site_id, "generate") if running else None
    deploy_live: dict = {}
    job_id = _pipeline_deploy_job.get(site_id, "")
    if running and phase == "deploy" and job_id:
        deploy_live = deploy_job_status(job_id, site_id=site_id)

    if running:
        if phase == "deploy":
            deploy_msg = deploy_live.get("message") or "git push · Cloud Build"
            deploy_state = deploy_live.get("state") or "running"
            lines = [
                "② 배포 단계 (deploy.sh)",
                f"   상태: {deploy_msg}",
                f"   PID: {deploy_live.get('pid') or '—'}",
            ]
            if deploy_live.get("log_path"):
                lines.append(f"   로그: {deploy_live['log_path']}")
            title = "배포 중" if deploy_state == "running" else "실행 중"
            log_snippet = (deploy_live.get("log_tail") or "").strip() or _log_snippet(
                text[-12000:] if text else ""
            )
        else:
            title = "생성 중"
            lines = [
                "① 콘텐츠 생성 · build_data",
                "   (완료 후 ② 배포가 자동으로 시작됩니다)",
            ]
            log_snippet = _log_snippet(text[-12000:] if text else "")
        summary = {
            "title": title,
            "ok": None,
            "lines": lines,
            "log_snippet": log_snippet,
        }
    else:
        summary = summarize_pipeline_status(status, text)

    last_meta = pipeline_last_run(site_id)
    return jsonify(
        {
            "running": running,
            "phase": phase,
            "deploy": deploy_live if deploy_live else status.get("deploy"),
            "deploy_job_id": job_id or None,
            "ok": status.get("ok") if not running else None,
            "error": status.get("error") or status.get("failed_step"),
            "steps": status.get("steps"),
            "message": status.get("message"),
            "summary": summary,
            "log_tail": text[-6000:] if text else "",
            "deploy_log_tail": (deploy_live.get("log_tail") or "") if deploy_live else "",
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
