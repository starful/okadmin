"""Tests for GitHub CLI workflow helpers."""
from __future__ import annotations

import subprocess
from pathlib import Path

from git_ops import is_production_branch
from github_ops import _pr_body, create_pr, gh_available, repo_slug


def test_is_production_branch():
    assert is_production_branch(Path("/tmp"), "main")
    assert is_production_branch(Path("/tmp"), "master")
    assert not is_production_branch(Path("/tmp"), "feat/foo")


def test_repo_slug_from_https(tmp_path):
    (tmp_path / ".git").mkdir()
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/starful/okramen.git"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    assert repo_slug(tmp_path) == "starful/okramen"


def test_repo_slug_from_ssh(tmp_path):
    (tmp_path / ".git").mkdir()
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:starful/okadmin.git"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    assert repo_slug(tmp_path) == "starful/okadmin"


def test_pr_body_closes_issue():
    body = _pr_body(summary="Remove periods", issue_number=42, test_plan="- [ ] pytest")
    assert "Closes #42" in body
    assert "Remove periods" in body
    assert "Deploy notes" in body


def test_pr_body_no_issue():
    body = _pr_body(summary="Hotfix", issue_number=None)
    assert "(none)" in body


def test_gh_available_no_cli(monkeypatch):
    monkeypatch.setattr("github_ops.shutil.which", lambda _: None)
    out = gh_available()
    assert out["ok"] is False
    assert "not found" in (out.get("error") or "").lower()


def test_create_pr_blocks_main_branch(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("github_ops.git_current_branch", lambda _path: "main")
    monkeypatch.setattr(
        "github_ops.gh_available",
        lambda: {"ok": True, "logged_in": True},
    )
    out = create_pr(tmp_path, title="Test")
    assert out["ok"] is False
    assert "feature branch" in (out.get("error") or "").lower()


def test_draft_issue_english_from_diff(tmp_path, monkeypatch):
    from github_ops import draft_issue_english

    (tmp_path / ".git").mkdir()

    monkeypatch.setattr(
        "github_ops._ship_change_context",
        lambda _p, **kw: {
            "ok": True,
            "branch": "feat/test",
            "base": "main",
            "status": {"file_count": 1},
            "has_changes": True,
            "commits": "abc feat: test",
            "range_stat": " README.md | 1 +",
            "range_diff": "+hello",
            "wt_stat": " README.md | 1 +",
            "wt_diff": "diff --git a/README.md\n+hello",
        },
    )
    monkeypatch.setattr("github_ops.repo_slug", lambda _p: "starful/demo")
    monkeypatch.setattr("llm_claude.ensure_llm", lambda: True)
    monkeypatch.setattr(
        "llm_claude.claude_json",
        lambda _prompt: {
            "title": "feat: update README intro",
            "body": "## Context\nUpdate readme.\n\n## Acceptance criteria\n- [ ] README shows hello",
        },
    )

    out = draft_issue_english(tmp_path, site_id="demo", hint="한 줄 소개 추가")
    assert out["ok"] is True
    assert out["title"].startswith("feat:")
    assert "Context" in out["body"]


def test_draft_pr_english_from_branch(tmp_path, monkeypatch):
    from github_ops import draft_pr_english

    (tmp_path / ".git").mkdir()

    monkeypatch.setattr(
        "github_ops._ship_change_context",
        lambda _p, **kw: {
            "ok": True,
            "branch": "feat/42-periods",
            "base": "main",
            "status": {"file_count": 0},
            "has_changes": True,
            "commits": "abc feat: strip periods",
            "range_stat": " instagram_prompt_queue.py | 10 +",
            "range_diff": "+strip_slide_copy",
            "wt_stat": "(clean working tree)",
            "wt_diff": "(no uncommitted diff)",
        },
    )
    monkeypatch.setattr("github_ops.repo_slug", lambda _p: "starful/okadmin")
    monkeypatch.setattr("llm_claude.ensure_llm", lambda: True)
    monkeypatch.setattr(
        "llm_claude.claude_json",
        lambda _prompt: {
            "title": "feat: strip slide punctuation",
            "summary": "- Remove trailing periods from card copy\n- Add tests",
            "test_plan": "- [ ] pytest tests/test_instagram_prompt_queue.py",
        },
    )

    out = draft_pr_english(tmp_path, site_id="okadmin", issue_number=42)
    assert out["ok"] is True
    assert out["title"].startswith("feat:")
    assert "Closes #42" in out["body"]
    assert "pytest" in out["test_plan"]


def test_draft_commit_english_from_worktree(tmp_path, monkeypatch):
    from github_ops import draft_commit_english

    (tmp_path / ".git").mkdir()

    monkeypatch.setattr(
        "github_ops._ship_change_context",
        lambda _p, **kw: {
            "ok": True,
            "branch": "feat/test",
            "base": "main",
            "status": {"file_count": 1},
            "has_changes": True,
            "commits": "(no commits ahead of base)",
            "range_stat": "(no diff vs base)",
            "range_diff": "(no diff vs base)",
            "wt_stat": " README.md | 1 +",
            "wt_diff": "diff --git a/README.md\n+hello",
        },
    )
    monkeypatch.setattr("github_ops.repo_slug", lambda _p: "starful/demo")
    monkeypatch.setattr("llm_claude.ensure_llm", lambda: True)
    monkeypatch.setattr(
        "llm_claude.claude_json",
        lambda _prompt: {"message": "feat: add hello to README"},
    )

    out = draft_commit_english(tmp_path, site_id="demo")
    assert out["ok"] is True
    assert out["message"].startswith("feat:")


def test_pr_review_local_fallback(tmp_path, monkeypatch):
    from github_ops import pr_review

    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("github_ops.git_current_branch", lambda _p: "feat/x")
    monkeypatch.setattr("github_ops.pr_for_branch", lambda *_a, **_kw: {"ok": True, "pr": None, "branch": "feat/x"})
    monkeypatch.setattr(
        "git_ops.git_status_detail",
        lambda _p: {"ok": True, "dirty": False, "branch": "feat/x"},
    )
    monkeypatch.setattr(
        "git_util.git_summary",
        lambda _p: {"branch": "feat/x", "ahead": 0, "dirty": False},
    )
    monkeypatch.setattr(
        "git_ops._run_git",
        lambda _p, args, **kw: subprocess.CompletedProcess(
            args, 0, stdout=" file.py | 2 ++\n" if "--stat" in args else "+change\n", stderr="",
        ),
    )

    out = pr_review(tmp_path)
    assert out["ok"] is True
    assert out["source"] == "local"
    assert out["can_merge"] is False
    assert "no open PR" in " ".join(out.get("blockers") or [])


def test_pr_review_github_diff(tmp_path, monkeypatch):
    from github_ops import pr_review

    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("github_ops.gh_available", lambda: {"ok": True, "logged_in": True})
    monkeypatch.setattr("github_ops.git_current_branch", lambda _p: "feat/x")
    monkeypatch.setattr(
        "github_ops.pr_for_branch",
        lambda *_a, **_kw: {
            "ok": True,
            "pr": {
                "number": 7,
                "title": "feat: test",
                "url": "https://github.com/starful/demo/pull/7",
                "mergeable": True,
                "baseRefName": "main",
                "headRefName": "feat/x",
                "additions": 10,
                "deletions": 2,
                "changedFiles": 1,
            },
            "branch": "feat/x",
        },
    )
    monkeypatch.setattr(
        "git_ops.git_status_detail",
        lambda _p: {"ok": True, "dirty": False},
    )
    monkeypatch.setattr(
        "git_util.git_summary",
        lambda _p: {"branch": "feat/x", "ahead": 0},
    )

    def fake_gh(_path, args, **kw):
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(args, 0, stdout='{"number":7,"mergeable":true}', stderr="")
        if args[:2] == ["pr", "diff"]:
            return subprocess.CompletedProcess(args, 0, stdout="+added line\n", stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="fail")

    monkeypatch.setattr("github_ops._run_gh", fake_gh)

    out = pr_review(tmp_path)
    assert out["ok"] is True
    assert out["source"] == "github"
    assert out["can_merge"] is True
    assert "+added line" in out["diff"]


def test_pr_review_github_diff_too_large_falls_back_local(tmp_path, monkeypatch):
    from github_ops import pr_review

    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("github_ops.gh_available", lambda: {"ok": True, "logged_in": True})
    monkeypatch.setattr("github_ops.git_current_branch", lambda _p: "feat/x")
    monkeypatch.setattr(
        "git_ops.git_status_detail",
        lambda _p: {"ok": True, "dirty": False},
    )
    monkeypatch.setattr(
        "git_util.git_summary",
        lambda _p: {"branch": "feat/x", "ahead": 0},
    )

    def fake_gh(_path, args, **kw):
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    '{"number":14,"title":"chore: content","url":"https://github.com/starful/okpy/pull/14",'
                    '"mergeable":true,"baseRefName":"main","headRefName":"feat/x",'
                    '"additions":100,"deletions":0,"changedFiles":400}'
                ),
                stderr="",
            )
        if args[:2] == ["pr", "diff"]:
            return subprocess.CompletedProcess(
                args,
                1,
                stdout="",
                stderr=(
                    "HTTP 406: Sorry, the diff exceeded the maximum number of files (300). "
                    "PullRequest.diff too_large"
                ),
            )
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="fail")

    monkeypatch.setattr("github_ops._run_gh", fake_gh)
    monkeypatch.setattr(
        "github_ops._local_pr_review",
        lambda *_a, **_kw: {
            "source": "local",
            "branch": "feat/x",
            "base": "main",
            "stat": "400 files changed",
            "diff": "+local truncated\n",
            "empty": False,
            "checks": {
                "has_open_pr": False,
                "uncommitted": False,
                "unpushed": False,
                "ahead": 0,
                "has_diff": True,
            },
        },
    )

    out = pr_review(tmp_path, number=14)
    assert out["ok"] is True
    assert out["can_merge"] is True
    assert out["source"] == "github+local"
    assert out["warnings"]
    assert "too large" in out["warnings"][0].lower()
    assert "local truncated" in out["diff"]
    assert out["pr"]["changedFiles"] == 400


def test_draft_ship_english_one_call(tmp_path, monkeypatch):
    from github_ops import draft_ship_english

    (tmp_path / ".git").mkdir()

    monkeypatch.setattr(
        "github_ops._ship_change_context",
        lambda _p, **kw: {
            "ok": True,
            "branch": "main",
            "base": "main",
            "status": {"file_count": 2},
            "has_changes": True,
            "commits": "(no commits ahead of base)",
            "range_stat": " shop.py | 10 +",
            "range_diff": "+search",
            "wt_stat": " shop.py | 10 +",
            "wt_diff": "+search block",
        },
    )
    monkeypatch.setattr("github_ops.repo_slug", lambda _p: "starful/demo")
    monkeypatch.setattr("llm_claude.ensure_llm", lambda: True)
    monkeypatch.setattr(
        "llm_claude.claude_json",
        lambda _prompt: {
            "branch_slug": "add-shop-search",
            "issue": {
                "title": "feat: add shop search",
                "body": "## Context\nAdd search.\n\n## Acceptance criteria\n- [ ] search works",
            },
            "commit": {"message": "feat: add shop search UI"},
            "pr": {
                "title": "feat: add shop search",
                "summary": "- Add search block",
                "test_plan": "- [ ] manual search test",
            },
        },
    )

    out = draft_ship_english(tmp_path, site_id="demo", hint="검색 추가")
    assert out["ok"] is True
    assert out["branch_slug"] == "add-shop-search"
    assert out["issue"]["title"].startswith("feat:")
    assert out["commit"]["message"].startswith("feat:")
    assert out["pr"]["title"].startswith("feat:")


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, capture_output=True, check=True)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)


def test_ship_change_context_counts_untracked_content(tmp_path):
    """Content generation usually adds new untracked MD — must count as ship changes."""
    from github_ops import _ship_change_context

    _init_git_repo(tmp_path)
    content = tmp_path / "content"
    content.mkdir()
    (content / "new_shop_en.md").write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")

    ctx = _ship_change_context(tmp_path)
    assert ctx["ok"] is True
    assert ctx["has_changes"] is True
    assert "new_shop_en.md" in ctx["wt_files"]
    assert ctx["status"]["dirty"] is True
def test_draft_ship_english_untracked_content_no_hint(tmp_path, monkeypatch):
    """Ship prep after content gen should work without a manual hint."""
    from github_ops import draft_ship_english

    _init_git_repo(tmp_path)
    content = tmp_path / "content"
    content.mkdir()
    (content / "new_shop_en.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")

    monkeypatch.setattr("github_ops.repo_slug", lambda _p: "starful/demo")
    monkeypatch.setattr("llm_claude.ensure_llm", lambda: True)
    monkeypatch.setattr(
        "llm_claude.claude_json",
        lambda _prompt: {
            "branch_slug": "add-new-shop",
            "issue": {
                "title": "feat: add new shop content",
                "body": "## Context\nNew MD.\n\n## Acceptance criteria\n- [ ] page builds",
            },
            "commit": {"message": "feat: add new shop markdown"},
            "pr": {
                "title": "feat: add new shop content",
                "summary": "- Add new_shop_en.md",
                "test_plan": "- [ ] build site",
            },
        },
    )

    out = draft_ship_english(tmp_path, site_id="demo", hint="")
    assert out["ok"] is True
    assert out["commit"]["message"].startswith("feat:")
