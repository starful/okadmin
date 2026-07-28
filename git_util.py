"""Read-only git summary for local repos under WORK_ROOT."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _ahead_behind(status_line: str) -> tuple[int, int]:
    ahead = behind = 0
    m = re.search(r"\[ahead (\d+)", status_line)
    if m:
        ahead = int(m.group(1))
    m = re.search(r"\[behind (\d+)", status_line)
    if m:
        behind = int(m.group(1))
    return ahead, behind


def git_summary(repo_path: Path) -> dict | None:
    if not (repo_path / ".git").is_dir():
        return None
    try:
        status = subprocess.run(
            ["git", "-C", str(repo_path), "status", "-sb"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        log = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-3", "--oneline"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        branch = subprocess.run(
            ["git", "-C", str(repo_path), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        last_commit = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%cI"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return {"error": str(e)}

    lines = [ln for ln in status.stdout.strip().splitlines() if ln]
    status_line = lines[0] if lines else ""
    dirty = len(lines) > 1
    ahead, behind = _ahead_behind(status_line)
    return {
        "branch": branch.stdout.strip() or "?",
        "status_line": status_line,
        "dirty": dirty,
        "ahead": ahead,
        "behind": behind,
        "last_commit_at": (last_commit.stdout or "").strip() or None,
        "recent_commits": [ln for ln in log.stdout.strip().splitlines() if ln],
    }
