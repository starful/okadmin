"""Claude Code CLI (claude.ai Pro/Max subscription) — replaces Gemini API for okadmin LLM calls.

Uses local `claude -p` so usage stays on the Claude subscription, not Anthropic API billing.
Do not set ANTHROPIC_API_KEY for this path unless you intentionally want API billing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def claude_bin() -> str:
    env = (os.environ.get("CLAUDE_BIN") or "").strip()
    if env and Path(env).is_file():
        return env
    for candidate in (
        "/opt/work/node_modules/.bin/claude",
        "/opt/work/.paperclip-tools/bin/claude",
        shutil.which("claude") or "",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return "claude"


def claude_cli_ready() -> bool:
    """True if Claude CLI reports logged-in (subscription)."""
    try:
        proc = subprocess.run(
            [claude_bin(), "auth", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ},
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    out = (proc.stdout or "") + (proc.stderr or "")
    if '"loggedIn": true' in out or '"loggedIn":true' in out:
        return True
    # Older CLI may print plain text
    return "logged in" in out.lower() and "not logged" not in out.lower()


def ensure_llm() -> bool:
    return claude_cli_ready()


# Backward-compatible name used across topic/GSC modules
def ensure_gemini_api_key() -> bool:
    """Deprecated name: now means Claude CLI subscription is ready."""
    return ensure_llm()


def claude_text(prompt: str, *, timeout_sec: int | None = None) -> str | None:
    """Non-interactive Claude Code prompt; returns plain text or None."""
    timeout = timeout_sec or int(os.environ.get("CLAUDE_TIMEOUT_SEC", "180"))
    # Disable agent tools so -p stays a pure text completion (no Write/permission chatter).
    cmd = [
        claude_bin(),
        "-p",
        "--output-format",
        "text",
        "--disallowedTools",
        "Write,Edit,MultiEdit,NotebookEdit,Bash,Read,Glob,Grep,Agent,TodoWrite",
        "--append-system-prompt",
        (
            "You are a pure text generator. Reply ONLY with the requested content. "
            "Never use tools, never ask for permission, never mention files or Write."
        ),
        prompt,
    ]
    # Prefer subscription OAuth; avoid --bare (skips keychain login).
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    blob = f"{text}\n{err}".strip()
    # Surface quota / auth failures instead of treating them as empty success.
    low = blob.lower()
    if "session limit" in low or "rate limit" in low or "usage limit" in low:
        raise RuntimeError(blob.splitlines()[0][:240] if blob else "Claude session limit")
    if proc.returncode != 0 and not text:
        if err:
            raise RuntimeError(err.splitlines()[0][:240])
        return None
    if not text:
        return None
    # Strip accidental code fences if model wraps anyway
    if text.startswith("```"):
        text = re.sub(r"^```(?:\w+)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip() or None


def claude_json(prompt: str, *, timeout_sec: int | None = None) -> dict[str, Any] | None:
    text = claude_text(prompt, timeout_sec=timeout_sec)
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


@dataclass
class _ClaudeResponse:
    text: str


class ClaudeModel:
    """Drop-in for google.generativeai GenerativeModel.generate_content."""

    def generate_content(self, prompt: str) -> _ClaudeResponse:
        try:
            text = claude_text(prompt) or ""
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc
        return _ClaudeResponse(text=text)


def claude_model() -> tuple[ClaudeModel | None, str | None]:
    if not ensure_llm():
        return None, (
            "Claude CLI 미로그인 — 터미널에서 `claude` 실행 후 /login "
            f"(bin={claude_bin()})"
        )
    return ClaudeModel(), None
