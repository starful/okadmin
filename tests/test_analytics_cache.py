"""Day-keyed analytics cache helpers."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from analytics_cache import (
    deltas_for_totals,
    is_transient_analytics_error,
    kst_today,
    merge_analytics_payload,
    normalize_days,
    payload_has_transient_ga4_error,
    pct_delta,
    read_cache,
    write_cache,
)


def test_normalize_days_allowed():
    assert normalize_days(1) == 1
    assert normalize_days(7) == 7
    assert normalize_days(28) == 28


def test_normalize_days_clamps():
    assert normalize_days(90) == 28
    assert normalize_days(14) == 28
    assert normalize_days(3) == 7
    assert normalize_days(0) == 1
    assert normalize_days("nope") == 28
    assert normalize_days(None) == 28


def test_pct_delta():
    assert pct_delta(110, 100) == 10.0
    assert pct_delta(90, 100) == -10.0
    assert pct_delta(0, 0) == 0.0
    assert pct_delta(5, 0) is None


def test_deltas_for_totals():
    out = deltas_for_totals(
        {"sessions": 120, "users": 50},
        {"sessions": 100, "users": 100},
        ("sessions", "users", "events"),
    )
    assert out["sessions"] == 20.0
    assert out["users"] == -50.0
    assert out["events"] == 0.0  # both missing → 0/0


def test_write_read_roundtrip(tmp_path: Path):
    with patch("analytics_cache.CACHE_DIR", tmp_path):
        with patch("analytics_cache.kst_today", return_value="2026-07-20"):
            meta = write_cache(
                "okramen",
                28,
                {"site_id": "okramen", "days": 28, "ga4": {"totals": {"sessions": 1}}},
            )
            assert meta["cache_hit"] is False
            assert meta["cache_day"] == "2026-07-20"
            assert meta["cached_at"]

            hit = read_cache("okramen", 28)
            assert hit is not None
            assert hit["cache_hit"] is True
            assert hit["cache_day"] == "2026-07-20"
            assert hit["ga4"]["totals"]["sessions"] == 1
            assert hit["days"] == 28


def test_read_cache_expires_next_kst_day(tmp_path: Path):
    with patch("analytics_cache.CACHE_DIR", tmp_path):
        with patch("analytics_cache.kst_today", return_value="2026-07-20"):
            write_cache("okramen", 7, {"ok": True})
        with patch("analytics_cache.kst_today", return_value="2026-07-21"):
            assert read_cache("okramen", 7) is None


def test_transient_ga4_error_detection():
    assert is_transient_analytics_error("504 Deadline Exceeded")
    assert is_transient_analytics_error("503 Service Unavailable")
    assert is_transient_analytics_error("조회 시간 초과")
    assert not is_transient_analytics_error("GA4 권한 없음 (property)")
    payload = {
        "ga4": {"error": "504 Deadline Exceeded"},
        "ga4_channels": {"total_sessions": 10},
        "gsc_daily": {"rows": []},
    }
    assert payload_has_transient_ga4_error(payload)


def test_read_cache_keeps_transient_as_partial(tmp_path: Path):
    """Transient GA4 errors must not wipe the day cache (avoids live-fetch storms)."""
    with patch("analytics_cache.CACHE_DIR", tmp_path):
        with patch("analytics_cache.kst_today", return_value="2026-07-20"):
            write_cache(
                "okonsen",
                28,
                {
                    "site_id": "okonsen",
                    "days": 28,
                    "partial": False,
                    "ga4": {"error": "504 Deadline Exceeded"},
                    "ga4_channels": {"total_sessions": 127},
                },
            )
            hit = read_cache("okonsen", 28)
            assert hit is not None
            assert hit["partial"] is True
            assert hit["ga4_channels"]["total_sessions"] == 127
            assert hit["cache_hit"] is True


def test_merge_keeps_good_ga4_over_transient():
    base = {"ga4": {"totals": {"sessions": 9}}, "ga4_channels": {"total_sessions": 3}}
    update = {"ga4": {"error": "조회 시간 초과"}, "ga4_devices": {"rows": []}}
    merged = merge_analytics_payload(base, update)
    assert merged["ga4"]["totals"]["sessions"] == 9
    assert merged["ga4_devices"] == {"rows": []}
    assert not merged.get("partial")


def test_write_cache_marks_partial_on_transient_ga4(tmp_path: Path):
    with patch("analytics_cache.CACHE_DIR", tmp_path):
        with patch("analytics_cache.kst_today", return_value="2026-07-20"):
            write_cache(
                "okonsen",
                28,
                {
                    "site_id": "okonsen",
                    "days": 28,
                    "partial": False,
                    "ga4": {"error": "504 Deadline Exceeded"},
                },
            )
            raw = (tmp_path / "okonsen_v3_d28_2026-07-20.json").read_text(encoding="utf-8")
            assert '"partial": true' in raw


def test_kst_today_format():
    day = kst_today()
    assert len(day) == 10
    datetime.strptime(day, "%Y-%m-%d")
    # sanity: within a day of UTC+9 wall clock
    expect = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    assert day == expect
