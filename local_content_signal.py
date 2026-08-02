"""Detect gitignored local content that needs Cloud Deploy (not Git ship).

Sites like krcare / okpy keep app/content/ out of git; SEO and pipelines still
write MD there. Hub Deploy uploads the local tree via Cloud Build, so we surface
"needs deploy" when content (or a successful SEO apply) is newer than the last
Cloud Deploy log.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

CONTENT_REL = "app/content"
_SCAN_CAP = 5000


def _parse_stamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def content_dir(repo_path: Path) -> Path:
    return Path(repo_path) / CONTENT_REL


def is_content_gitignored(repo_path: Path) -> bool:
    """True when app/content is ignored by git (directory or a path under it)."""
    root = Path(repo_path)
    if not root.is_dir():
        return False
    rel = CONTENT_REL
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", rel],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode == 0:
        return True
    # Directory may not exist yet — probe a placeholder path under it
    try:
        proc2 = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", f"{rel}/.hub_probe"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc2.returncode == 0


def newest_content_mtime(repo_path: Path) -> float | None:
    """Newest mtime under app/content (files only). None if empty/missing."""
    root = content_dir(repo_path)
    if not root.is_dir():
        return None
    newest: float | None = None
    n = 0
    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            n += 1
            if n > _SCAN_CAP:
                break
            try:
                mt = path.stat().st_mtime
            except OSError:
                continue
            if newest is None or mt > newest:
                newest = mt
    except OSError:
        return newest
    return newest


def last_cloud_deploy_at(deploy_logs: list[dict[str, Any]] | None) -> datetime | None:
    """Latest successful-looking Cloud Deploy stamp (excludes git ship stubs)."""
    best: datetime | None = None
    for row in deploy_logs or []:
        if (row.get("kind") or "deploy") != "deploy":
            continue
        # Prefer success; still count unknown/running finished stamps as "happened"
        state = row.get("state") or ""
        if state == "failed":
            continue
        dt = _parse_stamp(row.get("mtime"))
        if dt and (best is None or dt > best):
            best = dt
    return best


def local_content_deploy_signal(
    site_id: str,
    repo_path: Path | None,
    *,
    deploy_logs: list[dict[str, Any]] | None = None,
    seo_finished_at: str | None = None,
    seo_applied: int | None = None,
) -> dict[str, Any]:
    """Hub payload: whether ignored local content is ahead of last Cloud Deploy."""
    out: dict[str, Any] = {
        "site_id": site_id,
        "content_gitignored": False,
        "needs_deploy": False,
        "reason": None,
        "content_mtime": None,
        "content_mtime_display": None,
        "last_deploy_at": None,
        "last_deploy_display": None,
        "seo_applied": seo_applied,
        "seo_finished_at": seo_finished_at,
        "hint": None,
    }
    if not repo_path or not Path(repo_path).is_dir():
        return out

    ignored = is_content_gitignored(repo_path)
    out["content_gitignored"] = ignored
    if not ignored:
        return out

    out["hint"] = (
        "app/content/는 Git에 안 잡힙니다. MD·SEO 변경은 Deploy로 라이브 반영하세요."
    )

    content_mt = newest_content_mtime(repo_path)
    content_dt = datetime.fromtimestamp(content_mt) if content_mt else None
    if content_dt:
        out["content_mtime"] = content_dt.replace(microsecond=0).isoformat(sep=" ")
        out["content_mtime_display"] = content_dt.strftime("%Y-%m-%d %H:%M")

    deploy_dt = last_cloud_deploy_at(deploy_logs)
    if deploy_dt:
        out["last_deploy_at"] = deploy_dt.replace(microsecond=0).isoformat(sep=" ")
        out["last_deploy_display"] = deploy_dt.strftime("%Y-%m-%d %H:%M")

    seo_dt = _parse_stamp(seo_finished_at) if (seo_applied or 0) > 0 else None

    # Newest signal among content files and successful SEO apply
    change_dt = content_dt
    if seo_dt and (change_dt is None or seo_dt > change_dt):
        change_dt = seo_dt
    if change_dt is None:
        return out

    if deploy_dt is None or change_dt > deploy_dt:
        out["needs_deploy"] = True
        # Prefer SEO wording when a successful apply is still ahead of deploy
        if (seo_applied or 0) > 0 and seo_dt and (deploy_dt is None or seo_dt > deploy_dt):
            out["reason"] = f"SEO {seo_applied}건 반영 · Git에 안 보임 · Deploy 필요"
        else:
            out["reason"] = "로컬 content가 최근 배포보다 최신 · Deploy 필요"
    return out


def attach_seo_deploy_hint(site_id: str, repo_path: Path | None, result: dict[str, Any]) -> dict[str, Any]:
    """Annotate SEO run JSON for the GSC UI."""
    results = result.get("results") or []
    applied = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "applied")
    ignored = bool(repo_path and is_content_gitignored(repo_path))
    result["content_gitignored"] = ignored
    result["seo_applied_count"] = applied
    if ignored and applied > 0:
        result["deploy_hint"] = (
            "Git에는 안 보입니다. Deploy 탭에서 Deploy하면 로컬 content가 라이브에 반영됩니다."
        )
        result["needs_local_content_deploy"] = True
    else:
        result["needs_local_content_deploy"] = False
        if ignored:
            result["deploy_hint"] = (
                "이 사이트 content는 Git ignore입니다. MD 변경 시 Deploy로 반영하세요."
            )
        else:
            result["deploy_hint"] = None
    return result
