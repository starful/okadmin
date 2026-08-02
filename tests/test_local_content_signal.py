"""local_content_signal — gitignored content needs Cloud Deploy."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from local_content_signal import (
    attach_seo_deploy_hint,
    is_content_gitignored,
    last_cloud_deploy_at,
    local_content_deploy_signal,
    newest_content_mtime,
)


def _git_init(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / ".gitignore").write_text("app/content/\n", encoding="utf-8")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_is_content_gitignored(tmp_path: Path):
    _git_init(tmp_path)
    content = tmp_path / "app" / "content"
    content.mkdir(parents=True)
    (content / "a.md").write_text("hi\n", encoding="utf-8")
    assert is_content_gitignored(tmp_path) is True


def test_is_content_not_gitignored(tmp_path: Path):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    content = tmp_path / "app" / "content"
    content.mkdir(parents=True)
    (content / "a.md").write_text("hi\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert is_content_gitignored(tmp_path) is False


def test_newest_content_mtime(tmp_path: Path):
    content = tmp_path / "app" / "content" / "guides"
    content.mkdir(parents=True)
    f = content / "x.md"
    f.write_text("a\n", encoding="utf-8")
    mt = newest_content_mtime(tmp_path)
    assert mt is not None
    assert abs(mt - f.stat().st_mtime) < 1


def test_last_cloud_deploy_skips_git_and_failed():
    logs = [
        {"kind": "git", "mtime": "2026-07-31 22:00", "state": "success"},
        {"kind": "deploy", "mtime": "2026-07-30 10:00", "state": "failed"},
        {"kind": "deploy", "mtime": "2026-07-29 12:00", "state": "success"},
    ]
    dt = last_cloud_deploy_at(logs)
    assert dt == datetime(2026, 7, 29, 12, 0)


def test_needs_deploy_when_content_newer(tmp_path: Path):
    _git_init(tmp_path)
    content = tmp_path / "app" / "content"
    content.mkdir(parents=True)
    (content / "a.md").write_text("seo\n", encoding="utf-8")
    old = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    sig = local_content_deploy_signal(
        "krcare",
        tmp_path,
        deploy_logs=[{"kind": "deploy", "mtime": old, "state": "success"}],
        seo_finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        seo_applied=3,
    )
    assert sig["content_gitignored"] is True
    assert sig["needs_deploy"] is True
    assert "Deploy" in (sig["reason"] or "")


def test_no_needs_deploy_when_deploy_after_content(tmp_path: Path):
    _git_init(tmp_path)
    content = tmp_path / "app" / "content"
    content.mkdir(parents=True)
    f = content / "a.md"
    f.write_text("old\n", encoding="utf-8")
    # Pretend deploy is in the future relative to file
    future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    sig = local_content_deploy_signal(
        "okpy",
        tmp_path,
        deploy_logs=[{"kind": "deploy", "mtime": future, "state": "success"}],
        seo_finished_at=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        seo_applied=2,
    )
    assert sig["content_gitignored"] is True
    assert sig["needs_deploy"] is False


def test_attach_seo_deploy_hint(tmp_path: Path):
    _git_init(tmp_path)
    result = {
        "results": [
            {"status": "applied"},
            {"status": "ai_failed"},
        ]
    }
    out = attach_seo_deploy_hint("krcare", tmp_path, result)
    assert out["content_gitignored"] is True
    assert out["needs_local_content_deploy"] is True
    assert out["seo_applied_count"] == 1
    assert "Deploy" in (out["deploy_hint"] or "")
