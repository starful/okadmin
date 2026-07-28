"""Tests for feature branch helpers."""
from __future__ import annotations

import subprocess
from pathlib import Path

from git_ops import git_create_branch, normalize_branch_name, suggest_branch_name


def test_normalize_branch_name():
    assert normalize_branch_name("Feat/42 Hello World") == "feat/42-hello-world"
    assert normalize_branch_name("  fix/BUG_1  ") == "fix/bug_1"


def test_suggest_branch_name():
    assert suggest_branch_name(issue_number=12, hint="strip periods") == "feat/12-strip-periods"
    assert suggest_branch_name(issue_number=7) == "feat/7"
    assert suggest_branch_name(hint="hotfix") == "feat/hotfix"
    assert suggest_branch_name(
        issue_number=3,
        issue_title="feat: Add shop search compare",
    ) == "feat/3-add-shop-search-compare"


def test_git_create_branch_from_main(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()

    calls: list[list[str]] = []

    def fake_git(_path, args, **kw):
        calls.append(list(args))
        if args[:3] == ["show-ref", "--verify", "--quiet"]:
            ref = args[3]
            if ref == "refs/heads/main":
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")
        if args[:3] == ["checkout", "-b", "feat/test"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("git_ops._run_git", fake_git)
    monkeypatch.setattr("git_ops.git_current_branch", lambda _p: "main")

    out = git_create_branch(tmp_path, "feat/test", base="main")
    assert out["ok"] is True
    assert out["branch"] == "feat/test"
    assert out["created"] is True
    assert ["checkout", "-b", "feat/test", "main"] in calls


def test_git_create_branch_blocks_main_name(tmp_path):
    (tmp_path / ".git").mkdir()
    out = git_create_branch(tmp_path, "main")
    assert out["ok"] is False
