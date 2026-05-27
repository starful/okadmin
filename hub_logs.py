"""Read ops / deploy / git activity logs for dashboard."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import LOG_DIR, OPS_ROOT, STATE_FILE, list_services, repo_path, work_root_available
from git_ops import DEPLOY_LOG_DIR, tail_deploy_log
from git_util import git_summary

# auto-register 로그에서 사이트 매칭용 (hatena → okpy.net 운영)
SITE_LOG_ALIASES: dict[str, list[str]] = {
    "hatena": ["hatena", "okpy"],
    "starful.biz": ["starful.biz", "starful_biz", "starful.biz"],
}


def _log_dirs() -> list[Path]:
    dirs = []
    for d in (LOG_DIR, OPS_ROOT / "logs", DEPLOY_LOG_DIR):
        if d.is_dir() and d not in dirs:
            dirs.append(d)
    return dirs


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _tail_file(path: Path, *, lines: int = 25) -> str:
    if not path.is_file():
        return ""
    try:
        rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(_strip_ansi(line) for line in rows[-lines:])


def latest_auto_register_log_path() -> Path | None:
    found: list[Path] = []
    for d in _log_dirs():
        found.extend(d.glob("auto-register-*.log"))
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


def global_ops_log(*, tail_lines: int = 28) -> dict[str, Any]:
    last_run = ""
    if STATE_FILE.is_file():
        last_run = STATE_FILE.read_text(encoding="utf-8").strip()
    latest = latest_auto_register_log_path()
    return {
        "last_run": last_run,
        "log_file": latest.name if latest else "",
        "log_tail": _tail_file(latest, lines=tail_lines) if latest else "",
    }


def _site_match_tokens(site_id: str) -> list[str]:
    tokens = list(SITE_LOG_ALIASES.get(site_id, [site_id]))
    if site_id not in tokens:
        tokens.insert(0, site_id)
    return tokens


def _grep_auto_register_for_site(site_id: str, *, max_lines: int = 12) -> list[str]:
    tokens = _site_match_tokens(site_id)
    latest = latest_auto_register_log_path()
    if not latest:
        return []
    try:
        text = latest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[str] = []
    for line in text.splitlines():
        plain = _strip_ansi(line).strip()
        if not plain:
            continue
        low = plain.lower()
        if any(t.lower() in low for t in tokens):
            hits.append(plain[:200])
    return hits[-max_lines:]


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
        "auto_register": [],
        "deploy": [],
    }
    if svc.get("git") and work_root_available():
        gs = git_summary(repo_path(svc)) or {}
        activity["git_commits"] = list(gs.get("recent_commits") or [])[:5]
        activity["git_branch"] = gs.get("branch")
        activity["git_dirty"] = gs.get("dirty")
    activity["auto_register"] = _grep_auto_register_for_site(site_id)
    activity["deploy"] = deploy_logs_for_site(site_id)
    return activity


def dashboard_logs() -> dict[str, Any]:
    global_log = global_ops_log()
    sites: dict[str, Any] = {}
    for svc in list_services():
        sid = svc.get("id") or ""
        if sid == "okadmin":
            continue
        sites[sid] = site_activity(sid, svc)
    return {"global": global_log, "sites": sites}
