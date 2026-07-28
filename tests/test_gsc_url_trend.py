"""Tests for GSC URL history trend summary."""
from __future__ import annotations

from gsc_url_store import _trend_from_attempts


def test_trend_improving_ctr():
    attempts = [
        {"at": "2026-06-01 10:00:00", "pattern": "low_ctr", "ctr": 0.01, "position": 30, "impressions": 100},
        {"at": "2026-07-01 10:00:00", "pattern": "low_ctr", "ctr": 0.04, "position": 20, "impressions": 120},
    ]
    t = _trend_from_attempts(attempts)
    assert t["trend"] == "up"
    assert t["trend_arrow"] == "↑"
    assert "CTR" in t["tip"]


def test_trend_worsening():
    attempts = [
        {"at": "2026-06-01 10:00:00", "pattern": "low_ctr", "ctr": 0.05, "position": 12, "impressions": 200},
        {"at": "2026-07-01 10:00:00", "pattern": "low_ctr", "ctr": 0.01, "position": 35, "impressions": 180},
    ]
    t = _trend_from_attempts(attempts)
    assert t["trend"] == "down"
    assert t["trend_arrow"] == "↓"


def test_trend_single_attempt():
    attempts = [
        {"at": "2026-07-01 10:00:00", "pattern": "low_impression", "ctr": 0.0, "position": 40, "impressions": 5},
    ]
    t = _trend_from_attempts(attempts)
    assert t["trend_arrow"] == "→"
    assert t["trend_label"] == "1회"
