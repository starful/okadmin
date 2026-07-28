"""Tests for soft SEO action advice hints."""
from __future__ import annotations

from gsc_url_store import SEO_ADVICE_DELETE_AFTER, seo_action_advice


def test_advice_seo_for_low_count():
    a0 = seo_action_advice(seo_count=0, trend="none", has_md=True)
    assert a0["advice"] == "seo"
    assert a0["advice_label"] == "SEO 추천"
    a2 = seo_action_advice(seo_count=2, trend="flat", has_md=True)
    assert a2["advice"] == "seo"


def test_advice_delete_review_after_threshold():
    assert SEO_ADVICE_DELETE_AFTER == 3
    a = seo_action_advice(seo_count=3, trend="flat", has_md=True)
    assert a["advice"] == "delete_review"
    assert a["advice_label"] == "삭제 검토"
    b = seo_action_advice(seo_count=5, trend="down", has_md=True)
    assert b["advice"] == "delete_review"


def test_advice_keep_when_improved():
    a = seo_action_advice(seo_count=3, trend="up", has_md=True)
    assert a["advice"] == "keep"
    assert a["advice_label"] == "유지"


def test_advice_empty_without_md_or_deleted():
    assert seo_action_advice(seo_count=0, has_md=False)["advice"] == ""
    assert seo_action_advice(seo_count=4, trend="flat", is_deleted=True)["advice"] == ""
