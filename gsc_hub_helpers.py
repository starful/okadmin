"""GSC SEO post-run helpers: calendar notes, commit message."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from config import get_service
from ops_calendar import record_ops_calendar_event

_OK_STATUSES = frozenset({"applied", "no_changes"})


def _pattern_label(pattern: str) -> str:
    return "저노출" if pattern == "low_impression" else "저CTR"


def _url_path(url: str) -> str:
    try:
        path = urlparse(url).path or url
    except Exception:
        path = url
    path = path.strip() or url
    return path[:40] + "..." if len(path) > 43 else path


def seo_calendar_notes(result: dict[str, Any]) -> str:
    results = result.get("results") or []
    lines: list[str] = []
    pattern = (results[0].get("pattern") if results else None) or "low_ctr"
    lines.append(f"패턴: {_pattern_label(pattern)}")
    applied = sum(1 for r in results if r.get("status") == "applied")
    suggested = sum(
        1 for r in results if r.get("status") in ("suggested", "suggested_no_file")
    )
    if applied:
        lines.append(f"MD 반영: {applied}건")
    if suggested:
        lines.append(f"제안만: {suggested}건")
    failed = sum(
        1 for r in results if r.get("status") in ("fetch_failed", "ai_failed")
    )
    if failed:
        lines.append(f"실패: {failed}건")
    lines.append("")
    for r in results[:20]:
        url = r.get("url") or ""
        st = r.get("status") or "?"
        summary = (r.get("summary_ko") or "").strip()
        line = f"- [{st}] {_url_path(url)}"
        if summary:
            line += f" — {summary[:120]}"
        lines.append(line)
    if len(results) > 20:
        lines.append(f"... 외 {len(results) - 20}건")
    return "\n".join(lines)[:2000]


def seo_commit_message(site_id: str, result: dict[str, Any]) -> str | None:
    results = result.get("results") or []
    if not results:
        return None
    pattern = results[0].get("pattern") or "low_ctr"
    pat = _pattern_label(pattern)
    n = len(results)
    paths = [_url_path(r.get("url") or "") for r in results[:4]]
    tail = ", ".join(p for p in paths if p)
    if n > 4:
        tail = f"{tail} +{n - 4}" if tail else f"+{n - 4}"
    applied = sum(1 for r in results if r.get("status") == "applied")
    mode = "MD" if applied else "제안"
    msg = f"seo(gsc): {site_id} · {pat} {n}건({mode})"
    if tail:
        msg += f" · {tail}"
    return msg[:200]


def record_gsc_seo_calendar(
    site_id: str, result: dict[str, Any]
) -> dict[str, Any] | None:
    results = result.get("results") or []
    if not results:
        return None
    svc = get_service(site_id)
    label = (svc or {}).get("label", site_id)
    pattern = results[0].get("pattern") or "low_ctr"
    pat = _pattern_label(pattern)
    n = len(results)
    any_ok = any(r.get("status") in _OK_STATUSES for r in results)
    if any_ok:
        title = f"✓ GSC SEO · {label} · {pat} {n}건"
    else:
        title = f"GSC SEO 실패 · {label} · {pat} {n}건"
    return record_ops_calendar_event(
        site_id=site_id,
        kind="gsc",
        title=title,
        notes=seo_calendar_notes(result),
    )
