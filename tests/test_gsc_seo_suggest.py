"""SEO Claude JSON helper — resilient parse + one retry (all sites)."""
from __future__ import annotations

import pytest

from gsc_seo_worker import _suggest_seo


def test_suggest_seo_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_json(_prompt, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return {
            "title": "New Title",
            "description": "New desc under 155.",
            "seo_title": "SEO Title",
            "seo_description": "SEO desc",
            "summary_ko": "테스트",
        }

    monkeypatch.setattr("llm_claude.claude_json", fake_json)
    out = _suggest_seo(
        None,
        site_id="jpcampus",
        url="https://jpcampus.net/guide/coe-denial",
        page={"title": "Old", "description": "Old d", "h1": "H"},
        gsc={"impressions": 10, "ctr": 0.01, "position": 12},
        pattern="low_ctr",
    )
    assert calls["n"] == 2
    assert out["title"] == "New Title"
    assert out["summary_ko"] == "테스트"


def test_suggest_seo_raises_after_retry_exhausted(monkeypatch):
    monkeypatch.setattr("llm_claude.claude_json", lambda *_a, **_k: None)
    with pytest.raises(RuntimeError, match="invalid JSON"):
        _suggest_seo(
            None,
            site_id="okramen",
            url="https://okramen.net/x",
            page={"title": "T", "description": "D", "h1": "H"},
            gsc={"impressions": 1, "ctr": 0.0, "position": 1},
        )


def test_suggest_seo_retries_runtime_error(monkeypatch):
    calls = {"n": 0}

    def fake_json(_prompt, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("session limit")
        return {
            "title": "T2",
            "description": "D2",
            "seo_title": "S2",
            "seo_description": "SD2",
            "summary_ko": "ok",
        }

    monkeypatch.setattr("llm_claude.claude_json", fake_json)
    out = _suggest_seo(
        None,
        site_id="krcare",
        url="https://krcare.net/item/x",
        page={"title": "Old", "description": "", "h1": ""},
        gsc={},
        pattern="low_impression",
    )
    assert calls["n"] == 2
    assert out["title"] == "T2"
