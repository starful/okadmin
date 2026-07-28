"""Tests for GCP Billing-backed ai_spend summary shaping."""
from __future__ import annotations

from ai_spend import (
    ALERT_KEYS,
    CATEGORY_KEYS,
    _budget_for,
    _build_summary_from_rows,
    spend_preflight,
)


def test_category_keys_include_banana():
    assert CATEGORY_KEYS == ("gemini", "imagen", "banana", "places", "total")
    assert ALERT_KEYS == ("gemini", "imagen", "banana", "places")


def test_default_alert_budget_yen(monkeypatch):
    for key in (
        "GEMINI_BUDGET_YEN", "IMAGEN_BUDGET_YEN", "BANANA_BUDGET_YEN",
        "PLACES_BUDGET_YEN", "TOTAL_BUDGET_YEN",
    ):
        monkeypatch.delenv(key, raising=False)
    assert _budget_for("gemini", "JPY") == 3000.0
    assert _budget_for("imagen", "JPY") == 3000.0
    assert _budget_for("banana", "JPY") == 3000.0
    assert _budget_for("places", "JPY") == 3000.0
    assert _budget_for("total", "JPY") == 0.0


def test_default_alert_budget_usd_from_yen(monkeypatch):
    monkeypatch.delenv("GEMINI_BUDGET_USD", raising=False)
    monkeypatch.delenv("GEMINI_BUDGET", raising=False)
    monkeypatch.delenv("GEMINI_BUDGET_YEN", raising=False)
    monkeypatch.setattr("ai_spend._USD_YEN_RATE", 150.0)
    assert _budget_for("gemini", "USD") == 20.0


def test_build_summary_splits_categories():
    month = "2026-07"
    rows = [
        {"kind": "gemini", "day": "2026-07-01", "cost": 1.25, "currency": "USD"},
        {"kind": "gemini", "day": "2026-07-02", "cost": 0.75, "currency": "USD"},
        {"kind": "imagen", "day": "2026-07-01", "cost": 0.4, "currency": "USD"},
        {"kind": "banana", "day": "2026-07-01", "cost": 1.5, "currency": "USD"},
        {"kind": "places", "day": "2026-07-01", "cost": 2.0, "currency": "USD"},
        {"kind": "other", "day": "2026-07-01", "cost": 0.15, "currency": "USD"},
    ]
    summary = _build_summary_from_rows(month, rows, note="test", table="proj.ds.t")
    assert summary["currency"] == "USD"
    assert summary["source"] == "gcp_billing"
    assert summary["categories"] == list(CATEGORY_KEYS)
    assert summary["gemini"]["cost"] == 2.0
    assert summary["imagen"]["cost"] == 0.4
    assert summary["banana"]["cost"] == 1.5
    assert summary["places"]["cost"] == 2.0
    assert summary["total"]["cost"] == 6.05
    assert summary["gemini"]["daily"][0]["cost"] == 1.25
    assert summary["gemini"]["daily"][1]["cost"] == 0.75


def test_alert_banner_on_over_budget(monkeypatch):
    monkeypatch.setenv("GEMINI_BUDGET_USD", "1")
    monkeypatch.setenv("IMAGEN_BUDGET_USD", "100")
    monkeypatch.setenv("BANANA_BUDGET_USD", "100")
    monkeypatch.setenv("PLACES_BUDGET_USD", "100")
    month = "2026-07"
    rows = [
        {"kind": "gemini", "day": "2026-07-01", "cost": 2.5, "currency": "USD"},
    ]
    summary = _build_summary_from_rows(month, rows, note="test", table="t")
    assert summary["over_budget"]["gemini"] is True
    assert "gemini" in summary["alert_over"]
    assert summary["alert_level"] == "over"
    assert "Gemini" in summary["alert_headline"]


def test_spend_preflight_never_blocks():
    pf = spend_preflight()
    assert pf["ok"] is True
    assert pf["block_gemini"] is False
    assert pf["block_imagen"] is False
