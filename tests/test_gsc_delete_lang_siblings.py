"""Tests for SEO delete language sibling expansion."""
from __future__ import annotations

from gsc_seo_worker import expand_content_lang_siblings, lang_sibling_urls


def test_expand_en_ko_siblings(tmp_path):
    en = tmp_path / "foo_en.md"
    ko = tmp_path / "foo_ko.md"
    other = tmp_path / "bar_en.md"
    en.write_text("en")
    ko.write_text("ko")
    other.write_text("x")
    got = {p.name for p in expand_content_lang_siblings([en])}
    assert got == {"foo_en.md", "foo_ko.md"}
    assert "bar_en.md" not in got


def test_expand_bare_and_ja(tmp_path):
    en = tmp_path / "school.md"
    ja = tmp_path / "school_ja.md"
    en.write_text("en")
    ja.write_text("ja")
    got = {p.name for p in expand_content_lang_siblings([ja])}
    assert got == {"school.md", "school_ja.md"}


def test_lang_sibling_urls_path():
    urls = lang_sibling_urls("https://okramen.net/ramen/foo_en")
    assert "https://okramen.net/ramen/foo_en" in urls
    assert "https://okramen.net/ramen/foo_ko" in urls
