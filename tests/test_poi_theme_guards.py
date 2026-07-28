"""Prevent cross-site theme seed contamination for POI sites."""

from __future__ import annotations

from content_pipeline import (
    DEFAULT_GUIDE_SEEDS,
    DEFAULT_ITEM_SEEDS,
    EXPAND_GUIDE_SEEDS,
    POI_EXPAND_SEEDS,
    poi_guide_seeds,
)
from poi_topic_ai import _parse_guide_row, _row_off_theme
from topic_bank_seeds import expand_pool_for_site, seeds_for_site


def test_shared_cafe_seed_pools_stay_empty():
    assert DEFAULT_ITEM_SEEDS == []
    assert POI_EXPAND_SEEDS == []
    assert DEFAULT_GUIDE_SEEDS == []
    assert EXPAND_GUIDE_SEEDS == []


def test_poi_expand_pool_has_no_items_from_shared_cafe():
    for site in ("okramen", "okonsen", "okcaddie"):
        assert expand_pool_for_site(site).get("items") == []


def test_poi_guide_seeds_are_site_specific():
    ramen = {r["id"] for r in poi_guide_seeds("okramen")}
    onsen = {r["id"] for r in poi_guide_seeds("okonsen")}
    caddie = {r["id"] for r in poi_guide_seeds("okcaddie")}
    assert ramen and onsen and caddie
    assert ramen.isdisjoint(onsen)
    assert ramen.isdisjoint(caddie)
    assert onsen.isdisjoint(caddie)
    for site in ("okramen", "okonsen", "okcaddie"):
        for row in seeds_for_site(site)["guides"] + expand_pool_for_site(site)["guides"]:
            blob = f"{row.get('topic_en','')} {row.get('keywords','')} {row.get('topic_ko','')}".lower()
            if site == "okramen":
                assert "ramen" in blob or "라멘" in blob or "라면" in blob
            elif site == "okonsen":
                assert any(x in blob for x in ("onsen", "ryokan", "온천", "료칸", "rotenburo"))
            else:
                assert any(x in blob for x in ("golf", "caddie", "caddy", "골프", "코스", "course"))


def test_poi_seed_items_are_on_theme():
    assert _row_off_theme("okcaddie", "Kobe Harborland Cafe", "Harbor view", "Hyogo, Kobe")
    assert _row_off_theme("okramen", "Otaru Canal Coffee", "Canal view", "Hokkaido, Otaru")
    assert _row_off_theme("okonsen", "Ginza Latte Lab", "Wi-Fi", "Tokyo")

    assert not _row_off_theme(
        "okcaddie", "Hakone Country Club", "Public golf course | 18 holes", "Hakone"
    )
    assert not _row_off_theme(
        "okramen", "Ichiran Shinjuku", "Tonkotsu ramen", "Tokyo, Shinjuku"
    )
    assert not _row_off_theme(
        "okonsen", "Hakone Ten-yu", "Family bath | ryokan onsen", "Hakone"
    )


def test_ai_guide_rows_need_site_theme():
    assert (
        _parse_guide_row(
            "okcaddie",
            {
                "id": "cafe-menu",
                "topic_en": "How to read a cafe menu in Japan",
                "topic_ko": "카페",
                "keywords": "cafe menu",
            },
            set(),
        )
        is None
    )
    assert (
        _parse_guide_row(
            "okramen",
            {
                "id": "ramen-machines",
                "topic_en": "How to use ramen ticket machines",
                "topic_ko": "라멘 식권기",
                "keywords": "ramen ticket",
            },
            set(),
        )
        is not None
    )


def test_seeds_for_site_has_no_cafe_names():
    cafe_markers = ("cafe", "coffee", "latte", "espresso", "kissaten", "roast", "brew")
    for site in ("okramen", "okonsen", "okcaddie"):
        for bank_rows in seeds_for_site(site).values():
            for row in bank_rows:
                blob = " ".join(str(v) for v in row.values()).lower()
                assert not any(m in blob for m in cafe_markers), (site, row)
