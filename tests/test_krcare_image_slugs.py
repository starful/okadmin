"""KR Care: one image per clinic base_id; MD is multi-lang."""

from pathlib import Path

from image_site_content import iter_content_slugs
from image_site_meta import (
    _korean_name_from_title,
    _krcare_places_queries,
    _localized_base_id,
    enrich_site_image_rows,
)


def test_iter_content_slugs_krcare_strips_lang_suffixes(tmp_path: Path):
    repo = tmp_path / "krcare"
    content = repo / "app/content"
    content.mkdir(parents=True)
    (content / "mdcl_100_en.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (content / "mdcl_100_ja.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (content / "mdcl_100_zh.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (content / "mdcl_100_zh_tw.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (content / "mdcl_200_en.md").write_text("---\ntitle: y\n---\n", encoding="utf-8")

    assert iter_content_slugs("krcare", repo) == {"mdcl_100", "mdcl_200"}


def test_localized_base_id_krcare_langs():
    assert _localized_base_id("mdcl_99_en") == "mdcl_99"
    assert _localized_base_id("mdcl_99_ja") == "mdcl_99"
    assert _localized_base_id("mdcl_99_zh") == "mdcl_99"
    assert _localized_base_id("mdcl_99_zh_tw") == "mdcl_99"


def test_enrich_krcare_name_from_md(tmp_path: Path, monkeypatch):
    repo = tmp_path / "krcare"
    content = repo / "app/content"
    content.mkdir(parents=True)
    (content / "mdcl_100_en.md").write_text(
        "---\ntitle: Test Clinic (테스트병원)\naddress: 1 Main St\n---\n",
        encoding="utf-8",
    )
    (content / "mdcl_100_ja.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")

    monkeypatch.setattr(
        "image_site_meta._content_dir",
        lambda _svc, _subdir="app/content": content,
    )

    row = {"slug": "mdcl_100", "filename": "mdcl_100.jpg", "name": "", "address": ""}
    out = enrich_site_image_rows("krcare", [row])[0]
    assert out["name"] == "Test Clinic (테스트병원)"
    assert out["address"] == "1 Main St"


def test_korean_name_from_title():
    assert _korean_name_from_title("Frientrip Co., Ltd. (주식회사 프렌트립)") == "주식회사 프렌트립"
    assert _korean_name_from_title("Kosin University Gospel Hospital (고신대학교복음병원)") == "고신대학교복음병원"


def test_krcare_places_queries_prefers_korean_name():
    queries = _krcare_places_queries(
        "Frientrip Co., Ltd. (주식회사 프렌트립)",
        "Seoul, Gangnam",
    )
    assert queries[0] == "주식회사 프렌트립"
    assert "주식회사 프렌트립 병원" in queries


def test_list_default_image_options_krcare(tmp_path: Path, monkeypatch):
    from image_site_content import list_default_image_options

    repo = tmp_path / "krcare"
    images = repo / "app/static/images"
    images.mkdir(parents=True)
    (images / "default.jpg").write_bytes(b"jpeg")
    (images / "tourapi_clinic.jpg").write_bytes(b"jpeg2")
    (images / "clinic_myeongdong_jw.jpg").write_bytes(b"jpeg3")

    monkeypatch.setattr(
        "image_site_content._repo_for_site",
        lambda _key: repo,
    )

    opts = list_default_image_options("krcare")
    names = [o["name"] for o in opts]
    assert "default.jpg" in names
    assert "tourapi_clinic.jpg" in names
    assert "clinic_myeongdong_jw.jpg" in names
