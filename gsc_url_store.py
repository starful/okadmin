"""Per-URL GSC SEO attempts and file deletions (local JSON)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import OKADMIN_ROOT

GSC_URL_HISTORY_DIR = OKADMIN_ROOT / "data" / "gsc_logs" / "url_history"


def _history_path(site_id: str) -> Path:
    GSC_URL_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", site_id)
    return GSC_URL_HISTORY_DIR / f"{safe}.json"


def read_url_history(site_id: str) -> dict[str, dict[str, Any]]:
    path = _history_path(site_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_url_history(site_id: str, data: dict[str, dict[str, Any]]) -> None:
    _history_path(site_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _stamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _display(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso[:19]).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16] if iso else None


def url_history_meta(site_id: str) -> dict[str, dict[str, Any]]:
    """URL → {seo_count, last_seo_at, last_seo_display, deleted_at, deleted_display, is_deleted}."""
    raw = read_url_history(site_id)
    out: dict[str, dict[str, Any]] = {}
    for url, block in raw.items():
        if not url or not isinstance(block, dict):
            continue
        attempts = block.get("seo_attempts") or []
        deleted_at = block.get("deleted_at")
        last = attempts[-1] if attempts else {}
        out[url] = {
            "seo_count": len(attempts),
            "last_seo_at": last.get("at"),
            "last_seo_display": _display(last.get("at")),
            "last_seo_status": last.get("status"),
            "deleted_at": deleted_at,
            "deleted_display": _display(deleted_at),
            "deleted_files": block.get("deleted_files") or [],
            "is_deleted": bool(deleted_at),
        }
    return out


def record_seo_attempts(site_id: str, results: list[dict[str, Any]]) -> None:
    if not results:
        return
    data = read_url_history(site_id)
    now = _stamp()
    for row in results:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        block = data.setdefault(url, {"seo_attempts": []})
        block.setdefault("seo_attempts", []).append(
            {
                "at": now,
                "status": row.get("status"),
                "pattern": row.get("pattern"),
                "impressions": row.get("impressions"),
                "ctr": row.get("ctr"),
                "position": row.get("position"),
            }
        )
        attempts = block["seo_attempts"]
        if len(attempts) > 30:
            block["seo_attempts"] = attempts[-30:]
    _write_url_history(site_id, data)


def record_url_deletion(
    site_id: str, url: str, *, deleted_files: list[str]
) -> None:
    url = url.strip()
    if not url:
        return
    data = read_url_history(site_id)
    block = data.setdefault(url, {"seo_attempts": []})
    block["deleted_at"] = _stamp()
    block["deleted_files"] = deleted_files
    _write_url_history(site_id, data)
