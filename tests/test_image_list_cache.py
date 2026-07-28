"""Image list cache and enrich index tests."""

import time
from pathlib import Path
from unittest.mock import MagicMock

from image_list_cache import get_cached, invalidate, set_cached
from image_site_meta import enrich_site_image_rows, okpy_posts_by_cover_stem


def test_image_list_cache_roundtrip():
    invalidate()
    assert get_cached("okpy") is None
    payload = set_cached("okpy", {"ok": True, "images": [], "summary": {}})
    assert payload["cache_hit"] is False
    hit = get_cached("okpy")
    assert hit and hit["cache_hit"] is True
    invalidate("okpy")
    assert get_cached("okpy") is None


def test_image_list_cache_expires(monkeypatch):
    invalidate()
    times = iter([1000.0, 1030.0, 1100.0])
    monkeypatch.setattr("image_list_cache.time.time", lambda: next(times))
    monkeypatch.setattr("image_list_cache.TTL_SEC", 60)
    set_cached("statfacts", {"ok": True, "images": []})
    assert get_cached("statfacts") is not None
    assert get_cached("statfacts") is None


def test_okpy_posts_by_cover_stem_index(tmp_path: Path):
    repo = tmp_path / "okpy"
    posts = repo / "app/content/posts/python"
    posts.mkdir(parents=True)
    (posts / "marimo.md").write_text(
        "---\n"
        "title: Marimo Guide\nslug: marimo\n"
        "cover: https://storage.googleapis.com/ok-project-assets/okpy/20260727064420.jpg\n"
        "---\n",
        encoding="utf-8",
    )
    content_dir = repo / "app/content/posts"
    idx = okpy_posts_by_cover_stem(content_dir)
    assert idx["20260727064420"]["slug"] == "marimo"


def test_enrich_okpy_uses_index(tmp_path: Path, monkeypatch):
    repo = tmp_path / "okpy"
    posts = repo / "app/content/posts/python"
    posts.mkdir(parents=True)
    (posts / "marimo.md").write_text(
        "---\n"
        "title: Marimo Guide\nslug: marimo\n"
        "cover: https://storage.googleapis.com/ok-project-assets/okpy/20260727064420.jpg\n"
        "---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("image_site_meta.WORK_ROOT", tmp_path)
    monkeypatch.setattr(
        "image_site_meta._content_dir",
        lambda _svc, subdir="app/content": repo / subdir,
    )
    rows = [{"slug": "20260727064420", "url": "https://example/x.jpg"}]
    out = enrich_site_image_rows("okpy", rows)
    assert out[0]["name"] == "Marimo Guide"


def test_build_site_image_list_fast(monkeypatch):
    from datetime import datetime, timezone

    from image_site_content import build_site_image_list

    class _Blob:
        def __init__(self, name: str):
            self.name = name
            self.size = 1024
            self.updated = datetime(2026, 7, 27, tzinfo=timezone.utc)

    client = MagicMock()
    client.list_blobs.return_value = [
        _Blob("okpy/a.jpg"),
    ]
    monkeypatch.setattr(
        "image_site_content.gcs_sites",
        lambda: {"okpy": {"bucket": "b", "prefix": "okpy/"}},
    )
    monkeypatch.setattr(
        "image_site_content.build_image_coverage",
        lambda site_id, rows, **kw: (rows, {"content": 0, "missing": 0, "default": 0, "ok": 1, "gcs_only": 0}),
    )
    monkeypatch.setattr("image_site_content.work_root_available", lambda: False)
    out = build_site_image_list("okpy", client, fast_list=True)
    assert out["ok"] is True
    assert len(out["images"]) == 1


def test_okpy_dedupe_posts_prefix(monkeypatch):
    from datetime import datetime, timezone

    from image_site_content import _dedupe_gcs_image_rows, okpy_canonical_gcs_filename

    assert okpy_canonical_gcs_filename("posts/2026072521492702.jpg") == "2026072521492702.jpg"

    root = {
        "filename": "2026072521492702.jpg",
        "slug": "2026072521492702",
        "updated_ts": 100.0,
        "url": "https://storage.googleapis.com/b/okpy/2026072521492702.jpg",
    }
    nested = {
        "filename": "posts/2026072521492702.jpg",
        "slug": "2026072521492702",
        "updated_ts": 200.0,
        "url": "https://storage.googleapis.com/b/okpy/posts/2026072521492702.jpg",
    }
    out = _dedupe_gcs_image_rows(
        "okpy",
        [root, nested],
        bucket_name="b",
        prefix="okpy/",
    )
    assert len(out) == 1
    assert out[0]["slug"] == "2026072521492702"
    assert out[0]["filename"] == "posts/2026072521492702.jpg"

    out2 = _dedupe_gcs_image_rows(
        "okpy",
        [nested, root],
        bucket_name="b",
        prefix="okpy/",
    )
    assert out2[0]["filename"] == "posts/2026072521492702.jpg"


def test_okpy_canonical_cover_url():
    from image_site_meta import okpy_canonical_cover_url

    url = "https://storage.googleapis.com/ok-project-assets/okpy/posts/foo.jpg?v=1"
    assert okpy_canonical_cover_url(url) == "https://storage.googleapis.com/ok-project-assets/okpy/foo.jpg"
