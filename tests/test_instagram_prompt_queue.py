"""Tests for Instagram prompt queue."""
from __future__ import annotations

import instagram_prompt_queue as iq
from instagram_seed_data import build_seed_items


def test_seed_has_fifty_items_with_eight_slides(tmp_path, monkeypatch):
    monkeypatch.setattr(iq, "QUEUE_PATH", tmp_path / "queue.json")
    items = build_seed_items(batch=1)
    assert len(items) >= 50
    assert all(len(i["slides"]) == 8 for i in items)
    assert items[0]["id"] == "ig-01-001"
    assert all(i.get("cta_site") in {"okramen", "okonsen", "jpcampus", "okcaddie"} for i in items)


def test_ensure_queue_bootstraps_and_mark_done(tmp_path, monkeypatch):
    path = tmp_path / "queue.json"
    monkeypatch.setattr(iq, "QUEUE_PATH", path)
    data = iq.ensure_queue()
    n = len(build_seed_items(batch=1))
    assert path.is_file()
    assert len(data["items"]) == n
    assert iq.queue_stats(data)["todo"] == n

    item = iq.set_status("ig-01-001", "done")
    assert item is not None
    assert item["status"] == "done"
    assert item["done_at"]
    assert iq.queue_stats()["done"] == 1
    assert iq.queue_stats()["todo"] == n - 1

    restored = iq.set_status("ig-01-001", "todo")
    assert restored["status"] == "todo"
    assert restored["done_at"] is None


def test_format_gemini_prompt_contains_rules_and_slides():
    item = build_seed_items(1)[0]
    text = iq.format_gemini_prompt(item)
    assert "4:5" in text
    assert "1080" in text
    assert item["topic"] in text
    assert "[1장 표지]" in text
    assert "[7장 마무리]" in text
    assert "총 7장" in text
    assert "서로 달라야" in text
    assert "프로필 링크" in text
    assert "포인트" in text or "[2장]" in text


def test_format_gemini_prompt_no_site_url():
    item = build_seed_items(1)[0]
    text = iq.format_gemini_prompt(item, site_id="okramen")
    assert "https://okramen.net" not in text
    assert "4:5" in text
    assert "OK - JAPAN" in text
    assert "첨부" in text
    assert "프로필 링크" in text


def test_common_rules_profile_link_cta():
    from instagram_site_profiles import instagram_common_rules

    rules = instagram_common_rules()
    assert "https://okramen.net" not in rules
    assert "프로필 링크" in rules
    assert "4:5" in rules
    assert "OK - JAPAN" in rules


def test_infer_cta_site_by_topic():
    from instagram_site_profiles import infer_cta_site, profile_link_cta_line

    assert infer_cta_site(category="onsen", topic="온천 매너") == "okonsen"
    assert infer_cta_site(category="food", topic="라멘집 줄") == "okramen"
    assert infer_cta_site(category="transport", topic="Suica") == "jpcampus"
    assert "프로필 링크" in profile_link_cta_line("okramen")
    assert "🍜" in profile_link_cta_line("okramen")


def test_caption_includes_profile_link():
    item = build_seed_items(1)[4]  # onsen
    block = iq.format_caption_block(item)
    assert "프로필 링크" in block
    assert item["cta_site"] == "okonsen"


def test_instagram_enabled_sites_tourism_only():
    from instagram_site_profiles import INSTAGRAM_ENABLED_SITES, is_instagram_enabled

    assert INSTAGRAM_ENABLED_SITES == frozenset(
        {"okramen", "okonsen", "okcaddie", "jpcampus"}
    )
    assert is_instagram_enabled("okramen")
    assert is_instagram_enabled("jpcampus")
    assert not is_instagram_enabled("starful.biz")
    assert not is_instagram_enabled("statfacts")
    assert not is_instagram_enabled("")


def test_strip_slide_copy_removes_sentence_punctuation():
    from instagram_site_profiles import strip_slide_copy

    assert strip_slide_copy("많아요.") == "많아요"
    assert strip_slide_copy("첫 문장. 둘째 문장.") == "첫 문장 둘째 문장"
    assert strip_slide_copy("수수료·환율") == "수수료·환율"


def test_seed_slide_copy_has_no_trailing_periods():
    from instagram_site_profiles import strip_slide_copy

    for item in build_seed_items(batch=1):
        for slide in item["slides"]:
            title = slide["title"]
            body = slide["body"]
            assert title == strip_slide_copy(title)
            assert body == strip_slide_copy(body)
            assert not title.endswith(".")
            assert not body.endswith(".")


def test_format_gemini_prompt_slide_copy_has_no_periods():
    item = build_seed_items(1)[0]
    text = iq.format_gemini_prompt(item)
    for line in text.splitlines():
        if line.startswith(("제목:", "부제:", "본문:", "CTA:")):
            copy = line.split(":", 1)[1].strip()
            assert not copy.endswith("."), line


def test_todo_items_have_unique_slide_art(tmp_path, monkeypatch):
    monkeypatch.setattr(iq, "QUEUE_PATH", tmp_path / "queue.json")
    iq.ensure_queue()
    for item in iq.list_items(status="todo"):
        arts = [s.get("art") or "" for s in item.get("slides") or []]
        assert len(arts) == 8
        assert len(set(arts)) == 8, item["id"]


def test_list_filter_status(tmp_path, monkeypatch):
    monkeypatch.setattr(iq, "QUEUE_PATH", tmp_path / "queue.json")
    iq.ensure_queue()
    iq.set_status("ig-01-002", "done")
    todo = iq.list_items(status="todo")
    done = iq.list_items(status="done")
    assert all(i["status"] != "done" for i in todo)
    assert len(done) == 1
    assert done[0]["id"] == "ig-01-002"


def test_shared_queue_ignores_site_id(tmp_path, monkeypatch):
    path = tmp_path / "queue.json"
    monkeypatch.setattr(iq, "QUEUE_PATH", path)
    monkeypatch.setattr(iq, "QUEUE_DIR", tmp_path)
    data = iq.ensure_queue("okramen")
    assert path.is_file()
    assert not (tmp_path / "okramen.json").is_file()
    assert data["site_id"] is None
    rules = data.get("common_rules") or ""
    assert "프로필 링크" in rules
    assert "https://okramen.net" not in rules
