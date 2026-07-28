"""jpcampus image meta page_urls must match public routes (not everything → /stay/)."""
from __future__ import annotations

from pathlib import Path

from image_site_meta import _build_page_urls


def test_jpcampus_page_urls_by_kind(tmp_path: Path) -> None:
    content = tmp_path
    (content / "guide_linkedin-japan-usage.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    (content / "guide_linkedin-japan-usage_kr.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    (content / "stay_sakura_tsutsujigaoka.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    (content / "school_example.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    (content / "univ_example.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    base = "https://jpcampus.net"

    assert _build_page_urls("jpcampus", "guide_linkedin-japan-usage", content, base) == {
        "en": f"{base}/guide/linkedin-japan-usage",
        "kr": f"{base}/guide/linkedin-japan-usage?lang=kr",
    }
    assert _build_page_urls("jpcampus", "stay_sakura_tsutsujigaoka", content, base) == {
        "en": f"{base}/stay/sakura_tsutsujigaoka?lang=en",
    }
    (content / "stay_sakura_tsutsujigaoka_kr.md").write_text("---\ntitle: t\n---\n", encoding="utf-8")
    assert _build_page_urls("jpcampus", "stay_sakura_tsutsujigaoka", content, base)["kr"] == (
        f"{base}/stay/sakura_tsutsujigaoka?lang=kr"
    )
    assert _build_page_urls("jpcampus", "school_example", content, base) == {
        "en": f"{base}/school/school_example",
    }
    assert _build_page_urls("jpcampus", "univ_example", content, base) == {
        "en": f"{base}/school/univ_example",
    }
