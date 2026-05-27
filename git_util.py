"""Read-only git summary for local repos under WORK_ROOT."""
from __future__ import annotations

import subprocess
from pathlib import Path


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
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return {"error": str(e)}

    lines = [ln for ln in status.stdout.strip().splitlines() if ln]
    dirty = len(lines) > 1
    return {
        "branch": branch.stdout.strip() or "?",
        "status_line": lines[0] if lines else "",
        "dirty": dirty,
        "recent_commits": [ln for ln in log.stdout.strip().splitlines() if ln],
    }
