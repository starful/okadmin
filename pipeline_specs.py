"""Site pipeline configuration: topic-bank ensure modes and POI site sets."""
from __future__ import annotations

from typing import Literal

EnsureMode = Literal["release", "sync_only", "expand"]

POI_SITES = frozenset({"okramen", "okonsen", "okcaddie"})

# Sites with standard content+guide release (insights/items + guides).
RELEASE_QUEUE_SITES = POI_SITES | frozenset({"okstats"})

# How ensure_csv prepares topic bank queues before generation.
SITE_ENSURE_MODE: dict[str, EnsureMode] = {
    "okramen": "release",
    "okonsen": "release",
    "okcaddie": "release",
    "okstats": "release",
    "starful.biz": "release",
    "jpcampus": "release",
    "krcampus": "release",
    "hatena": "expand",
}


def ensure_mode(site_id: str) -> EnsureMode | None:
    return SITE_ENSURE_MODE.get(site_id)
