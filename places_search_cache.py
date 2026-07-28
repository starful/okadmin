"""In-memory TTL cache for Places searchText / searchNearby (image tab)."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_lock = threading.Lock()
_search_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_photo_cache: dict[str, tuple[float, bytes]] = {}

SEARCH_TTL_SEC = max(60, int(os.environ.get("PLACES_SEARCH_CACHE_TTL", str(24 * 3600))))
PHOTO_TTL_SEC = max(60, int(os.environ.get("PLACES_PHOTO_CACHE_TTL", str(7 * 24 * 3600))))
PHOTO_CACHE_MAX = max(100, int(os.environ.get("PLACES_PHOTO_CACHE_MAX", "500")))


def _search_key(site_id: str, slug: str) -> str:
    return f"{(site_id or '').strip()}:{(slug or '').strip()}"


def get_search_cache(site_id: str, slug: str) -> dict[str, Any] | None:
    key = _search_key(site_id, slug)
    now = time.time()
    with _lock:
        entry = _search_cache.get(key)
        if not entry:
            return None
        expires, payload = entry
        if now >= expires:
            _search_cache.pop(key, None)
            return None
        out = dict(payload)
        out["places_cache_hit"] = True
        return out


def set_search_cache(site_id: str, slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = _search_key(site_id, slug)
    store = dict(payload)
    store["places_cache_hit"] = False
    with _lock:
        _search_cache[key] = (time.time() + SEARCH_TTL_SEC, store)
    return store


def invalidate_search(site_id: str | None = None, slug: str | None = None) -> None:
    with _lock:
        if site_id and slug:
            _search_cache.pop(_search_key(site_id, slug), None)
        elif site_id:
            prefix = f"{site_id}:"
            for key in list(_search_cache):
                if key.startswith(prefix):
                    _search_cache.pop(key, None)
        else:
            _search_cache.clear()


def get_photo_cache(photo_ref: str) -> bytes | None:
    ref = (photo_ref or "").strip()
    if not ref:
        return None
    now = time.time()
    with _lock:
        entry = _photo_cache.get(ref)
        if not entry:
            return None
        expires, payload = entry
        if now >= expires:
            _photo_cache.pop(ref, None)
            return None
        return payload


def set_photo_cache(photo_ref: str, payload: bytes) -> None:
    ref = (photo_ref or "").strip()
    if not ref or not payload:
        return
    with _lock:
        if len(_photo_cache) >= PHOTO_CACHE_MAX:
            oldest = min(_photo_cache.items(), key=lambda x: x[1][0])[0]
            _photo_cache.pop(oldest, None)
        _photo_cache[ref] = (time.time() + PHOTO_TTL_SEC, payload)
