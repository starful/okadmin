"""Git push and deploy.sh helpers for Work Hub dashboard."""
from __future__ import annotations

import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from config import LOG_DIR, OKADMIN_ROOT

GIT_TIMEOUT = 120
DEPLOY_LOG_DIR = LOG_DIR if LOG_DIR.is_dir() else OKADMIN_ROOT / "logs"

# job_id -> {proc, log_path, site_id, started_at}
_DEPLOY_JOBS: dict[str, dict[str, Any]] = {}

SITEMAP_BUILD_COMMANDS: dict[str, list[str]] = {
    "krcampus": ["python3", "scripts/build_data.py"],
    "jpcampus": ["python3", "scripts/build_data.py"],
    "okramen": ["python3", "script/build_data.py"],
    "okonsen": ["python3", "script/build_data.py"],
    "okcaddie": ["python3", "script/build_data.py"],
    "okstats": ["python3", "script/build_data.py"],
    "starful.biz": ["python3", "scripts/build_data.py"],
}


def _run_git(repo_path: Path, args: list[str], *, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def git_current_branch(repo_path: Path) -> str:
    proc = _run_git(repo_path, ["branch", "--show-current"], timeout=15)
    if proc.returncode != 0:
        return "main"
    return (proc.stdout or "").strip() or "main"


def git_push_repo(
    repo_path: Path,
    *,
    site_id: str,
    message: str | None = None,
) -> dict:
    if not (repo_path / ".git").is_dir():
        return {"ok": False, "status": "failed", "error": "no git repository"}

    branch = git_current_branch(repo_path)
    msg = (message or "").strip() or (
        f"chore: hub push {site_id} {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    add_proc = _run_git(repo_path, ["add", "-A"])
    if add_proc.returncode != 0:
        return {
            "ok": False,
            "status": "failed",
            "error": add_proc.stderr.strip() or add_proc.stdout.strip() or "git add failed",
        }

    diff_proc = _run_git(repo_path, ["diff", "--cached", "--quiet"])
    committed = False
    commit_hash = ""
    if diff_proc.returncode == 1:
        commit_proc = _run_git(repo_path, ["commit", "-m", msg])
        if commit_proc.returncode != 0:
            return {
                "ok": False,
                "status": "failed",
                "error": commit_proc.stderr.strip()
                or commit_proc.stdout.strip()
                or "git commit failed",
            }
        committed = True
        head = _run_git(repo_path, ["rev-parse", "--short", "HEAD"], timeout=15)
        commit_hash = (head.stdout or "").strip()

    push_proc = _run_git(
        repo_path,
        ["push", "origin", branch],
        timeout=GIT_TIMEOUT,
    )
    if push_proc.returncode != 0:
        err = push_proc.stderr.strip() or push_proc.stdout.strip() or "git push failed"
        return {
            "ok": False,
            "status": "failed",
            "error": err,
            "message": err,
            "branch": branch,
            "committed": committed,
            "output": (push_proc.stderr or push_proc.stdout or "").strip(),
        }

    log_proc = _run_git(repo_path, ["log", "-1", "--oneline"], timeout=15)
    last_line = (log_proc.stdout or "").strip()

    if committed:
        message = f"푸시 완료 · 커밋 {commit_hash or ''} · {branch}"
    else:
        message = f"푸시 완료 (커밋할 변경 없음) · {branch}"

    return {
        "ok": True,
        "status": "success",
        "message": message.strip(),
        "branch": branch,
        "committed": committed,
        "commit": commit_hash,
        "last_commit": last_line,
        "output": (push_proc.stdout or push_proc.stderr or "").strip(),
    }


def deploy_script_path(repo_path: Path) -> Path | None:
    script = repo_path / "deploy.sh"
    return script if script.is_file() else None


def sitemap_build_command(site_id: str) -> list[str] | None:
    cmd = SITEMAP_BUILD_COMMANDS.get(site_id)
    return list(cmd) if cmd else None


def start_deploy(
    repo_path: Path,
    *,
    site_id: str,
    mode: str = "deploy-only",
    with_git: bool = False,
    with_deploy: bool = False,
    include_build_data: bool = True,
) -> dict:
    script = deploy_script_path(repo_path)
    if not script:
        return {"ok": False, "error": "deploy.sh not found"}

    allowed = {"deploy-only", "full", "content-only"}
    flag = f"--{mode}" if mode in allowed else "--deploy-only"

    DEPLOY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = DEPLOY_LOG_DIR / f"deploy-{site_id}-{ts}.log"

    deploy_cmd = ["bash", str(script), flag]
    if with_git:
        deploy_cmd.append("--with-git")
    if with_deploy:
        deploy_cmd.append("--with-deploy")
    build_cmd = sitemap_build_command(site_id) if include_build_data else None
    if build_cmd:
        command_line = f"{shlex.join(build_cmd)} && {shlex.join(deploy_cmd)}"
        cmd = ["bash", "-lc", command_line]
        start_msg = "build_data + deploy 시작"
    else:
        cmd = deploy_cmd
        start_msg = "배포 시작"
    try:
        log_f = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(repo_path),
        )
    except OSError as e:
        return {"ok": False, "error": str(e)}

    job_id = f"{site_id}-{ts}"
    _DEPLOY_JOBS[job_id] = {
        "proc": proc,
        "log_path": log_path,
        "site_id": site_id,
        "started_at": ts,
        "mode": mode,
        "with_git": with_git,
        "with_deploy": with_deploy,
        "include_build_data": include_build_data,
    }
    _prune_deploy_jobs()

    return {
        "ok": True,
        "status": "running",
        "job_id": job_id,
        "pid": proc.pid,
        "command": cmd,
        "log_path": str(log_path),
        "mode": mode,
        "message": f"{start_msg} (PID {proc.pid}) · 로그 tail 확인",
    }


def _prune_deploy_jobs(max_jobs: int = 40) -> None:
    if len(_DEPLOY_JOBS) <= max_jobs:
        return
    finished = [
        jid
        for jid, j in _DEPLOY_JOBS.items()
        if j["proc"].poll() is not None
    ]
    for jid in finished[: len(_DEPLOY_JOBS) - max_jobs]:
        _DEPLOY_JOBS.pop(jid, None)


def tail_deploy_log(log_path: Path, *, lines: int = 35) -> str:
    if not log_path.is_file():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    rows = text.splitlines()
    return "\n".join(rows[-lines:])


def _last_error_line(log_tail: str) -> str:
    for line in reversed(log_tail.splitlines()):
        s = line.strip()
        if not s:
            continue
        if "ERROR:" in s or "error:" in s.lower() or "❌" in s:
            # Strip ANSI color codes for display
            return re.sub(r"\x1b\[[0-9;]*m", "", s)
    return ""


def _infer_log_state(log_tail: str, exit_code: int | None) -> str:
    if exit_code is None:
        return "running"
    if exit_code != 0:
        return "failed"
    tail = log_tail.lower()
    if "❌" in log_tail or "error:" in tail[-1200:]:
        return "failed"
    if "done" in tail or "완료" in log_tail:
        return "success"
    return "success" if exit_code == 0 else "failed"


def deploy_job_status(job_id: str, *, site_id: str | None = None) -> dict[str, Any]:
    job = _DEPLOY_JOBS.get(job_id)
    if not job:
        log_path = DEPLOY_LOG_DIR / f"deploy-{job_id}.log"
        if not log_path.is_file():
            return {
                "ok": False,
                "error": "job not found (서버 재시작 후에는 로그 경로를 알 수 없음)",
            }
        log_tail = tail_deploy_log(log_path)
        return {
            "ok": True,
            "state": "unknown",
            "message": "백그라운드 작업 추적 불가 · 로그만 표시",
            "log_tail": log_tail,
            "log_path": str(log_path),
        }

    if site_id and job.get("site_id") != site_id:
        return {"ok": False, "error": "site_id mismatch"}

    proc = job["proc"]
    exit_code = proc.poll()
    log_path: Path = job["log_path"]
    log_tail = tail_deploy_log(log_path)

    if exit_code is None:
        return {
            "ok": True,
            "state": "running",
            "pid": proc.pid,
            "message": "배포 진행 중…",
            "log_tail": log_tail,
            "log_path": str(log_path),
            "mode": job.get("mode"),
        }

    state = _infer_log_state(log_tail, exit_code)
    err_line = _last_error_line(log_tail)
    if state == "success":
        message = "배포 완료"
    elif err_line:
        message = f"배포 실패 (exit {exit_code}): {err_line[:200]}"
    else:
        message = f"배포 실패 (exit {exit_code})"

    return {
        "ok": True,
        "state": state,
        "exit_code": exit_code,
        "message": message,
        "log_tail": log_tail,
        "log_path": str(log_path),
        "mode": job.get("mode"),
    }


def wait_for_deploy_job(
    job_id: str,
    *,
    site_id: str | None = None,
    timeout: int = 3600,
) -> dict[str, Any]:
    """Block until deploy job finishes; returns deploy_job_status-shaped dict."""
    job = _DEPLOY_JOBS.get(job_id)
    if not job:
        return {"ok": False, "error": "deploy job not found"}
    proc = job["proc"]
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {
            "ok": False,
            "state": "failed",
            "error": f"deploy timeout after {timeout}s",
            "job_id": job_id,
            "log_path": str(job["log_path"]),
        }
    final = deploy_job_status(job_id, site_id=site_id)
    final["job_id"] = job_id
    if final.get("state") == "success":
        final["ok"] = True
    elif final.get("state") == "failed":
        final["ok"] = False
    return final
