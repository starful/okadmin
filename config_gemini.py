"""LLM readiness for okadmin.

Historically loaded GEMINI_API_KEY. Now uses Claude Code CLI (claude.ai subscription).
Kept module name for import compatibility.
"""
from __future__ import annotations

from llm_claude import claude_cli_ready, ensure_llm


def ensure_gemini_api_key() -> bool:
    """True if Claude CLI is logged in (subscription). Name kept for callers."""
    return ensure_llm()


def gemini_configured() -> bool:
    return claude_cli_ready()
