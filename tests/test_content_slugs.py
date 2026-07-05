"""Slug rules must stay aligned with ok-series generators."""
from content_slugs import caddie_item_slug, content_item_slug, poi_item_slug


def test_poi_item_slug():
    assert poi_item_slug("Marunouchi Blend Lab") == "marunouchi_blend_lab"
    assert poi_item_slug("O'Brien's, Tokyo") == "obriens_tokyo"


def test_caddie_item_slug():
    assert caddie_item_slug("Sample Golf Club") == "sample_golf_club"
    assert caddie_item_slug("A & B Cafe") == "a_and_b_cafe"
    assert caddie_item_slug("Dr. Smith's Course") == "dr_smiths_course"


def test_content_item_slug_site_aware():
    assert content_item_slug("okramen", "A & B Ramen") == "a_&_b_ramen"
    assert content_item_slug("okcaddie", "A & B Cafe") == "a_and_b_cafe"
    assert content_item_slug("okonsen", "Hot Spring No.1") == "hot_spring_no.1"
