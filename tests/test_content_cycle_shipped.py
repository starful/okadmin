"""Content 7-day clock resets on git push / deploy success."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import hub_logs
import pipeline_runner as pr


def test_mark_content_cycle_shipped_writes_and_skips_older(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pr, "_log_dir", lambda: tmp_path)
    site = "okramen"
    older = datetime(2026, 7, 20, 12, 0, 0)
    newer = datetime(2026, 7, 25, 10, 0, 0)

    first = pr.mark_content_cycle_shipped(site, via="git_push", at=newer)
    assert first["ok"] is True
    assert first.get("skipped") is not True
    status = pr.read_pipeline_status(site)
    assert status is not None
    assert status["finished_at"] == "2026-07-25 10:00:00"
    assert status["content_cycle_via"] == "git_push"
    assert status["ok"] is True

    skipped = pr.mark_content_cycle_shipped(site, via="deploy", at=older)
    assert skipped.get("skipped") is True
    status2 = pr.read_pipeline_status(site)
    assert status2["finished_at"] == "2026-07-25 10:00:00"
    assert status2["content_cycle_via"] == "git_push"


def test_mark_writes_deploy_log(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pr, "_log_dir", lambda: tmp_path)
    log_dir = tmp_path / "deploy_logs"
    log_dir.mkdir()
    monkeypatch.setattr("git_ops.DEPLOY_LOG_DIR", log_dir)
    site = "okramen"
    at = datetime(2026, 7, 25, 16, 0, 0)
    result = pr.mark_content_cycle_shipped(
        site, via="deploy", at=at, record_deploy_log=True, detail="paperclip test"
    )
    assert result["ok"] is True
    assert result.get("deploy_log")
    path = Path(result["deploy_log"])
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "DONE" in text
    assert "완료" in text
    assert "paperclip test" in text


def test_sync_from_git_when_clean_and_pushed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pr, "_log_dir", lambda: tmp_path)
    site = "okramen"
    pipeline_at = "2026-07-20 12:00:00"
    pr.mark_content_cycle_shipped(
        site, via="pipeline", at=datetime(2026, 7, 20, 12, 0, 0)
    )
    commit_at = (datetime.now().replace(microsecond=0) - timedelta(hours=1)).isoformat()
    git_gs = {
        "dirty": False,
        "ahead": 0,
        "last_commit_at": commit_at,
    }
    best = hub_logs.sync_content_cycle_from_activity(
        site,
        pipeline_at=pipeline_at,
        deploy_logs=[],
        git_gs=git_gs,
    )
    assert best is not None
    status = pr.read_pipeline_status(site)
    assert status is not None
    assert status.get("content_cycle_via") == "git"
    # Schedule should move forward from July 20.
    assert status["finished_at"] > pipeline_at


def test_sync_ignores_unpushed_git(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pr, "_log_dir", lambda: tmp_path)
    site = "okonsen"
    pipeline_at = "2026-07-22 09:00:00"
    pr.mark_content_cycle_shipped(
        site, via="pipeline", at=datetime(2026, 7, 22, 9, 0, 0)
    )
    git_gs = {
        "dirty": False,
        "ahead": 2,
        "last_commit_at": datetime.now().isoformat(),
    }
    hub_logs.sync_content_cycle_from_activity(
        site,
        pipeline_at=pipeline_at,
        deploy_logs=[],
        git_gs=git_gs,
    )
    status = pr.read_pipeline_status(site)
    assert status["finished_at"] == "2026-07-22 09:00:00"
    assert status.get("content_cycle_via") == "pipeline"
