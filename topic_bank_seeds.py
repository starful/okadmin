"""Seed rows for topic banks — sourced from content_pipeline constants."""
from __future__ import annotations

from typing import Any

from topic_bank_registry import banks_for_site


def bootstrap_seeds_for_site(site_id: str) -> dict[str, list[dict[str, str]]]:
    """Minimum rows for a new topic bank — weekly expand pool is CSV 추가 only."""
    from content_pipeline import DEFAULT_GUIDE_SEEDS, DEFAULT_ITEM_SEEDS

    out: dict[str, list[dict[str, str]]] = {}

    if site_id == "okstats":
        out["insights"] = []
        out["guides"] = []

    elif site_id in ("okramen", "okonsen", "okcaddie"):
        out["items"] = list(DEFAULT_ITEM_SEEDS)
        out["guides"] = list(DEFAULT_GUIDE_SEEDS)
        if site_id == "okramen":
            out["items"] = [
                {"Name": "Ichiran Shinjuku", "Lat": "35.6909", "Lng": "139.7018", "Address": "Tokyo, Shinjuku", "Thumbnail": "", "Features": "Tonkotsu", "Agoda": ""},
                {"Name": "Ippudo Ginza", "Lat": "35.6711", "Lng": "139.7662", "Address": "Tokyo, Chuo", "Thumbnail": "", "Features": "Tonkotsu", "Agoda": ""},
            ]
        elif site_id == "okonsen":
            out["items"] = [
                {"Name": "Hakone Ten-yu", "Lat": "35.2393", "Lng": "139.0456", "Address": "Hakone", "Thumbnail": "", "Features": "Family bath", "Agoda": ""},
                {"Name": "Gora Kadan", "Lat": "35.2492", "Lng": "139.0465", "Address": "Hakone", "Thumbnail": "", "Features": "Ryokan onsen", "Agoda": ""},
            ]
        elif site_id == "okcaddie":
            out["items"] = [{"Name": "Sample Golf Club", "Lat": "35.0", "Lng": "135.0", "Address": "Hyogo", "Features": "Public", "Booking": ""}]

    elif site_id == "starful.biz":
        base = ["AI Engineer", "Product Manager", "Data Analyst", "DevOps Engineer", "UX Designer",
                "Backend Developer", "Cloud Architect", "Security Engineer", "Technical Writer", "QA Engineer"]
        out["positions"] = [{"position_name": t} for t in base]

    elif site_id == "jpcampus":
        out["guide_topics"] = [
            {"slug": "cost-seed", "category": "Budget", "title": "1-Year Study Cost in Japan", "description": "Budget overview", "prompt": "Write a realistic 1-year study cost guide for Tokyo."},
            {"slug": "visa-seed", "category": "Visa", "title": "Student Visa Steps", "description": "Visa guide", "prompt": "Step-by-step student visa guide for Japan."},
            {"slug": "housing-seed", "category": "Housing", "title": "Student Housing Options", "description": "Housing compare", "prompt": "Compare dorm, share house, and apartment for students."},
        ]

    elif site_id == "krcampus":
        out["guide_topics"] = [{"slug": "visa", "category": "Visa", "title": "Student Visa Guide for Korea (D-2 and D-4)", "description": "Step-by-step visa guide.", "prompt": "Write a Korea student visa guide for D-2 and D-4."}]
        out["language_schools"] = [{"name_ko": "연세대학교 한국어학당", "name_en": "Yonsei Korean Language Institute", "region": "Seoul", "city": "Seoul"}]
        out["universities"] = [{"name_ko": "서울대학교", "name_en": "Seoul National University", "region": "Seoul"}]

    elif site_id == "hatena":
        out["python"] = [{"lib_name": x} for x in ("NumPy", "Pandas", "FastAPI", "Pydantic", "httpx")]
        out["cloud"] = [
            {"Topic": "AWS Lambda vs GCP Cloud Functions vs Azure Functions"},
            {"Topic": "Amazon S3 vs Google Cloud Storage vs Azure Blob Storage"},
            {"Topic": "AWS RDS vs Cloud SQL vs Azure Database for PostgreSQL"},
            {"Topic": "Amazon EKS vs GKE vs AKS comparison"},
            {"Topic": "CloudFront vs Cloud CDN vs Azure CDN"},
        ]
        out["positions"] = [{"position_name": x} for x in ("Site Reliability Engineer", "Platform Engineer", "MLOps Engineer")]

    return out


def seeds_for_site(site_id: str) -> dict[str, list[dict[str, str]]]:
    from content_pipeline import (
        DEFAULT_GUIDE_SEEDS,
        DEFAULT_ITEM_SEEDS,
        EXPAND_GUIDE_SEEDS,
        JPCAMPUS_EXPAND_GUIDES,
        KRCAMPUS_EXPAND_TOPIC_ROWS,
        POI_EXPAND_SEEDS,
        STARFUL_EXPAND_POSITIONS,
        STATFACTS_GUIDE_EXPAND,
        STATFACTS_INSIGHT_EXPAND,
    )

    out: dict[str, list[dict[str, str]]] = {}

    if site_id == "okstats":
        out["insights"] = list(STATFACTS_INSIGHT_EXPAND)
        out["guides"] = list(STATFACTS_GUIDE_EXPAND)

    elif site_id in ("okramen", "okonsen", "okcaddie"):
        out["items"] = list(DEFAULT_ITEM_SEEDS) + list(POI_EXPAND_SEEDS)
        out["guides"] = list(DEFAULT_GUIDE_SEEDS) + list(EXPAND_GUIDE_SEEDS)
        if site_id == "okramen":
            out["items"] = [
                {
                    "Name": "Ichiran Shinjuku",
                    "Lat": "35.6909",
                    "Lng": "139.7018",
                    "Address": "Tokyo, Shinjuku",
                    "Thumbnail": "",
                    "Features": "Tonkotsu",
                    "Agoda": "",
                },
                {
                    "Name": "Ippudo Ginza",
                    "Lat": "35.6711",
                    "Lng": "139.7662",
                    "Address": "Tokyo, Chuo",
                    "Thumbnail": "",
                    "Features": "Tonkotsu",
                    "Agoda": "",
                },
            ] + list(POI_EXPAND_SEEDS)
        elif site_id == "okonsen":
            out["items"] = [
                {
                    "Name": "Hakone Ten-yu",
                    "Lat": "35.2393",
                    "Lng": "139.0456",
                    "Address": "Hakone",
                    "Thumbnail": "",
                    "Features": "Family bath",
                    "Agoda": "",
                },
                {
                    "Name": "Gora Kadan",
                    "Lat": "35.2492",
                    "Lng": "139.0465",
                    "Address": "Hakone",
                    "Thumbnail": "",
                    "Features": "Ryokan onsen",
                    "Agoda": "",
                },
            ] + list(POI_EXPAND_SEEDS)
        elif site_id == "okcaddie":
            out["items"] = [
                {
                    "Name": "Sample Golf Club",
                    "Lat": "35.0",
                    "Lng": "135.0",
                    "Address": "Hyogo",
                    "Features": "Public",
                    "Booking": "",
                },
            ] + list(POI_EXPAND_SEEDS)

    elif site_id == "starful.biz":
        base = [
            "AI Engineer",
            "Product Manager",
            "Data Analyst",
            "DevOps Engineer",
            "UX Designer",
            "Backend Developer",
            "Cloud Architect",
            "Security Engineer",
            "Technical Writer",
            "QA Engineer",
        ]
        out["positions"] = [{"position_name": t} for t in base + list(STARFUL_EXPAND_POSITIONS)]

    elif site_id == "jpcampus":
        out["guide_topics"] = [
            {
                "slug": "cost-seed",
                "category": "Budget",
                "title": "1-Year Study Cost in Japan",
                "description": "Budget overview",
                "prompt": "Write a realistic 1-year study cost guide for Tokyo.",
            },
            {
                "slug": "visa-seed",
                "category": "Visa",
                "title": "Student Visa Steps",
                "description": "Visa guide",
                "prompt": "Step-by-step student visa guide for Japan.",
            },
            {
                "slug": "housing-seed",
                "category": "Housing",
                "title": "Student Housing Options",
                "description": "Housing compare",
                "prompt": "Compare dorm, share house, and apartment for students.",
            },
        ] + list(JPCAMPUS_EXPAND_GUIDES)

    elif site_id == "krcampus":
        out["guide_topics"] = [
            {
                "slug": "visa",
                "category": "Visa",
                "title": "Student Visa Guide for Korea (D-2 and D-4)",
                "description": "Step-by-step visa guide.",
                "prompt": "Write a Korea student visa guide for D-2 and D-4.",
            },
        ] + list(KRCAMPUS_EXPAND_TOPIC_ROWS)
        out["language_schools"] = [
            {
                "name_ko": "연세대학교 한국어학당",
                "name_en": "Yonsei Korean Language Institute",
                "region": "Seoul",
                "city": "Seoul",
            },
        ]
        out["universities"] = [
            {"name_ko": "서울대학교", "name_en": "Seoul National University", "region": "Seoul"},
        ]

    elif site_id == "hatena":
        out["python"] = [{"lib_name": x} for x in ("NumPy", "Pandas", "FastAPI", "Pydantic", "httpx")]
        out["cloud"] = [
            {"Topic": "AWS Lambda vs GCP Cloud Functions vs Azure Functions"},
            {"Topic": "Amazon S3 vs Google Cloud Storage vs Azure Blob Storage"},
            {"Topic": "AWS RDS vs Cloud SQL vs Azure Database for PostgreSQL"},
            {"Topic": "Amazon EKS vs GKE vs AKS comparison"},
            {"Topic": "CloudFront vs Cloud CDN vs Azure CDN"},
        ]
        out["positions"] = [
            {"position_name": "Site Reliability Engineer"},
            {"position_name": "Platform Engineer"},
            {"position_name": "MLOps Engineer"},
        ]

    _append_extra_seeds(site_id, out)
    return out


def expand_pool_for_site(site_id: str) -> dict[str, list[dict[str, str]]]:
    """Rows eligible for weekly CSV 추가 (append to bank if not already present)."""
    from content_pipeline import (
        EXPAND_GUIDE_SEEDS,
        JPCAMPUS_EXPAND_GUIDES,
        KRCAMPUS_EXPAND_TOPIC_ROWS,
        POI_EXPAND_SEEDS,
        STARFUL_EXPAND_POSITIONS,
        STATFACTS_GUIDE_EXPAND,
        STATFACTS_INSIGHT_EXPAND,
    )

    out: dict[str, list[dict[str, str]]] = {}

    if site_id == "okstats":
        out["insights"] = list(STATFACTS_INSIGHT_EXPAND)
        out["guides"] = list(STATFACTS_GUIDE_EXPAND)

    elif site_id in ("okramen", "okonsen", "okcaddie"):
        out["items"] = list(POI_EXPAND_SEEDS)
        out["guides"] = list(EXPAND_GUIDE_SEEDS)

    elif site_id == "starful.biz":
        out["positions"] = [{"position_name": t} for t in STARFUL_EXPAND_POSITIONS]

    elif site_id == "jpcampus":
        out["guide_topics"] = list(JPCAMPUS_EXPAND_GUIDES)

    elif site_id == "krcampus":
        out["guide_topics"] = list(KRCAMPUS_EXPAND_TOPIC_ROWS)

    _append_extra_seeds(site_id, out)
    return out


def _append_extra_seeds(site_id: str, out: dict[str, list[dict[str, str]]]) -> None:
    """Additional pending topics so CSV 추가 keeps working after legacy pools."""
    extra: dict[str, list[dict[str, str]]] = {}

    if site_id == "okstats":
        extra["insights"] = [
            {
                "id": "progress-bar-checkout",
                "topic": "Checkout progress indicator",
                "intervention": "Show a 3-step progress bar during checkout",
                "outcome": "Checkout completion rate",
                "effect_min": "4",
                "effect_max": "10",
                "effect_unit": "percent_relative",
                "categories": "ux,checkout",
                "confidence": "ab_test",
                "keywords": "checkout progress bar",
            },
            {
                "id": "social-proof-product-page",
                "topic": "Social proof on product pages",
                "intervention": "Display recent purchase notifications on PDP",
                "outcome": "Add-to-cart rate",
                "effect_min": "3",
                "effect_max": "8",
                "effect_unit": "percent_relative",
                "categories": "ux,business",
                "confidence": "ab_test",
                "keywords": "social proof ecommerce",
            },
            {
                "id": "default-annual-billing",
                "topic": "Default annual billing toggle",
                "intervention": "Pre-select annual plan on pricing page",
                "outcome": "Annual plan uptake",
                "effect_min": "8",
                "effect_max": "20",
                "effect_unit": "percent_relative",
                "categories": "business,saas",
                "confidence": "ab_test",
                "keywords": "annual billing default",
            },
            {
                "id": "error-message-specificity",
                "topic": "Specific form error messages",
                "intervention": "Replace generic errors with field-specific guidance",
                "outcome": "Form completion rate",
                "effect_min": "5",
                "effect_max": "12",
                "effect_unit": "percent_relative",
                "categories": "ux,signup",
                "confidence": "ab_test",
                "keywords": "form validation errors",
            },
            {
                "id": "strength-training-frequency",
                "topic": "Strength training frequency",
                "intervention": "Train major muscle groups twice per week vs once",
                "outcome": "Strength gains over 8 weeks",
                "effect_min": "10",
                "effect_max": "25",
                "effect_unit": "percent_relative",
                "categories": "health,sports",
                "confidence": "study",
                "keywords": "strength training frequency",
            },
            {
                "id": "sleep-consistency-hrv",
                "topic": "Sleep schedule consistency",
                "intervention": "Keep bedtime within 30 minutes nightly for 4 weeks",
                "outcome": "Heart rate variability",
                "effect_min": "6",
                "effect_max": "15",
                "effect_unit": "percent_relative",
                "categories": "health",
                "confidence": "study",
                "keywords": "sleep consistency hrv",
            },
        ]
        extra["guides"] = [
            {
                "id": "funnel-step-definitions",
                "topic_en": "Defining funnel steps consistently across teams",
                "topic_ko": "",
                "keywords": "funnel definition analytics",
            },
            {
                "id": "power-analysis-primer",
                "topic_en": "Power analysis primer for product experiments",
                "topic_ko": "",
                "keywords": "power analysis ab test",
            },
            {
                "id": "novelty-effects-experiments",
                "topic_en": "Detecting novelty effects in long-running experiments",
                "topic_ko": "",
                "keywords": "novelty effect experiment",
            },
        ]

    if site_id == "krcampus":
        extra["guide_topics"] = [
            {
                "slug": "arc-renewal",
                "category": "Settlement",
                "title": "ARC renewal guide for degree students",
                "description": "When and how to renew your Alien Registration Card.",
                "prompt": "Write a Korea ARC renewal guide for D-2 students: timing, documents, and immigration office tips.",
            },
            {
                "slug": "part-time-work-rules",
                "category": "Work",
                "title": "Part-time work rules for international students",
                "description": "Legal work hours and permission steps.",
                "prompt": "Explain part-time work rules for D-2 and D-4 visa holders in Korea.",
            },
            {
                "slug": "korean-bank-account",
                "category": "Settlement",
                "title": "Opening a Korean bank account as a student",
                "description": "Bank account steps for foreigners.",
                "prompt": "Step-by-step bank account guide for international students in Korea.",
            },
        ]
        extra["language_schools"] = [
            {
                "name_ko": "서울대학교 국제어교육원",
                "name_en": "Seoul National University Korean Language Education Center",
                "region": "Seoul",
                "city": "Seoul",
            },
            {
                "name_ko": "고려대학교 한국어센터",
                "name_en": "Korea University Korean Language Center",
                "region": "Seoul",
                "city": "Seoul",
            },
        ]
        extra["universities"] = [
            {"name_ko": "연세대학교", "name_en": "Yonsei University", "region": "Seoul"},
            {"name_ko": "고려대학교", "name_en": "Korea University", "region": "Seoul"},
        ]

    for bank_id, rows in extra.items():
        if bank_id in out:
            existing_keys = {_row_key_for_merge(site_id, bank_id, r) for r in out[bank_id]}
            for row in rows:
                k = _row_key_for_merge(site_id, bank_id, row)
                if k and k not in existing_keys:
                    out[bank_id].append(row)
                    existing_keys.add(k)
        else:
            out[bank_id] = rows


def _row_key_for_merge(site_id: str, bank_id: str, row: dict[str, Any]) -> str | None:
    from topic_bank import row_key
    from topic_bank_registry import banks_for_site

    for spec in banks_for_site(site_id):
        if spec.bank_id == bank_id:
            return row_key(spec, {k: str(v) for k, v in row.items()})
    return None
