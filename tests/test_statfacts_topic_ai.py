"""StatFacts topic AI helpers."""

from __future__ import annotations

from statfacts_topic_ai import (
    _forbidden_ids_csv,
    _normalize_id,
    _parse_guide_row,
    _parse_insight_row,
    distribute_category_counts,
)


def test_distribute_category_counts():
    dist = distribute_category_counts(6, ("ux", "business", "gaming", "food", "hr", "travel", "sports", "health"))
    assert sum(dist.values()) == 6
    assert all(v >= 0 for v in dist.values())


def test_forbidden_ids_csv_includes_all():
    ids = {f"topic-{i}" for i in range(120)}
    text = _forbidden_ids_csv(ids)
    assert "topic-0" in text
    assert "topic-119" in text
    assert text.count(",") == 119


def test_parse_insight_rejects_duplicate():
    existing = {"guest-checkout-conversion"}
    row = _parse_insight_row(
        {
            "id": "guest-checkout-conversion",
            "topic": "Guest checkout",
            "intervention": "Add guest checkout",
            "outcome": "Checkout rate",
        },
        existing,
    )
    assert row is None


def test_parse_insight_accepts_new():
    existing: set[str] = set()
    row = _parse_insight_row(
        {
            "id": " Niche_Pricing_Anchor ",
            "topic": "Pricing anchor",
            "intervention": "Show higher-tier plan first",
            "outcome": "Plan mix toward annual",
            "categories": "business,saas",
        },
        existing,
    )
    assert row is not None
    assert row["id"] == "niche-pricing-anchor"
    assert "niche-pricing-anchor" in existing


def test_normalize_id():
    assert _normalize_id("Hello_World!!") == "hello-world"
    assert _parse_guide_row({"id": "hello-world", "topic_en": "Hi"}, {"hello-world"}) is None
