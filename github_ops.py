"""GitHub workflow helpers via GitHub CLI (gh). Local Work Hub only."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from git_ops import git_current_branch

GH_TIMEOUT = 90
DEFAULT_BASE = "main"
PRODUCTION_BRANCHES = frozenset({"main", "master"})

PR_BODY_TEMPLATE = """## Summary
{summary}

## Related issue
{issue_line}

## Test plan
{test_plan}

## Deploy notes
Production deploy runs from `main` after this PR is merged (okadmin Deploy tab).
"""


def _run_gh(repo_path: Path, args: list[str], *, timeout: int = GH_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def gh_available() -> dict[str, Any]:
    """Return {ok, logged_in, user?, error?}."""
    if not shutil.which("gh"):
        return {"ok": False, "logged_in": False, "error": "gh CLI not found — install: brew install gh"}
    proc = _run_gh(Path.cwd(), ["auth", "status", "--hostname", "github.com"], timeout=30)
    text = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return {
            "ok": False,
            "logged_in": False,
            "error": "gh not logged in — run: gh auth login",
            "detail": text.strip()[:400],
        }
    logged_in = "Logged in to github.com" in text
    user = ""
    m = re.search(r"account\s+(\S+)", text)
    if m:
        user = m.group(1)
    return {"ok": logged_in, "logged_in": logged_in, "user": user or None}


def repo_slug(repo_path: Path) -> str | None:
    """Parse starful/okramen from origin URL."""
    from git_ops import _run_git

    proc = _run_git(repo_path, ["remote", "get-url", "origin"], timeout=15)
    if proc.returncode != 0:
        return None
    url = (proc.stdout or "").strip()
    if not url:
        return None
    # git@github.com:org/repo.git or https://github.com/org/repo.git
    m = re.search(r"github\.com[:/]([^/]+)/([^/.\s]+)", url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def _parse_json(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _gh_err(proc: subprocess.CompletedProcess) -> str:
    return (proc.stderr or proc.stdout or "gh command failed").strip()[:500]


def github_config(repo_path: Path) -> dict[str, Any]:
    auth = gh_available()
    slug = repo_slug(repo_path) if (repo_path / ".git").is_dir() else None
    branch = git_current_branch(repo_path) if slug else None
    return {
        "ok": bool(auth.get("logged_in") and slug),
        "gh": auth,
        "repo": slug,
        "branch": branch,
        "on_production_branch": branch in PRODUCTION_BRANCHES if branch else False,
        "default_base": DEFAULT_BASE,
    }


def _ship_change_context(
    repo_path: Path,
    *,
    base: str = DEFAULT_BASE,
    max_diff_chars: int = 12000,
) -> dict[str, Any]:
    """Working tree + branch-vs-base commits/diff for issue/PR drafts.

    New content MD files are often untracked; ``git diff`` alone misses them, so
    porcelain dirty status counts as changes too.
    """
    from git_ops import _run_git, git_current_branch, git_diff_detail, git_status_detail

    status = git_status_detail(repo_path)
    if not status.get("ok"):
        return {"ok": False, "error": status.get("error") or "git status failed"}

    branch = git_current_branch(repo_path)
    wt = git_diff_detail(repo_path, max_chars=max_diff_chars)
    log_proc = _run_git(repo_path, ["log", f"{base}..HEAD", "--oneline", "-20"], timeout=30)
    commits = (log_proc.stdout or "").strip() or "(no commits ahead of base)"
    range_stat = _run_git(repo_path, ["diff", "--stat", f"{base}...HEAD"], timeout=60)
    range_diff_proc = _run_git(repo_path, ["diff", f"{base}...HEAD"], timeout=90)
    range_diff = (range_diff_proc.stdout or "").strip()
    if len(range_diff) > max_diff_chars:
        range_diff = range_diff[:max_diff_chars] + f"\n… truncated ({len(range_diff)} chars)"

    files = list(status.get("files") or [])
    files_text = "\n".join(files[:80])
    dirty = bool(status.get("dirty"))
    wt_stat = (wt.get("stat") or "").strip()
    wt_diff = (wt.get("diff") or "").strip()
    if not wt_stat and files_text:
        wt_stat = f"(working tree dirty — includes untracked)\n{files_text}"
    elif not wt_stat:
        wt_stat = "(clean working tree)"
    if not wt_diff and files_text:
        wt_diff = f"(no unified diff — new/untracked or binary)\n{files_text}"
    elif not wt_diff:
        wt_diff = "(no uncommitted diff)"

    has_changes = bool(
        dirty
        or (wt.get("diff") or "").strip()
        or commits != "(no commits ahead of base)"
        or range_diff
    )
    return {
        "ok": True,
        "branch": branch,
        "base": base,
        "status": status,
        "wt_files": files_text or "(none)",
        "wt_stat": wt_stat,
        "wt_diff": wt_diff,
        "commits": commits,
        "range_stat": (range_stat.stdout or "").strip() or "(no diff vs base)",
        "range_diff": range_diff or "(no diff vs base)",
        "has_changes": has_changes,
    }


def draft_issue_english(
    repo_path: Path,
    *,
    site_id: str = "",
    hint: str = "",
    max_diff_chars: int = 12000,
    base: str = DEFAULT_BASE,
) -> dict[str, Any]:
    """Draft GitHub issue title + body in English from git changes (Claude CLI)."""
    from llm_claude import claude_json, ensure_llm

    if not ensure_llm():
        return {"ok": False, "error": "Claude CLI not logged in — run `claude` then /login"}

    ctx = _ship_change_context(repo_path, base=base, max_diff_chars=max_diff_chars)
    if not ctx.get("ok"):
        return {"ok": False, "error": ctx.get("error") or "git context failed"}

    branch = ctx["branch"]
    slug = repo_slug(repo_path) or site_id or "repository"
    hint = (hint or "").strip()
    if not ctx.get("has_changes") and not hint:
        return {
            "ok": False,
            "error": "no changes vs base — commit, push, or add a short hint",
        }

    prompt = f"""Write a GitHub issue in English for a solo maintainer.

Repository: {slug}
Site id: {site_id or "(n/a)"}
Branch: {branch}
Base branch: {base}
Dirty files: {ctx["status"].get("file_count") or 0}

Developer hint (may be Korean — translate intent to English):
{hint or "(none)"}

Commits ({base}..HEAD):
{ctx["commits"]}

Diff vs {base} --stat:
{ctx["range_stat"]}

Diff vs {base} (truncated):
{ctx["range_diff"]}

Uncommitted diff --stat:
{ctx["wt_stat"]}

Uncommitted diff (truncated):
{ctx["wt_diff"][:max_diff_chars]}

Return JSON only:
{{
  "title": "short imperative title, max 72 chars, no trailing period",
  "body": "markdown with ## Context, ## Proposed changes, ## Acceptance criteria (bullet lists OK)"
}}

Rules:
- English only in title and body
- Title: feat/fix/chore prefix when appropriate
- Body: concise, specific to the changes; do not invent unrelated scope
- No code fences in JSON values
"""
    try:
        data = claude_json(prompt)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)[:240]}
    if not data:
        return {"ok": False, "error": "Claude returned no JSON"}
    title = str(data.get("title") or "").strip()
    body = str(data.get("body") or "").strip()
    if not title:
        return {"ok": False, "error": "draft missing title"}
    if len(title) > 120:
        title = title[:117] + "..."
    return {"ok": True, "title": title, "body": body, "branch": branch, "repo": slug}


def draft_commit_english(
    repo_path: Path,
    *,
    site_id: str = "",
    hint: str = "",
    max_diff_chars: int = 12000,
    base: str = DEFAULT_BASE,
) -> dict[str, Any]:
    """Draft a Conventional Commit message in English from working tree diff (Claude CLI)."""
    from llm_claude import claude_json, ensure_llm

    if not ensure_llm():
        return {"ok": False, "error": "Claude CLI not logged in — run `claude` then /login"}

    ctx = _ship_change_context(repo_path, base=base, max_diff_chars=max_diff_chars)
    if not ctx.get("ok"):
        return {"ok": False, "error": ctx.get("error") or "git context failed"}

    branch = ctx["branch"]
    slug = repo_slug(repo_path) or site_id or "repository"
    hint = (hint or "").strip()
    wt_diff = (ctx.get("wt_diff") or "").strip()
    dirty = bool((ctx.get("status") or {}).get("dirty"))
    has_wt = dirty or (wt_diff and wt_diff not in ("(no uncommitted diff)", ""))
    if not has_wt and not hint:
        return {"ok": False, "error": "no uncommitted changes — edit files or add a short hint"}

    prompt = f"""Write a git commit message in English for a solo maintainer.

Repository: {slug}
Site id: {site_id or "(n/a)"}
Branch: {branch}

Developer hint (may be Korean — translate intent to English):
{hint or "(none)"}

Working tree files (porcelain):
{ctx.get("wt_files") or "(none)"}

Uncommitted diff --stat:
{ctx["wt_stat"]}

Uncommitted diff (truncated):
{wt_diff[:max_diff_chars]}

Recent commits on branch ({base}..HEAD):
{ctx["commits"]}

Return JSON only:
{{
  "message": "feat: short imperative summary (max 72 chars, Conventional Commits prefix)"
}}

Rules:
- English only
- One line subject; optional body after blank line if needed (keep short)
- feat/fix/chore/docs/test prefix when appropriate
- Specific to the diff or new content files; do not invent unrelated scope
- No code fences in JSON values
"""
    try:
        data = claude_json(prompt)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)[:240]}
    if not data:
        return {"ok": False, "error": "Claude returned no JSON"}
    message = str(data.get("message") or "").strip()
    if not message:
        return {"ok": False, "error": "draft missing message"}
    if len(message) > 500:
        message = message[:497] + "..."
    return {"ok": True, "message": message, "branch": branch, "repo": slug}


def draft_pr_english(
    repo_path: Path,
    *,
    site_id: str = "",
    hint: str = "",
    issue_number: int | None = None,
    max_diff_chars: int = 12000,
    base: str = DEFAULT_BASE,
) -> dict[str, Any]:
    """Draft PR title + summary + test plan in English (Claude CLI)."""
    from llm_claude import claude_json, ensure_llm

    if not ensure_llm():
        return {"ok": False, "error": "Claude CLI not logged in — run `claude` then /login"}

    ctx = _ship_change_context(repo_path, base=base, max_diff_chars=max_diff_chars)
    if not ctx.get("ok"):
        return {"ok": False, "error": ctx.get("error") or "git context failed"}

    branch = ctx["branch"]
    if branch in PRODUCTION_BRANCHES:
        return {
            "ok": False,
            "error": f"create a feature branch first (currently on {branch})",
        }

    slug = repo_slug(repo_path) or site_id or "repository"
    hint = (hint or "").strip()
    if not ctx.get("has_changes") and not hint:
        return {
            "ok": False,
            "error": "no changes vs base — commit, push, or add a short hint",
        }

    issue_hint = f"Link to issue #{issue_number} in test plan if relevant." if issue_number else ""

    prompt = f"""Write a GitHub pull request in English for a solo maintainer.

Repository: {slug}
Site id: {site_id or "(n/a)"}
Head branch: {branch}
Base branch: {base}
{issue_hint}

Developer hint (may be Korean — translate intent to English):
{hint or "(none)"}

Commits ({base}..HEAD):
{ctx["commits"]}

Diff vs {base} --stat:
{ctx["range_stat"]}

Diff vs {base} (truncated):
{ctx["range_diff"]}

Uncommitted diff --stat:
{ctx["wt_stat"]}

Uncommitted diff (truncated):
{ctx["wt_diff"][:max_diff_chars]}

Return JSON only:
{{
  "title": "short PR title, max 72 chars, no trailing period, feat/fix/chore prefix",
  "summary": "2-4 bullet lines for PR Summary section (plain text, use - bullets)",
  "test_plan": "markdown checklist for Test plan, each line - [ ] ..."
}}

Rules:
- English only
- Be specific to the diff; do not invent unrelated scope
- test_plan must be actionable (pytest, manual UI check, etc.)
- No code fences in JSON values
"""
    try:
        data = claude_json(prompt)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)[:240]}
    if not data:
        return {"ok": False, "error": "Claude returned no JSON"}
    title = str(data.get("title") or "").strip()
    summary = str(data.get("summary") or "").strip()
    test_plan = str(data.get("test_plan") or "").strip()
    if not title:
        return {"ok": False, "error": "draft missing title"}
    if len(title) > 120:
        title = title[:117] + "..."
    if not summary:
        summary = title
    body = _pr_body(summary=summary, issue_number=issue_number, test_plan=test_plan)
    return {
        "ok": True,
        "title": title,
        "summary": summary,
        "test_plan": test_plan,
        "body": body,
        "branch": branch,
        "repo": slug,
        "issue_number": issue_number,
    }


    return {
        "ok": True,
        "title": title,
        "summary": summary,
        "test_plan": test_plan,
        "body": body,
        "branch": branch,
        "repo": slug,
        "issue_number": issue_number,
    }


def draft_ship_english(
    repo_path: Path,
    *,
    site_id: str = "",
    hint: str = "",
    max_diff_chars: int = 12000,
    base: str = DEFAULT_BASE,
) -> dict[str, Any]:
    """Draft issue + commit + PR + branch slug in one Claude call."""
    from llm_claude import claude_json, ensure_llm

    if not ensure_llm():
        return {"ok": False, "error": "Claude CLI not logged in — run `claude` then /login"}

    ctx = _ship_change_context(repo_path, base=base, max_diff_chars=max_diff_chars)
    if not ctx.get("ok"):
        return {"ok": False, "error": ctx.get("error") or "git context failed"}

    branch = ctx["branch"]
    slug = repo_slug(repo_path) or site_id or "repository"
    hint = (hint or "").strip()
    if not ctx.get("has_changes") and not hint:
        return {
            "ok": False,
            "error": "no changes vs base — edit files or add a short hint",
        }

    prompt = f"""Plan a full GitHub ship workflow in English for a solo maintainer (issue → branch → commit → PR).

Repository: {slug}
Site id: {site_id or "(n/a)"}
Current branch: {branch}
Base branch: {base}

Developer hint (may be Korean — translate intent to English):
{hint or "(none)"}

Commits ({base}..HEAD):
{ctx["commits"]}

Diff vs {base} --stat:
{ctx["range_stat"]}

Diff vs {base} (truncated):
{ctx["range_diff"]}

Working tree files (porcelain):
{ctx.get("wt_files") or "(none)"}

Uncommitted diff --stat:
{ctx["wt_stat"]}

Uncommitted diff (truncated):
{ctx["wt_diff"][:max_diff_chars]}

Return JSON only:
{{
  "branch_slug": "short kebab slug for branch, max 32 chars, no feat/ prefix",
  "issue": {{
    "title": "issue title, max 72 chars, feat/fix/chore prefix",
    "body": "markdown: ## Context, ## Proposed changes, ## Acceptance criteria"
  }},
  "commit": {{
    "message": "Conventional Commits one-liner, max 72 chars"
  }},
  "pr": {{
    "title": "PR title (match issue tone)",
    "summary": "2-4 bullet lines with - prefix",
    "test_plan": "markdown checklist, each line - [ ] ..."
  }}
}}

Rules:
- English only; be specific to the diff or new content files
- branch_slug, issue title, commit message, PR title should describe the SAME change consistently
- No code fences in JSON values
"""
    try:
        data = claude_json(prompt)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)[:240]}
    if not data:
        return {"ok": False, "error": "Claude returned no JSON"}

    branch_slug = str(data.get("branch_slug") or "").strip()
    issue_raw = data.get("issue") or {}
    commit_raw = data.get("commit") or {}
    pr_raw = data.get("pr") or {}

    issue_title = str(issue_raw.get("title") or "").strip()
    issue_body = str(issue_raw.get("body") or "").strip()
    commit_message = str(commit_raw.get("message") or "").strip()
    pr_title = str(pr_raw.get("title") or "").strip()
    pr_summary = str(pr_raw.get("summary") or "").strip()
    pr_test_plan = str(pr_raw.get("test_plan") or "").strip()

    if not issue_title:
        return {"ok": False, "error": "draft missing issue title"}
    if not commit_message:
        commit_message = issue_title
    if not pr_title:
        pr_title = issue_title
    if not pr_summary:
        pr_summary = issue_title

    pr_body = _pr_body(summary=pr_summary, issue_number=None, test_plan=pr_test_plan)

    return {
        "ok": True,
        "branch_slug": branch_slug,
        "issue": {"title": issue_title[:120], "body": issue_body},
        "commit": {"message": commit_message[:500]},
        "pr": {
            "title": pr_title[:120],
            "summary": pr_summary,
            "test_plan": pr_test_plan,
            "body": pr_body,
        },
        "branch": branch,
        "repo": slug,
    }


def ship_prepare(
    repo_path: Path,
    *,
    site_id: str = "",
    hint: str = "",
    base: str = DEFAULT_BASE,
    issue_number: int | None = None,
    skip_issue: bool = False,
) -> dict[str, Any]:
    """Issue → branch → commit → push → PR with one Claude draft. Skips completed steps."""
    from git_ops import (
        git_commit_only,
        git_create_branch,
        git_current_branch,
        git_push_only,
        git_status_detail,
        suggest_branch_name,
    )

    steps: list[dict[str, Any]] = []

    def _record(name: str, result: dict[str, Any], *, skipped: bool = False) -> dict[str, Any]:
        steps.append(
            {
                "name": name,
                "skipped": skipped,
                "ok": skipped or bool(result.get("ok")),
                "message": result.get("message") or result.get("error") or "",
                "detail": {k: v for k, v in result.items() if k not in ("ok", "error", "message")},
            }
        )
        return result

    draft = draft_ship_english(repo_path, site_id=site_id, hint=hint, base=base)
    if not draft.get("ok"):
        return {**draft, "steps": steps}

    issue_num = issue_number
    issue_url = ""
    if not skip_issue and issue_num is None:
        if not gh_available().get("logged_in"):
            return {"ok": False, "error": "gh not logged in", "steps": steps}
        issue = draft["issue"]
        created = create_issue(repo_path, title=issue["title"], body=issue.get("body") or "")
        _record("issue", created)
        if not created.get("ok"):
            return {"ok": False, "error": created.get("error") or "issue create failed", "steps": steps}
        issue_num = created.get("number")
        issue_url = created.get("url") or ""
    elif issue_num is not None:
        _record("issue", {"ok": True, "message": f"using issue #{issue_num}"}, skipped=True)
    else:
        _record("issue", {"ok": True, "message": "skipped"}, skipped=True)

    current = git_current_branch(repo_path)
    branch_name = current
    if current in PRODUCTION_BRANCHES:
        name = suggest_branch_name(
            issue_number=issue_num,
            issue_title=draft["issue"]["title"],
            hint=draft.get("branch_slug") or hint,
        )
        br = git_create_branch(repo_path, name, base=base)
        _record("branch", br)
        if not br.get("ok"):
            return {"ok": False, "error": br.get("error") or "branch failed", "steps": steps, "draft": draft}
        branch_name = br.get("branch") or name
    else:
        _record("branch", {"ok": True, "message": f"on {current}"}, skipped=True)

    status = git_status_detail(repo_path)
    if not status.get("ok"):
        return {"ok": False, "error": status.get("error") or "git status failed", "steps": steps}

    if status.get("dirty"):
        committed = git_commit_only(
            repo_path,
            site_id=site_id,
            message=draft["commit"]["message"],
        )
        _record("commit", committed)
        if not committed.get("ok"):
            return {"ok": False, "error": committed.get("error") or "commit failed", "steps": steps}
    else:
        _record("commit", {"ok": True, "message": "clean working tree"}, skipped=True)

    current = git_current_branch(repo_path)
    if current in PRODUCTION_BRANCHES:
        return {
            "ok": False,
            "error": "still on main after branch step",
            "steps": steps,
            "draft": draft,
        }

    pushed = git_push_only(repo_path, site_id=site_id)
    _record("push", pushed)
    if not pushed.get("ok"):
        return {"ok": False, "error": pushed.get("error") or "push failed", "steps": steps, "draft": draft}

    pr_info: dict[str, Any] | None = None
    if not gh_available().get("logged_in"):
        return {"ok": False, "error": "gh not logged in for PR", "steps": steps, "draft": draft}

    existing = pr_for_branch(repo_path, branch=current)
    if existing.get("pr"):
        pr_info = existing["pr"]
        _record("pr", {"ok": True, "message": f"PR #{pr_info.get('number')} exists", "url": pr_info.get("url")}, skipped=True)
    else:
        pr_d = draft["pr"]
        opened = create_pr(
            repo_path,
            title=pr_d["title"],
            body=pr_d.get("body"),
            summary=pr_d.get("summary") or "",
            issue_number=issue_num,
            test_plan=pr_d.get("test_plan") or "",
            base=base,
        )
        _record("pr", opened)
        if not opened.get("ok"):
            return {"ok": False, "error": opened.get("error") or "PR failed", "steps": steps, "draft": draft}
        pr_info = {"number": opened.get("number"), "url": opened.get("url"), "title": opened.get("title")}

    return {
        "ok": True,
        "drafted": True,
        "draft": draft,
        "steps": steps,
        "issue": {"number": issue_num, "url": issue_url} if issue_num else None,
        "branch": branch_name,
        "pr": pr_info,
        "message": f"PR #{pr_info.get('number')} ready — Review & merge" if pr_info else "Ship prep done",
    }


def create_issue(
    repo_path: Path,
    *,
    title: str,
    body: str = "",
) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    if not gh_available().get("logged_in"):
        return {"ok": False, "error": "gh not logged in"}
    args = ["issue", "create", "--title", title]
    if body.strip():
        args.extend(["--body", body.strip()])
    proc = _run_gh(repo_path, args)
    if proc.returncode != 0:
        return {"ok": False, "error": _gh_err(proc)}
    url = (proc.stdout or "").strip()
    num = None
    m = re.search(r"/issues/(\d+)", url)
    if m:
        num = int(m.group(1))
    return {"ok": True, "url": url, "number": num, "title": title}


def _pr_body(
    *,
    summary: str,
    issue_number: int | None = None,
    test_plan: str = "",
) -> str:
    issue_line = f"Closes #{issue_number}" if issue_number else "(none)"
    plan = (test_plan or "").strip() or "- [ ] Tests / manual check"
    return PR_BODY_TEMPLATE.format(
        summary=(summary or "").strip() or "- ",
        issue_line=issue_line,
        test_plan=plan,
    )


def create_pr(
    repo_path: Path,
    *,
    title: str,
    body: str | None = None,
    summary: str = "",
    issue_number: int | None = None,
    test_plan: str = "",
    base: str = DEFAULT_BASE,
    head: str | None = None,
) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    if not gh_available().get("logged_in"):
        return {"ok": False, "error": "gh not logged in"}
    head = (head or git_current_branch(repo_path)).strip()
    if head in PRODUCTION_BRANCHES:
        return {
            "ok": False,
            "error": f"create a feature branch first (currently on {head})",
        }
    pr_body = body if body is not None else _pr_body(
        summary=summary or title,
        issue_number=issue_number,
        test_plan=test_plan,
    )
    args = [
        "pr",
        "create",
        "--base",
        base,
        "--head",
        head,
        "--title",
        title,
        "--body",
        pr_body,
    ]
    proc = _run_gh(repo_path, args)
    if proc.returncode != 0:
        return {"ok": False, "error": _gh_err(proc)}
    url = (proc.stdout or "").strip()
    num = None
    m = re.search(r"/pull/(\d+)", url)
    if m:
        num = int(m.group(1))
    return {"ok": True, "url": url, "number": num, "title": title, "head": head, "base": base}


def pr_for_branch(repo_path: Path, *, branch: str | None = None) -> dict[str, Any]:
    """Open PR for branch, if any."""
    if not gh_available().get("logged_in"):
        return {"ok": False, "error": "gh not logged in", "pr": None}
    branch = (branch or git_current_branch(repo_path)).strip()
    if branch in PRODUCTION_BRANCHES:
        return {"ok": True, "pr": None, "branch": branch, "note": "on production branch"}
    proc = _run_gh(
        repo_path,
        [
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number,title,state,url,reviewDecision,mergeable,isDraft,baseRefName,headRefName",
            "--limit",
            "1",
        ],
    )
    if proc.returncode != 0:
        return {"ok": False, "error": _gh_err(proc), "pr": None, "branch": branch}
    rows = _parse_json(proc.stdout) or []
    pr = rows[0] if rows else None
    return {"ok": True, "pr": pr, "branch": branch}


def _local_pr_review(
    repo_path: Path,
    *,
    base: str = DEFAULT_BASE,
    max_diff_chars: int = 48000,
) -> dict[str, Any]:
    """Branch vs base diff when no open PR (local fallback)."""
    from git_ops import _run_git, git_current_branch, git_status_detail
    from git_util import git_summary

    branch = git_current_branch(repo_path)
    status = git_status_detail(repo_path)
    summary = git_summary(repo_path) or {}
    stat_proc = _run_git(repo_path, ["diff", "--stat", f"{base}...HEAD"], timeout=60)
    diff_proc = _run_git(repo_path, ["diff", f"{base}...HEAD"], timeout=90)
    stat = (stat_proc.stdout or "").strip() or "(no diff vs base)"
    diff = (diff_proc.stdout or "").strip()
    empty = not diff
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + f"\n… truncated ({len(diff)} chars)"
    ahead = int(summary.get("ahead") or 0)
    return {
        "source": "local",
        "branch": branch,
        "base": base,
        "stat": stat,
        "diff": diff or "(no diff vs base)",
        "empty": empty,
        "pr": None,
        "checks": {
            "has_open_pr": False,
            "mergeable": None,
            "uncommitted": bool(status.get("dirty")),
            "unpushed": ahead > 0,
            "ahead": ahead,
            "on_production_branch": branch in PRODUCTION_BRANCHES,
            "has_diff": not empty,
        },
    }


def _gh_diff_too_large(err: str) -> bool:
    low = (err or "").lower()
    return (
        "too_large" in low
        or "exceeded the maximum number of files" in low
        or "http 406" in low
        or "pullrequest.diff too_large" in low
    )


def pr_review(
    repo_path: Path,
    *,
    number: int | None = None,
    base: str = DEFAULT_BASE,
    max_diff_chars: int = 48000,
) -> dict[str, Any]:
    """Full PR diff + pre-merge checks for okadmin self-review."""
    from git_ops import git_status_detail
    from git_util import git_summary

    if not (repo_path / ".git").is_dir():
        return {"ok": False, "error": "no git repository"}

    status = git_status_detail(repo_path)
    if not status.get("ok"):
        return {"ok": False, "error": status.get("error") or "git status failed"}

    summary = git_summary(repo_path) or {}
    branch = git_current_branch(repo_path)
    ahead = int(summary.get("ahead") or 0)

    pr_data: dict[str, Any] | None = None
    if number is not None:
        if not gh_available().get("logged_in"):
            return {"ok": False, "error": "gh not logged in"}
        proc = _run_gh(
            repo_path,
            [
                "pr",
                "view",
                str(int(number)),
                "--json",
                "number,title,state,url,mergeable,isDraft,baseRefName,headRefName,additions,deletions,changedFiles",
            ],
        )
        if proc.returncode != 0:
            return {"ok": False, "error": _gh_err(proc)}
        rows = _parse_json(proc.stdout) or {}
        pr_data = rows if isinstance(rows, dict) else None
    elif branch not in PRODUCTION_BRANCHES:
        listed = pr_for_branch(repo_path, branch=branch)
        if not listed.get("ok"):
            return {"ok": False, "error": listed.get("error") or "PR lookup failed"}
        pr_data = listed.get("pr")

    if not pr_data:
        local = _local_pr_review(repo_path, base=base, max_diff_chars=max_diff_chars)
        blockers: list[str] = []
        if local["checks"]["uncommitted"]:
            blockers.append("uncommitted changes — Commit (EN) first")
        if local["checks"]["unpushed"]:
            blockers.append(f"{local['checks']['ahead']} unpushed commit(s) — Push first")
        if not local["checks"]["has_open_pr"]:
            blockers.append("no open PR — Push then Open PR (EN)")
        if local["empty"] and not local["checks"]["uncommitted"]:
            blockers.append("no diff vs base")
        if branch in PRODUCTION_BRANCHES:
            return {
                "ok": False,
                "error": "on main — nothing to merge; use a feature branch + PR",
                "branch": branch,
                "checks": local["checks"],
                "blockers": blockers,
                "can_merge": False,
            }
        if local["empty"] and not local["checks"]["uncommitted"]:
            return {
                "ok": False,
                "error": "no changes vs base — commit and push first",
                "branch": branch,
                "checks": local["checks"],
                "blockers": blockers,
                "can_merge": False,
            }
        return {
            "ok": True,
            **local,
            "blockers": blockers,
            "can_merge": False,
        }

    if not gh_available().get("logged_in"):
        return {"ok": False, "error": "gh not logged in"}

    pr_num = int(pr_data["number"])
    warnings: list[str] = []
    diff_proc = _run_gh(repo_path, ["pr", "diff", str(pr_num)], timeout=120)
    if diff_proc.returncode != 0:
        err = _gh_err(diff_proc)
        if not _gh_diff_too_large(err):
            return {"ok": False, "error": err}
        # GitHub caps PR unified diffs at 300 files — fall back to local git.
        local = _local_pr_review(
            repo_path,
            base=str(pr_data.get("baseRefName") or base),
            max_diff_chars=max_diff_chars,
        )
        diff = (local.get("diff") or "").strip()
        empty = bool(local.get("empty"))
        warnings.append(
            "GitHub PR diff too large (>300 files). Showing truncated local diff — "
            "open GitHub Files for the full list."
        )
        source = "github+local"
    else:
        diff = (diff_proc.stdout or "").strip()
        empty = not diff
        source = "github"
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + f"\n… truncated ({len(diff)} chars)"

    changed = pr_data.get("changedFiles")
    additions = pr_data.get("additions")
    deletions = pr_data.get("deletions")
    if changed is not None:
        stat = f"{changed} files changed"
        if additions is not None and deletions is not None:
            stat += f", {additions} insertions(+), {deletions} deletions(-)"
    else:
        stat_proc = _run_gh(repo_path, ["pr", "diff", str(pr_num), "--stat"], timeout=60)
        if stat_proc.returncode == 0:
            stat = (stat_proc.stdout or "").strip() or "(stat unavailable)"
        else:
            local_stat = _local_pr_review(
                repo_path,
                base=str(pr_data.get("baseRefName") or base),
                max_diff_chars=max_diff_chars,
            )
            stat = local_stat.get("stat") or "(stat unavailable)"

    if warnings and diff:
        diff = "# " + warnings[0] + "\n\n" + diff

    mergeable = pr_data.get("mergeable")
    has_files = bool(changed and int(changed) > 0)
    checks = {
        "has_open_pr": True,
        "mergeable": mergeable,
        "uncommitted": bool(status.get("dirty")),
        "unpushed": ahead > 0,
        "ahead": ahead,
        "on_production_branch": branch in PRODUCTION_BRANCHES,
        "has_diff": (not empty) or has_files,
        "diff_truncated": bool(warnings),
    }
    blockers = []
    if checks["uncommitted"]:
        blockers.append("uncommitted changes — Commit (EN) first")
    if checks["unpushed"]:
        blockers.append(f"{ahead} unpushed commit(s) — Push first")
    if mergeable is False:
        blockers.append("merge conflict — resolve on GitHub")
    if empty and not has_files:
        blockers.append("PR diff is empty")

    return {
        "ok": True,
        "source": source,
        "branch": branch,
        "base": pr_data.get("baseRefName") or base,
        "stat": stat,
        "diff": diff or "(empty diff — open GitHub Files for large PRs)",
        "empty": empty and not has_files,
        "pr": pr_data,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "can_merge": not blockers and mergeable is not False,
    }


def merge_pr(
    repo_path: Path,
    *,
    number: int | None = None,
    squash: bool = True,
    delete_branch: bool = True,
) -> dict[str, Any]:
    if not gh_available().get("logged_in"):
        return {"ok": False, "error": "gh not logged in"}
    args = ["pr", "merge"]
    if number is not None:
        args.append(str(int(number)))
    if squash:
        args.append("--squash")
    if delete_branch:
        args.append("--delete-branch")
    proc = _run_gh(repo_path, args)
    if proc.returncode != 0:
        return {"ok": False, "error": _gh_err(proc)}
    return {"ok": True, "message": (proc.stdout or "merged").strip(), "number": number}
