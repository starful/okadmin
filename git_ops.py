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
    "statfacts": ["python3", "script/build_data.py"],
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


PRODUCTION_BRANCHES = frozenset({"main", "master"})
BRANCH_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")


def is_production_branch(repo_path: Path, branch: str | None = None) -> bool:
    b = (branch or git_current_branch(repo_path)).strip()
    return b in PRODUCTION_BRANCHES


def normalize_branch_name(name: str) -> str:
    """Sanitize user branch input for git."""
    text = (name or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9._/-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-/")
    return text


def suggest_branch_name(
    *,
    issue_number: int | None = None,
    hint: str = "",
    issue_title: str = "",
    prefix: str = "feat",
) -> str:
    """Default branch name for Ship UI (issue # + short slug from title)."""
    pre = (prefix or "feat").strip().rstrip("/") or "feat"
    slug_source = (issue_title or hint or "").strip()
    for p in ("feat:", "fix:", "chore:", "docs:", "test:"):
        if slug_source.lower().startswith(p):
            slug_source = slug_source[len(p) :].strip()
    slug = normalize_branch_name(slug_source)[:32].strip("-")
    if issue_number is not None:
        base = f"{pre}/{int(issue_number)}"
        return f"{base}-{slug}" if slug else base
    return f"{pre}/{slug}" if slug else f"{pre}/"


def git_create_branch(
    repo_path: Path,
    name: str,
    *,
    base: str = "main",
) -> dict[str, Any]:
    """Create and checkout a feature branch (from base or current HEAD on production branch)."""
    if not (repo_path / ".git").is_dir():
        return {"ok": False, "error": "no git repository"}

    branch = normalize_branch_name(name)
    if not branch or branch in PRODUCTION_BRANCHES:
        return {"ok": False, "error": "invalid branch name — use feat/… or fix/…"}
    if not BRANCH_NAME_RE.match(branch):
        return {"ok": False, "error": "invalid branch name characters"}

    current = git_current_branch(repo_path)
    if current == branch:
        return {"ok": True, "branch": branch, "created": False, "message": f"already on {branch}"}

    exists = _run_git(repo_path, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], timeout=15)
    if exists.returncode == 0:
        sw = _run_git(repo_path, ["checkout", branch], timeout=30)
        if sw.returncode != 0:
            return {
                "ok": False,
                "error": (sw.stderr or sw.stdout or "checkout failed").strip(),
                "branch": branch,
            }
        return {"ok": True, "branch": branch, "created": False, "message": f"switched to {branch}"}

    base = (base or "main").strip() or "main"
    if current in PRODUCTION_BRANCHES:
        start = base
        if _run_git(repo_path, ["show-ref", "--verify", "--quiet", f"refs/heads/{base}"], timeout=15).returncode != 0:
            remote_ref = f"refs/remotes/origin/{base}"
            if _run_git(repo_path, ["show-ref", "--verify", "--quiet", remote_ref], timeout=15).returncode == 0:
                start = f"origin/{base}"
        create = _run_git(repo_path, ["checkout", "-b", branch, start], timeout=30)
    else:
        create = _run_git(repo_path, ["checkout", "-b", branch], timeout=30)

    if create.returncode != 0:
        return {
            "ok": False,
            "error": (create.stderr or create.stdout or "branch create failed").strip(),
            "branch": branch,
        }
    return {"ok": True, "branch": branch, "created": True, "message": f"branch {branch} created"}


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

    try:
        from pipeline_runner import mark_content_cycle_shipped

        mark_content_cycle_shipped(site_id, via="git_push", record_deploy_log=True)
    except Exception:
        pass

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


def git_status_detail(repo_path: Path) -> dict[str, Any]:
    """Porcelain status + short summary for Hub Git tab."""
    if not (repo_path / ".git").is_dir():
        return {"ok": False, "error": "no git repository"}
    branch = git_current_branch(repo_path)
    short = _run_git(repo_path, ["status", "-sb"], timeout=30)
    porcelain = _run_git(repo_path, ["status", "--porcelain", "-uall"], timeout=30)
    if short.returncode != 0:
        return {
            "ok": False,
            "error": short.stderr.strip() or short.stdout.strip() or "git status failed",
        }
    lines = [ln for ln in (porcelain.stdout or "").splitlines() if ln]
    short_lines = [ln for ln in (short.stdout or "").splitlines() if ln]
    return {
        "ok": True,
        "branch": branch,
        "dirty": bool(lines),
        "status_line": short_lines[0] if short_lines else "",
        "files": lines[:200],
        "file_count": len(lines),
        "status_text": (short.stdout or "").strip(),
    }


def git_diff_detail(repo_path: Path, *, staged: bool = False, max_chars: int = 48000) -> dict[str, Any]:
    """Unified diff (working tree or staged)."""
    if not (repo_path / ".git").is_dir():
        return {"ok": False, "error": "no git repository"}
    args = ["diff", "--stat"] if not staged else ["diff", "--cached", "--stat"]
    stat = _run_git(repo_path, args, timeout=60)
    args2 = ["diff"] if not staged else ["diff", "--cached"]
    diff = _run_git(repo_path, args2, timeout=90)
    if stat.returncode not in (0, 1) and diff.returncode not in (0, 1):
        return {
            "ok": False,
            "error": (diff.stderr or stat.stderr or "git diff failed").strip(),
        }
    text = (diff.stdout or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n… truncated ({len(text)} chars)"
    return {
        "ok": True,
        "staged": staged,
        "stat": (stat.stdout or "").strip(),
        "diff": text,
        "empty": not text,
    }


def git_commit_only(
    repo_path: Path,
    *,
    site_id: str,
    message: str | None = None,
) -> dict[str, Any]:
    """git add -A + commit (no push)."""
    if not (repo_path / ".git").is_dir():
        return {"ok": False, "error": "no git repository"}
    branch = git_current_branch(repo_path)
    msg = (message or "").strip() or (
        f"chore: hub commit {site_id} {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    add_proc = _run_git(repo_path, ["add", "-A"])
    if add_proc.returncode != 0:
        return {
            "ok": False,
            "error": add_proc.stderr.strip() or add_proc.stdout.strip() or "git add failed",
        }
    diff_proc = _run_git(repo_path, ["diff", "--cached", "--quiet"])
    if diff_proc.returncode == 0:
        return {
            "ok": True,
            "committed": False,
            "branch": branch,
            "message": f"커밋할 변경 없음 · {branch}",
        }
    commit_proc = _run_git(repo_path, ["commit", "-m", msg])
    if commit_proc.returncode != 0:
        return {
            "ok": False,
            "error": commit_proc.stderr.strip()
            or commit_proc.stdout.strip()
            or "git commit failed",
        }
    head = _run_git(repo_path, ["rev-parse", "--short", "HEAD"], timeout=15)
    commit_hash = (head.stdout or "").strip()
    return {
        "ok": True,
        "committed": True,
        "commit": commit_hash,
        "branch": branch,
        "message": f"커밋 {commit_hash} · {branch}",
    }


def git_push_only(repo_path: Path, *, site_id: str | None = None) -> dict[str, Any]:
    """Push current branch only (no add/commit)."""
    if not (repo_path / ".git").is_dir():
        return {"ok": False, "error": "no git repository"}
    branch = git_current_branch(repo_path)
    push_proc = _run_git(repo_path, ["push", "-u", "origin", branch], timeout=GIT_TIMEOUT)
    if push_proc.returncode != 0:
        err = push_proc.stderr.strip() or push_proc.stdout.strip() or "git push failed"
        return {"ok": False, "error": err, "branch": branch, "message": err}
    log_proc = _run_git(repo_path, ["log", "-1", "--oneline"], timeout=15)
    if site_id:
        try:
            from pipeline_runner import mark_content_cycle_shipped

            mark_content_cycle_shipped(site_id, via="git_push", record_deploy_log=True)
        except Exception:
            pass
    return {
        "ok": True,
        "branch": branch,
        "last_commit": (log_proc.stdout or "").strip(),
        "message": f"푸시 완료 · {branch}",
        "output": (push_proc.stdout or push_proc.stderr or "").strip(),
    }


def deploy_script_path(repo_path: Path) -> Path | None:
    script = repo_path / "deploy.sh"
    return script if script.is_file() else None


def sitemap_build_command(site_id: str) -> list[str] | None:
    cmd = SITEMAP_BUILD_COMMANDS.get(site_id)
    return list(cmd) if cmd else None


def site_has_running_deploy(site_id: str) -> bool:
    """True if this site has a still-running deploy/push job."""
    for job in _DEPLOY_JOBS.values():
        if job.get("site_id") != site_id:
            continue
        proc = job.get("proc")
        if proc is not None and proc.poll() is None:
            return True
    return False


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


def _deploy_failure_reason(log_tail: str) -> str:
    """Pick a short, high-signal failure cause from deploy log tail."""
    lines = [
        re.sub(r"\x1b\[[0-9;]*m", "", ln).strip()
        for ln in (log_tail or "").splitlines()
        if ln.strip()
    ]
    for s in reversed(lines):
        low = s.lower()
        if "seo guard failed" in low:
            return s[:240]
    for s in reversed(lines):
        low = s.lower()
        if "build failure" in low:
            return s[:240]
    for s in reversed(lines):
        if s.startswith("ERROR:") or s.startswith("ERROR "):
            return s[:240]
    return _last_error_line(log_tail)[:240]


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
    err_line = _deploy_failure_reason(log_tail) if state == "failed" else ""
    if state == "success":
        message = "배포 완료"
        if not job.get("_content_cycle_noted"):
            sid = job.get("site_id") or site_id
            if sid:
                try:
                    from pipeline_runner import mark_content_cycle_shipped

                    via = "git_push" if job.get("with_git") and not job.get("with_deploy") else "deploy"
                    mark_content_cycle_shipped(str(sid), via=via, record_deploy_log=False)
                except Exception:
                    pass
            job["_content_cycle_noted"] = True
    elif err_line:
        message = err_line
    else:
        message = f"배포 실패 (exit {exit_code})"

    return {
        "ok": True,
        "state": state,
        "exit_code": exit_code,
        "message": message,
        "error_summary": err_line or None,
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
