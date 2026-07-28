"""Day-keyed file cache for analytics overview (KST calendar day)."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import OKADMIN_ROOT

CACHE_DIR = OKADMIN_ROOT / "data" / "analytics_cache"
_lock = threading.Lock()

# Asia/Seoul without zoneinfo dependency quirks
_KST = timezone(timedelta(hours=9))

ALLOWED_DAYS = frozenset({1, 7, 28})
# Bump when overview payload shape changes (invalidate old day files)
CACHE_VERSION = 3

# GA4 API flakes (504 Deadline Exceeded, etc.) — do not treat as stable cache.
_TRANSIENT_ERROR_MARKERS = (
    "504",
    "503",
    "502",
    "429",
    "deadline exceeded",
    "timeout",
    "시간 초과",
    "temporarily unavailable",
    "connection reset",
    "unavailable",
    "resource exhausted",
)

GA4_PAYLOAD_KEYS = ("ga4", "ga4_channels", "ga4_devices", "ga4_events")


def is_transient_analytics_error(msg: str | None) -> bool:
    if not msg:
        return False
    low = str(msg).lower()
    return any(marker in low for marker in _TRANSIENT_ERROR_MARKERS)


def payload_has_transient_ga4_error(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in GA4_PAYLOAD_KEYS:
        block = payload.get(key)
        if isinstance(block, dict) and is_transient_analytics_error(block.get("error")):
            return True
    return False


def _block_is_usable(block: Any) -> bool:
    """True if a GA4/GSC block looks like real data (not a bare error)."""
    if not isinstance(block, dict):
        return False
    if block.get("error") and len(block) <= 2:
        return False
    return bool(block)


def merge_analytics_payload(
    base: dict[str, Any] | None,
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge a live fetch onto cache; keep prior good GA4 blocks over transient errors."""
    out = dict(base or {})
    for key, val in (update or {}).items():
        if key in ("cache_hit", "cached_at"):
            continue
        if key in GA4_PAYLOAD_KEYS and isinstance(val, dict):
            if is_transient_analytics_error(val.get("error")) and _block_is_usable(out.get(key)):
                continue
        out[key] = val
    if payload_has_transient_ga4_error(out):
        out["partial"] = True
    return out


def kst_today() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d")


def normalize_days(days: int) -> int:
    try:
        d = int(days)
    except (TypeError, ValueError):
        return 28
    if d in ALLOWED_DAYS:
        return d
    if d <= 1:
        return 1
    if d <= 7:
        return 7
    return 28


def _safe_site(site_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", (site_id or "").strip()) or "unknown"


def cache_path(site_id: str, days: int, *, day: str | None = None) -> Path:
    day = day or kst_today()
    days = normalize_days(days)
    return CACHE_DIR / f"{_safe_site(site_id)}_v{CACHE_VERSION}_d{days}_{day}.json"


def read_cache(site_id: str, days: int) -> dict[str, Any] | None:
    """Return today's cached payload (including partial / transient GA4 errors).

    Transient errors used to invalidate the whole day and force live re-fetch
    storms; we keep the file and mark partial so UI can show what we have.
    """
    path = cache_path(site_id, days)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("cache_day") != kst_today():
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    out = dict(payload)
    if payload_has_transient_ga4_error(out):
        out["partial"] = True
    out["cache_hit"] = True
    out["cache_day"] = data.get("cache_day")
    out["cached_at"] = data.get("cached_at")
    return out


def write_cache(site_id: str, days: int, payload: dict[str, Any]) -> dict[str, Any]:
    days = normalize_days(days)
    day = kst_today()
    path = cache_path(site_id, days, day=day)
    now = datetime.now(_KST).strftime("%Y-%m-%d %H:%M")
    store = dict(payload)
    if payload_has_transient_ga4_error(store):
        store["partial"] = True
    store["cache_hit"] = False
    store["cache_day"] = day
    store["cached_at"] = now
    meta = {
        "cache_day": day,
        "cached_at": now,
        "site_id": site_id,
        "days": days,
        "payload": store,
    }
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"cache_hit": False, "cache_day": day, "cached_at": now}


def pct_delta(current: float | int, prior: float | int) -> float | None:
    try:
        cur = float(current)
        prev = float(prior)
    except (TypeError, ValueError):
        return None
    if prev == 0:
        if cur == 0:
            return 0.0
        return None
    return round((cur - prev) / prev * 100.0, 1)


def deltas_for_totals(
    current: dict[str, Any] | None,
    prior: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> dict[str, float | None]:
    cur = current or {}
    prev = prior or {}
    return {k: pct_delta(cur.get(k) or 0, prev.get(k) or 0) for k in keys}
