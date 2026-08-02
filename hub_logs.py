"""Read deploy / git activity logs for dashboard."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import LOG_DIR, OPS_ROOT, list_hub_services, repo_path, work_root_available
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
from pipeline_runner import mark_content_cycle_shipped


def _to_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0)


def _parse_ship_datetime(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        return _to_naive(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        return None


def _log_dirs() -> list[Path]:
    dirs = []
    for d in (LOG_DIR, OPS_ROOT / "logs", DEPLOY_LOG_DIR):
        if d.is_dir() and d not in dirs:
            dirs.append(d)
    return dirs


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _ship_candidates(
    *,
    pipeline_at: str | None,
    deploy_logs: list[dict[str, Any]],
    git_gs: dict[str, Any] | None,
) -> list[tuple[datetime, str]]:
    """Collect candidate ship times for the content 7-day clock."""
    out: list[tuple[datetime, str]] = []
    pat = _parse_ship_datetime(str(pipeline_at or ""))
    if pat:
        out.append((pat, "pipeline"))

    for dep in deploy_logs:
        if dep.get("state") != "success":
            continue
        raw = str(dep.get("mtime") or "").strip()
        if not raw:
            continue
        dt = _parse_ship_datetime(raw if len(raw) > 16 else f"{raw}:00")
        if dt:
            out.append((dt, "deploy"))
            break

    if git_gs and not git_gs.get("error"):
        dirty = bool(git_gs.get("dirty"))
        ahead = int(git_gs.get("ahead") or 0)
        # In sync with remote: treat latest commit as shipped (Paperclip ./deploy.sh --with-git).
        if not dirty and ahead == 0:
            raw = str(git_gs.get("last_commit_at") or "").strip()
            dt = _parse_ship_datetime(raw)
            if dt:
                out.append((dt, "git"))
    return out


def sync_content_cycle_from_activity(
    site_id: str,
    *,
    pipeline_at: str | None,
    deploy_logs: list[dict[str, Any]],
    git_gs: dict[str, Any] | None,
) -> str | None:
    """If deploy/git ship is newer than pipeline clock, bump content cycle. Returns best stamp."""
    # Only content-pipeline sites participate in the 7-day content clock.
    from content_pipeline import CONTENT_PIPELINES

    if site_id not in CONTENT_PIPELINES:
        return pipeline_at
    cands = _ship_candidates(
        pipeline_at=pipeline_at,
        deploy_logs=deploy_logs,
        git_gs=git_gs,
    )
    if not cands:
        return pipeline_at
    best_dt, best_via = max(cands, key=lambda x: x[0])
    if best_via != "pipeline":
        mark_content_cycle_shipped(site_id, via=best_via, at=best_dt)
    return best_dt.isoformat(sep=" ")


def _read_log_head(path: Path, *, max_chars: int = 2048) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except OSError:
        return ""


def classify_deploy_log_kind(*, head: str = "", tail: str = "", size: int = 0) -> str:
    """Classify a deploy-*.log as git push stub vs real Cloud Deploy.

    Returns ``git`` | ``deploy``.
    """
    head_s = head or ""
    via_m = re.search(r"(?m)^via:\s*(\S+)", head_s)
    if via_m:
        via = via_m.group(1).strip().lower()
        if via in ("git_push", "git", "push") or via.startswith("git_"):
            return "git"
        if via in ("deploy", "cloudbuild", "paperclip", "site_deploy", "cloud_deploy"):
            return "deploy"

    blob = f"{head_s}\n{tail or ''}".lower()
    if any(
        needle in blob
        for needle in (
            "cloud build",
            "gcloud builds",
            "cloudbuild",
            "starting build",
            "deploy.sh",
            "creating temporary archive",
        )
    ):
        return "deploy"

    # Tiny ship stubs without Cloud Build markers are almost always Git push notes.
    if size and size < 800 and ("ship" in blob or "via:" in blob):
        if "git" in blob or "push" in blob:
            return "git"

    return "deploy"


def deploy_logs_for_site(site_id: str, *, max_files: int = 20, tail_lines: int = 12) -> list[dict[str, Any]]:
    files: list[Path] = []
    for d in _log_dirs():
        files.extend(d.glob(f"deploy-{site_id}-*.log"))
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)[:max_files]
    out: list[dict[str, Any]] = []
    for p in files:
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        head = _read_log_head(p)
        tail = tail_deploy_log(p, lines=tail_lines)
        state = "unknown"
        if "ERROR:" in tail or "❌" in tail:
            state = "failed"
        elif "DONE" in tail or "완료" in tail:
            state = "success"
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        kind = classify_deploy_log_kind(head=head, tail=tail, size=size)
        out.append(
            {
                "file": p.name,
                "mtime": mtime,
                "state": state,
                "kind": kind,
                "tail": _strip_ansi(tail),
                "size": size,
            }
        )
    return out


def resolve_deploy_log(site_id: str, filename: str) -> Path | None:
    """Safe resolve of deploy-{site_id}-*.log under known log dirs."""
    name = (filename or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    if not re.fullmatch(rf"deploy-{re.escape(site_id)}-[A-Za-z0-9._-]+\.log", name):
        return None
    for d in _log_dirs():
        p = (d / name).resolve()
        try:
            if p.is_file() and p.parent.resolve() == d.resolve():
                return p
        except OSError:
            continue
    return None


def read_deploy_log(site_id: str, filename: str, *, max_chars: int = 400_000) -> dict[str, Any]:
    path = resolve_deploy_log(site_id, filename)
    if not path:
        return {"ok": False, "error": "log not found"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    truncated = False
    if len(text) > max_chars:
        text = text[-max_chars:]
        truncated = True
    mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    head = text[:2048] if not truncated else _read_log_head(path)
    kind = classify_deploy_log_kind(head=head, tail=text[-4000:], size=size)
    return {
        "ok": True,
        "file": path.name,
        "mtime": mtime,
        "kind": kind,
        "truncated": truncated,
        "text": _strip_ansi(text),
    }


def site_activity(site_id: str, svc: dict[str, Any]) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "git_commits": [],
        "deploy": [],
    }
    git_gs: dict[str, Any] | None = None
    if svc.get("git") and work_root_available():
        git_gs = git_summary(repo_path(svc)) or {}
        activity["git_commits"] = list(git_gs.get("recent_commits") or [])[:5]
        activity["git_branch"] = git_gs.get("branch")
        activity["git_dirty"] = git_gs.get("dirty")

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
    deploy_logs = deploy_logs_for_site(site_id)
    activity["deploy"] = deploy_logs

    content_at = sync_content_cycle_from_activity(
        site_id,
        pipeline_at=content_meta.get("last_run_at"),
        deploy_logs=deploy_logs,
        git_gs=git_gs,
    )
    # Re-read after possible bump so display matches schedule.
    if content_at and content_at != content_meta.get("last_run_at"):
        content_meta = pipeline_last_run(site_id)

    activity["last_content_added_at"] = content_meta.get("last_run_display")
    activity["last_content_added_ok"] = content_meta.get("last_run_ok")
    content_sched = work_due_schedule(
        content_meta.get("last_run_at") or content_at,
        interval_days=CONTENT_INTERVAL_DAYS,
    )
    activity["content_schedule"] = content_sched
    activity["content_due_label"] = format_due_label(content_sched)

    if work_root_available():
        from local_content_signal import local_content_deploy_signal

        activity["local_content"] = local_content_deploy_signal(
            site_id,
            repo_path(svc) if svc.get("git") else None,
            deploy_logs=deploy_logs,
            seo_finished_at=gsc_meta.get("last_seo_at"),
            seo_applied=gsc_meta.get("last_seo_applied"),
        )

    return activity


def dashboard_logs() -> dict[str, Any]:
    sites: dict[str, Any] = {}
    for svc in list_hub_services():
        sid = svc.get("id") or ""
        if sid == "okadmin":
            continue
        sites[sid] = site_activity(sid, svc)
    return {"sites": sites}
