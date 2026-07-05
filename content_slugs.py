"""Content filename slugs — must match ok-series generator rules."""
from __future__ import annotations


def poi_item_slug(name: str) -> str:
    """okramen / okonsen item slug (matches ramen_generator / onsen_generator)."""
    return name.lower().replace(" ", "_").replace("'", "").replace(",", "")


def caddie_item_slug(name: str) -> str:
    """okcaddie course slug (matches course_generator)."""
    return (
        name.lower()
        .replace(" ", "_")
        .replace("'", "")
        .replace(",", "")
        .replace("&", "and")
        .replace(".", "")
    )


def content_item_slug(site_id: str, name: str) -> str:
    """Site-aware item slug for MD filename lookup."""
    if site_id == "okcaddie":
        return caddie_item_slug(name)
    return poi_item_slug(name)


# Aliases used by image_site_meta and CSV row lookup.
okonsen_safe_name = poi_item_slug
caddie_safe_name = caddie_item_slug


def csv_safe_name(site_key: str, name: str) -> str:
    return content_item_slug(site_key, name)
