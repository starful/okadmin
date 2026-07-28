"""In-memory TTL cache for GCS image tab list API."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

TTL_SEC = max(15, int(os.environ.get("IMAGE_LIST_CACHE_TTL", "90")))


def get_cached(site_id: str) -> dict[str, Any] | None:
    now = time.time()
    with _lock:
        entry = _cache.get(site_id)
        if not entry:
            return None
        expires, payload = entry
        if now >= expires:
            _cache.pop(site_id, None)
            return None
        out = dict(payload)
        out["cache_hit"] = True
        return out


def set_cached(site_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store = dict(payload)
    store["cache_hit"] = False
    with _lock:
        _cache[site_id] = (time.time() + TTL_SEC, store)
    return store


def invalidate(site_id: str | None = None) -> None:
    with _lock:
        if site_id:
            _cache.pop(site_id, None)
        else:
            _cache.clear()
