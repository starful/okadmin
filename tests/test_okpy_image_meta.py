"""OKPy: GCS cover basename ↔ post MD (starful-style meta)."""

from pathlib import Path

from image_site_meta import (
    _okpy_post_by_cover_stem,
    _okpy_post_resolve,
    okpy_cover_stems_from_repo,
    okpy_sync_cover_md,
    site_image_meta,
)


def test_okpy_cover_stems_from_repo(tmp_path: Path):
    repo = tmp_path / "okpy"
    posts = repo / "app/content/posts/python"
    posts.mkdir(parents=True)
    (posts / "marimo.md").write_text(
        "---\n"
        "title: Marimo Guide\ncategory: python\nslug: marimo\n"
        "cover: https://storage.googleapis.com/ok-project-assets/okpy/20260727064420.jpg\n"
        "---\n",
        encoding="utf-8",
    )

    assert okpy_cover_stems_from_repo(repo) == {"20260727064420"}


def test_okpy_post_by_cover_stem(tmp_path: Path):
    repo = tmp_path / "okpy"
    posts = repo / "app/content/posts/python"
    posts.mkdir(parents=True)
    (posts / "marimo.md").write_text(
        "---\n"
        "title: Marimo Guide\ncategory: python\nslug: marimo\n"
        "cover: https://storage.googleapis.com/ok-project-assets/okpy/20260727064420.jpg\n"
        "---\n",
        encoding="utf-8",
    )
    content_dir = repo / "app/content/posts"

    meta, path = _okpy_post_by_cover_stem(content_dir, "20260727064420")
    assert path and path.name == "marimo.md"
    assert meta.get("slug") == "marimo"


def test_site_image_meta_okpy(tmp_path: Path, monkeypatch):
    repo = tmp_path / "okpy"
    posts = repo / "app/content/posts/python"
    posts.mkdir(parents=True)
    (posts / "marimo.md").write_text(
        "---\n"
        "title: Marimo Guide\ncategory: python\nslug: marimo\n"
        "cover: https://storage.googleapis.com/ok-project-assets/okpy/20260727064420.jpg\n"
        "---\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("image_site_meta.WORK_ROOT", tmp_path)
    monkeypatch.setattr(
        "image_site_meta._content_dir",
        lambda _svc, subdir="app/content": repo / subdir,
    )

    meta = site_image_meta("okpy", "20260727064420")
    assert meta["ok"] is True
    assert meta["slug"] == "marimo"
    assert meta["upload_slug"] == "20260727064420"
    assert meta["name"] == "Marimo Guide"
    assert meta["uses_places"] is False
    assert meta["page_urls"]["ja"] == "https://okpy.net/blog/marimo"


def test_starful_uses_places_off():
    from image_site_meta import SITE_IMAGE_META

    assert SITE_IMAGE_META["starful_biz"]["uses_places"] is False


def test_okpy_post_resolve_by_article_slug(tmp_path: Path):
    repo = tmp_path / "okpy"
    posts = repo / "app/content/posts/terraform"
    posts.mkdir(parents=True)
    (posts / "terraform-state-and-remote-backend.md").write_text(
        "---\n"
        "title: Terraform State\ncategory: terraform\nslug: terraform-state-and-remote-backend\n"
        "cover: https://storage.googleapis.com/ok-project-assets/okpy/20260727064420.jpg\n"
        "---\n"
        "![cover](https://storage.googleapis.com/ok-project-assets/okpy/old-library.jpg)\n\n"
        "Body text.\n",
        encoding="utf-8",
    )
    content_dir = repo / "app/content/posts"

    meta, path = _okpy_post_resolve(content_dir, "terraform-state-and-remote-backend")
    assert path and path.name == "terraform-state-and-remote-backend.md"
    assert meta.get("slug") == "terraform-state-and-remote-backend"

    meta2, path2 = _okpy_post_by_cover_stem(content_dir, "20260727064420")
    assert path2 == path
    assert meta2.get("slug") == "terraform-state-and-remote-backend"


def test_okpy_sync_cover_md_updates_body(tmp_path: Path):
    from image_site_meta import okpy_sync_cover_md

    post = tmp_path / "post.md"
    old_url = "https://storage.googleapis.com/ok-project-assets/okpy/old-library.jpg"
    new_url = "https://storage.googleapis.com/ok-project-assets/okpy/posts/20260727064420.jpg"
    post.write_text(
        "---\n"
        f"title: Test\nslug: test\ncover: {old_url}\n"
        "---\n"
        f"![cover]({old_url})\n\n"
        "Body.\n",
        encoding="utf-8",
    )

    assert okpy_sync_cover_md(post, new_url) is True
    text = post.read_text(encoding="utf-8")
    canon = "https://storage.googleapis.com/ok-project-assets/okpy/20260727064420.jpg"
    assert canon in text
    assert old_url not in text
    assert "/okpy/posts/" not in text
    assert "![cover](" in text
