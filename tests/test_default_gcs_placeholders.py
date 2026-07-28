"""Default GCS placeholder upload after content-only pipeline."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from image_site_content import (
    ensure_gcs_image_for_slug,
    iter_content_slugs,
    upload_default_gcs_placeholders,
)


def test_iter_content_slugs_okramen(tmp_path):
    repo = tmp_path / "okramen"
    content = repo / "app/content"
    content.mkdir(parents=True)
    (content / "foo_en.md").write_text("x")
    (content / "foo_ko.md").write_text("x")
    (content / "bar_ko.md").write_text("y")
    assert iter_content_slugs("okramen", repo) == {"foo", "bar"}


def test_ensure_gcs_skips_when_already_on_gcs(tmp_path):
    repo = tmp_path / "okramen"
    client = MagicMock()
    on_gcs = {"foo"}
    r = ensure_gcs_image_for_slug("okramen", "foo", repo, client=client, on_gcs=on_gcs)
    assert r["action"] == "skip"
    client.bucket.assert_not_called()


def test_ensure_gcs_uploads_default_when_missing(tmp_path):
    repo = tmp_path / "okramen"
    content = repo / "app/content"
    content.mkdir(parents=True)
    (content / "new_shop_ko.md").write_text("---\ntitle: x\n---\n")

    client = MagicMock()
    bucket = MagicMock()
    client.bucket.return_value = bucket
    blob = MagicMock()
    bucket.blob.return_value = blob

    prep = {
        "ok": True,
        "payload": b"jpeg-bytes",
        "content_type": "image/jpeg",
        "filename": "new_shop.jpg",
        "source": "app/static/images/default.jpg",
    }

    with patch("image_site_content._repo_for_site", return_value=repo), patch(
        "image_site_content.gcs_sites",
        return_value={"okramen": {"bucket": "b", "prefix": ""}},
    ), patch("image_site_content.get_default_image_payload", return_value=prep), patch(
        "image_site_meta.bump_site_thumbnail_cache", return_value={"ok": True}
    ), patch("image_site_content.sync_local_image", return_value="app/static/images/new_shop.jpg"):
        r = ensure_gcs_image_for_slug(
            "okramen", "new_shop", repo, client=client, on_gcs=set()
        )

    assert r["action"] == "uploaded_default"
    blob.upload_from_string.assert_called_once()


def test_pipeline_post_steps_default_when_images_off():
    from pipeline_runner import pipeline_post_steps

    env = {"CONTENT_PIPELINE_WITH_IMAGES": "0"}
    steps = pipeline_post_steps("okramen", env)
    assert [s[0] for s in steps] == ["default_gcs"]


def test_pipeline_post_steps_sync_then_default_when_images_on():
    from pipeline_runner import pipeline_post_steps

    env = {"CONTENT_PIPELINE_WITH_IMAGES": "1"}
    steps = pipeline_post_steps("okramen", env)
    assert [s[0] for s in steps] == ["gcs_images", "default_gcs"]


def test_build_image_coverage_marks_missing(tmp_path, monkeypatch):
    from image_site_content import build_image_coverage

    repo = tmp_path / "okramen"
    content = repo / "app/content"
    images = repo / "app/static/images"
    content.mkdir(parents=True)
    images.mkdir(parents=True)
    (content / "new_shop_ko.md").write_text("---\ntitle: x\n---\n")
    (content / "old_shop_ko.md").write_text("---\ntitle: y\n---\n")
    (images / "old_shop.jpg").write_bytes(b"custom-bytes-not-default")
    (images / "default.jpg").write_bytes(b"default-raw")

    monkeypatch.setattr("image_site_content._repo_for_site", lambda site_key: repo)
    monkeypatch.setattr(
        "image_site_content._optimize_default_payload",
        lambda site_key, raw: (raw, "image/jpeg"),
    )

    gcs_rows = [
        {
            "slug": "old_shop",
            "filename": "old_shop.jpg",
            "display_filename": "old_shop.jpg",
            "url": "https://example/old_shop.jpg",
            "size_kb": 1,
            "date_str": "2026-07-25",
            "updated_ts": 1,
        }
    ]
    rows, summary = build_image_coverage("okramen", gcs_rows)
    by = {r["slug"]: r for r in rows}
    assert by["new_shop"]["image_status"] == "missing"
    assert by["old_shop"]["image_status"] == "ok"
    assert summary["missing"] == 1
    assert summary["ok"] == 1
    assert summary["content"] == 2


def test_statfacts_default_source_prefers_branded_placeholder(tmp_path):
    from image_site_content import _default_source_path

    repo = tmp_path / "statfacts"
    images = repo / "app/static/images"
    images.mkdir(parents=True)
    (images / "default-annual-billing.jpg").write_bytes(b"x")
    path = _default_source_path("statfacts", "any-slug", repo)
    assert path is not None
    assert path.name == "default-annual-billing.jpg"

