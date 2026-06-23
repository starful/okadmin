"""Read deploy / git activity logs for dashboard."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import LOG_DIR, OPS_ROOT, list_services, repo_path, work_root_available
from content_pipeline import pipeline_last_run
from dashboard_schedule import (
    CONTENT_INTERVAL_DAYS,
    GSC_INTERVAL_DAYS,
    format_due_label,
    work_due_schedule,
)
from gsc_run_store import gsc_last_runs
from git_ops import DEPLOY_LOG_DIR, tail_deploy_log
from git_util import git_summary


def _log_dirs() -> list[Path]:
    dirs = []
    for d in (LOG_DIR, OPS_ROOT / "logs", DEPLOY_LOG_DIR):
        if d.is_dir() and d not in dirs:
            dirs.append(d)
    return dirs


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def deploy_logs_for_site(site_id: str, *, max_files: int = 2, tail_lines: int = 10) -> list[dict[str, Any]]:
    files: list[Path] = []
    for d in _log_dirs():
        files.extend(d.glob(f"deploy-{site_id}-*.log"))
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)[:max_files]
    out: list[dict[str, Any]] = []
    for p in files:
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        tail = tail_deploy_log(p, lines=tail_lines)
        state = "unknown"
        if "ERROR:" in tail or "❌" in tail:
            state = "failed"
        elif "DONE" in tail or "완료" in tail:
            state = "success"
        out.append({"file": p.name, "mtime": mtime, "state": state, "tail": _strip_ansi(tail)})
    return out


def site_activity(site_id: str, svc: dict[str, Any]) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "git_commits": [],
        "deploy": [],
    }
    if svc.get("git") and work_root_available():
        gs = git_summary(repo_path(svc)) or {}
        activity["git_commits"] = list(gs.get("recent_commits") or [])[:5]
        activity["git_branch"] = gs.get("branch")
        activity["git_dirty"] = gs.get("dirty")

    gsc_meta = gsc_last_runs(site_id)
    gsc_last_at = gsc_meta.get("last_seo_at") or gsc_meta.get("last_run_at")
    activity["last_gsc_response_at"] = (
        gsc_meta.get("last_seo_display") or gsc_meta.get("last_run_display")
    )
    activity["last_gsc_response_ok"] = (
        gsc_meta.get("last_seo_ok")
        if gsc_meta.get("last_seo_display")
        else gsc_meta.get("last_run_ok")
    )
    gsc_sched = work_due_schedule(gsc_last_at, interval_days=GSC_INTERVAL_DAYS)
    activity["gsc_schedule"] = gsc_sched
    activity["gsc_due_label"] = format_due_label(gsc_sched)

    content_meta = pipeline_last_run(site_id)
    activity["last_content_added_at"] = content_meta.get("last_run_display")
    activity["last_content_added_ok"] = content_meta.get("last_run_ok")
    content_sched = work_due_schedule(
        content_meta.get("last_run_at"),
        interval_days=CONTENT_INTERVAL_DAYS,
    )
    activity["content_schedule"] = content_sched
    activity["content_due_label"] = format_due_label(content_sched)

    activity["deploy"] = deploy_logs_for_site(site_id)
    return activity


def dashboard_logs() -> dict[str, Any]:
    sites: dict[str, Any] = {}
    for svc in list_services():
        sid = svc.get("id") or ""
        if sid == "okadmin":
            continue
        sites[sid] = site_activity(sid, svc)
    return {"sites": sites}
