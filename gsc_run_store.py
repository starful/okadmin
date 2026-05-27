"""Persist GSC dashboard / SEO run timestamps per site (local data/gsc_logs)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import OKADMIN_ROOT

GSC_LOG_DIR = OKADMIN_ROOT / "data" / "gsc_logs"


def _status_path(site_id: str) -> Path:
    GSC_LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe = site_id.replace("/", "_")
    return GSC_LOG_DIR / f"{safe}.json"


def read_gsc_status(site_id: str) -> dict[str, Any]:
    path = _status_path(site_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _stamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _display(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso[:19]).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16] if iso else None


def write_gsc_dashboard_run(site_id: str, payload: dict[str, Any], *, ok: bool) -> None:
    data = read_gsc_status(site_id)
    data["dashboard"] = {
        "finished_at": _stamp(),
        "ok": ok,
        "ga4_error": (payload.get("ga4") or {}).get("error"),
        "gsc_error": (payload.get("gsc") or {}).get("error"),
        "low_ctr_count": (payload.get("gsc") or {}).get("low_ctr_count"),
    }
    _status_path(site_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_gsc_seo_run(site_id: str, result: dict[str, Any], *, ok: bool) -> None:
    data = read_gsc_status(site_id)
    results = result.get("results") or []
    applied = sum(1 for r in results if r.get("status") == "applied")
    data["seo"] = {
        "finished_at": _stamp(),
        "ok": ok,
        "count": len(results),
        "applied": applied,
        "error": result.get("error"),
    }
    _status_path(site_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def gsc_last_runs(site_id: str) -> dict[str, Any]:
    data = read_gsc_status(site_id)
    dash = data.get("dashboard") or {}
    seo = data.get("seo") or {}

    def _pack(block: dict[str, Any], prefix: str) -> dict[str, Any]:
        at = block.get("finished_at")
        return {
            f"last_{prefix}_at": at,
            f"last_{prefix}_display": _display(at),
            f"last_{prefix}_ok": block.get("ok"),
        }

    out: dict[str, Any] = {"site_id": site_id}
    out.update(_pack(dash, "dashboard"))
    out.update(_pack(seo, "seo"))

    latest_at = None
    latest_kind = None
    latest_ok = None
    for kind, block in (("dashboard", dash), ("seo", seo)):
        at = block.get("finished_at")
        if not at:
            continue
        if latest_at is None or at > latest_at:
            latest_at = at
            latest_kind = kind
            latest_ok = block.get("ok")

    out["last_run_at"] = latest_at
    out["last_run_display"] = _display(latest_at)
    out["last_run_ok"] = latest_ok
    out["last_run_kind"] = latest_kind
    return out
