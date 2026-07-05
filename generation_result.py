"""Structured generation result marker for pipeline subprocess steps."""
from __future__ import annotations

import json
import sys
from typing import Any

MARKER = "__OKADMIN_GENERATION_RESULT__"


def emit_generation_result(
    *,
    step: str = "",
    topics: int = 0,
    generated: int = 0,
    failed: int = 0,
    skipped: int = 0,
    ok: bool = True,
) -> None:
    payload: dict[str, Any] = {
        "step": step,
        "topics": int(topics),
        "generated": int(generated),
        "failed": int(failed),
        "skipped": int(skipped),
        "ok": bool(ok),
    }
    print(f"{MARKER}{json.dumps(payload, ensure_ascii=False)}", flush=True)


def parse_generation_results(text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        idx = line.find(MARKER)
        if idx < 0:
            continue
        try:
            results.append(json.loads(line[idx + len(MARKER) :]))
        except json.JSONDecodeError:
            continue
    return results


def last_generation_result(text: str) -> dict[str, Any] | None:
    results = parse_generation_results(text)
    return results[-1] if results else None


def try_emit(**kwargs: Any) -> None:
    """Best-effort emit (generators may run outside Hub)."""
    try:
        emit_generation_result(**kwargs)
    except Exception:
        pass
