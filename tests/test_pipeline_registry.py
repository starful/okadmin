"""Tests for pipeline ensure modes and site registry."""
from pipeline_specs import RELEASE_QUEUE_SITES, SITE_ENSURE_MODE, ensure_mode


def test_release_sites_include_okstats_and_campus():
    assert "okstats" in RELEASE_QUEUE_SITES
    assert ensure_mode("okstats") == "release"
    assert ensure_mode("jpcampus") == "release"
    assert ensure_mode("starful.biz") == "release"
    assert ensure_mode("hatena") == "expand"
    assert "sync_only" not in SITE_ENSURE_MODE.values() or ensure_mode("hatena") != "sync_only"


def test_poi_in_release_queue():
    assert "okramen" in RELEASE_QUEUE_SITES
    assert "okcaddie" in RELEASE_QUEUE_SITES
    assert "jpcampus" not in RELEASE_QUEUE_SITES


def test_pipeline_for_site_unknown():
    from pathlib import Path

    from pipeline_site_registry import pipeline_for_site

    out = pipeline_for_site("unknown-site", Path("/tmp"), {})
    assert out.get("ok") is False
