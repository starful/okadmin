from pipeline_specs import SITE_ENSURE_MODE, ensure_mode


def test_okpy_release_mode():
    assert ensure_mode("okpy") == "release"
    assert "hatena" not in SITE_ENSURE_MODE


def test_content_pipelines_has_okpy_not_hatena():
    from content_pipeline import CONTENT_PIPELINES, TRENDS_SEED_SITES

    assert "okpy" in CONTENT_PIPELINES
    assert "hatena" not in CONTENT_PIPELINES
    assert "okpy" in TRENDS_SEED_SITES
    assert "hatena" not in TRENDS_SEED_SITES
