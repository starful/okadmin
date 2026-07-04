"""Topic bank registry: okadmin master CSV paths and site repo mirror paths."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

KeyKind = Literal["id", "slug", "coord", "name"]
LimitKind = Literal["content", "guide"]


@dataclass(frozen=True)
class BankSpec:
    bank_id: str
    headers: tuple[str, ...]
    key_col: str
    key_kind: KeyKind
    site_rel: str
    limit_kind: LimitKind = "content"


GUIDE_HEADERS = ("id", "topic_en", "topic_ko", "keywords")
RAMEN_HEADERS = ("Name", "Lat", "Lng", "Address", "Thumbnail", "Features", "Agoda")
ONSEN_HEADERS = RAMEN_HEADERS
COURSE_HEADERS = ("Name", "Lat", "Lng", "Address", "Features", "Booking")
INSIGHT_HEADERS = (
    "id",
    "topic",
    "intervention",
    "outcome",
    "effect_min",
    "effect_max",
    "effect_unit",
    "categories",
    "confidence",
    "keywords",
)
CAMPUS_GUIDE_HEADERS = ("slug", "category", "title", "description", "prompt")
SCHOOL_HEADERS = ("name_ko", "name_en", "region", "city")
UNIV_HEADERS = ("name_ko", "name_en", "region")
JP_UNIV_HEADERS = ("name_ja", "name_en", "region")

SITE_BANKS: dict[str, tuple[BankSpec, ...]] = {
    "okstats": (
        BankSpec("insights", INSIGHT_HEADERS, "id", "id", "script/csv/insights.csv"),
        BankSpec("guides", GUIDE_HEADERS, "id", "id", "script/csv/guides.csv", "guide"),
    ),
    "okramen": (
        BankSpec("items", RAMEN_HEADERS, "Name", "coord", "script/csv/ramens.csv"),
        BankSpec("guides", GUIDE_HEADERS, "id", "id", "script/csv/guides.csv", "guide"),
    ),
    "okonsen": (
        BankSpec("items", ONSEN_HEADERS, "Name", "coord", "script/csv/onsens.csv"),
        BankSpec("guides", GUIDE_HEADERS, "id", "id", "script/csv/guides.csv", "guide"),
    ),
    "okcaddie": (
        BankSpec("items", COURSE_HEADERS, "Name", "coord", "script/csv/courses.csv"),
        BankSpec("guides", GUIDE_HEADERS, "id", "id", "script/csv/guides.csv", "guide"),
    ),
    "starful.biz": (
        BankSpec("positions", ("position_name",), "position_name", "name", "scripts/data/positions.csv"),
    ),
    "jpcampus": (
        BankSpec(
            "guide_topics",
            CAMPUS_GUIDE_HEADERS,
            "slug",
            "slug",
            "data/guide_topics.csv",
            "guide",
        ),
        BankSpec(
            "universities",
            JP_UNIV_HEADERS,
            "name_ja",
            "name",
            "data/univ_list_100.csv",
        ),
    ),
    "krcampus": (
        BankSpec(
            "guide_topics",
            CAMPUS_GUIDE_HEADERS,
            "slug",
            "slug",
            "data/guide_topics.csv",
            "guide",
        ),
        BankSpec(
            "language_schools",
            SCHOOL_HEADERS,
            "name_ko",
            "name",
            "data/language_schools.csv",
        ),
        BankSpec(
            "universities",
            UNIV_HEADERS,
            "name_ko",
            "name",
            "data/universities.csv",
        ),
    ),
    "hatena": (
        BankSpec("python", ("lib_name",), "lib_name", "name", "csv/python.csv"),
        BankSpec("cloud", ("Topic",), "Topic", "name", "csv/cloud.csv"),
        BankSpec("positions", ("position_name",), "position_name", "name", "csv/positions.csv"),
    ),
}


def banks_for_site(site_id: str) -> tuple[BankSpec, ...]:
    return SITE_BANKS.get(site_id, ())
