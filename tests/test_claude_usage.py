"""Tests for Claude subscription usage shaping."""
from __future__ import annotations

from datetime import datetime, timezone

from claude_usage import format_resets_at, shape_usage_payload


def test_shape_usage_payload_windows():
    raw = {
        "five_hour": {
            "utilization": 42.5,
            "resets_at": "2026-07-25T17:30:00.000000+00:00",
        },
        "seven_day": {
            "utilization": 10,
            "resets_at": "2026-07-27T08:00:00.000000+00:00",
        },
        "seven_day_sonnet": None,
        "seven_day_opus": None,
        "extra_usage": {"is_enabled": False},
    }
    summary = shape_usage_payload(
        raw,
        subscription_type="pro",
        rate_limit_tier="default",
        source="live",
        note="test",
    )
    assert summary["ok"] is True
    assert summary["subscription_type"] == "pro"
    assert len(summary["windows"]) == 2
    five = summary["windows"][0]
    assert five["key"] == "five_hour"
    assert five["percent"] == 42.5
    assert five["remaining_percent"] == 57.5
    assert five["level"] == "ok"
    assert five["resets_local"]
    assert five["resets_in"]
    week = summary["windows"][1]
    assert week["key"] == "seven_day"
    assert week["percent"] == 10.0


def test_level_warn_and_over():
    raw = {
        "five_hour": {"utilization": 90, "resets_at": "2026-07-25T17:30:00+00:00"},
        "seven_day": {"utilization": 100, "resets_at": "2026-07-27T08:00:00+00:00"},
    }
    summary = shape_usage_payload(raw)
    assert summary["windows"][0]["level"] == "danger"
    assert summary["windows"][1]["level"] == "over"


def test_format_resets_at_remaining():
    now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
    info = format_resets_at("2026-07-25T14:30:00+00:00", now=now)
    assert info["seconds"] == 2 * 3600 + 30 * 60
    assert "2시간" in (info["in"] or "")
    assert info["local"]
    assert info.get("expired") is False


def test_format_resets_at_expired():
    now = datetime(2026, 7, 25, 18, 0, 0, tzinfo=timezone.utc)
    info = format_resets_at("2026-07-25T14:30:00+00:00", now=now)
    assert info["seconds"] == 0
    assert info["in"] == "리셋됨"
    assert info["expired"] is True


def test_refresh_summary_resets_marks_stale_percent():
    from claude_usage import refresh_summary_resets

    now = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
    summary = {
        "source": "stale_cache",
        "note": "rate limited",
        "windows": [
            {
                "key": "five_hour",
                "label": "5시간",
                "percent": 100.0,
                "resets_at": "2026-07-26T06:09:59+00:00",
                "resets_in": "53분",
            }
        ],
    }
    out = refresh_summary_resets(summary, now=now)
    w = out["windows"][0]
    assert w["resets_in"] == "리셋됨"
    assert w["percent_stale"] is True
    assert "리셋됨" in (out.get("note") or "")


def test_shape_empty_is_not_ok():
    summary = shape_usage_payload({}, error="no creds", note="no creds")
    assert summary["ok"] is False
    assert summary["windows"] == []
    assert summary["error"] == "no creds"


def test_attach_usage_summary_pipeline_ok():
    from claude_usage import attach_usage_summary

    summary = shape_usage_payload(
        {
            "five_hour": {"utilization": 42, "resets_at": "2026-07-27T08:00:00+00:00"},
            "seven_day": {"utilization": 10, "resets_at": "2026-07-27T08:00:00+00:00"},
        }
    )
    out = attach_usage_summary(summary)
    assert out["pipeline_ok"] is True
    assert "5시간" in out["headline"]
    assert out["worst_level"] == "ok"


def test_attach_usage_summary_blocks_at_85():
    from claude_usage import attach_usage_summary

    summary = shape_usage_payload(
        {"five_hour": {"utilization": 88, "resets_at": "2026-07-27T08:00:00+00:00"}}
    )
    out = attach_usage_summary(summary)
    assert out["pipeline_ok"] is False
    assert out["worst_level"] == "danger"
    assert "88%" in out["headline"]
