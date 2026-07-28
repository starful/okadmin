"""GCS-only image delete (no MD)."""

from pathlib import Path
from unittest.mock import MagicMock

from image_site_content import delete_gcs_image


def test_delete_gcs_image_rejects_when_md_exists(tmp_path: Path, monkeypatch):
    repo = tmp_path / "krcare"
    content = repo / "app/content"
    content.mkdir(parents=True)
    (content / "mdcl_1_en.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")

    monkeypatch.setattr("image_site_content._repo_for_site", lambda _k: repo)
    monkeypatch.setattr(
        "image_site_content.list_content_md_paths",
        lambda _k, _s: ["krcare/app/content/mdcl_1_en.md"],
    )

    out = delete_gcs_image("krcare", "mdcl_1", client=MagicMock())
    assert out["ok"] is False
    assert "MD exists" in out["error"]


def test_delete_gcs_image_ok_without_md(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("image_site_content.list_content_md_paths", lambda _k, _s: [])
    monkeypatch.setattr(
        "image_site_content.delete_gcs_blobs",
        lambda *_a, **_k: ["images/tourapi_clinic.jpg"],
    )
    monkeypatch.setattr(
        "image_site_content.delete_local_image",
        lambda *_a, **_k: [],
    )

    out = delete_gcs_image("krcare", "tourapi_clinic", client=MagicMock())
    assert out["ok"] is True
    assert out["deleted_gcs"] == ["images/tourapi_clinic.jpg"]
