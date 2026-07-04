"""One-click content pipelines (topic bank → generate → build)."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from config import get_service, repo_path, work_root_available
from topic_bank_registry import banks_for_site

MIN_ITEM_ROWS = 8
MIN_GUIDE_ROWS = 3

# Hub one-click caps: 가이드 3토픽(최대 6 MD) · 아이템 6행(최대 12 MD en/ko).
DEFAULT_CONTENT_LIMIT = 6
DEFAULT_GUIDE_LIMIT = 3
DEFAULT_HATENA_MAX_POSTS = 6
DEFAULT_KOREAN_LIMIT = 6
DEFAULT_JAPANESE_LIMIT = 3
MAX_CONTENT_LIMIT = 50
MAX_GUIDE_LIMIT = 20
MAX_HATENA_MAX_POSTS = 20
MAX_KOREAN_LIMIT = 30
MAX_JAPANESE_LIMIT = 20
MAX_SCHOOL_LIMIT = 15
MAX_UNIVERSITY_LIMIT = 15
DEFAULT_KRCAMPUS_SCHOOL_LIMIT = 3
DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT = 3

# Tokyo cafe seeds when items.csv is nearly empty
DEFAULT_ITEM_SEEDS: list[dict[str, str]] = [
    {
        "Name": "Marunouchi Blend Lab",
        "Lat": "35.6812",
        "Lng": "139.7671",
        "Address": "Tokyo, Marunouchi",
        "Features": "Specialty coffee | Wi-Fi",
        "Agoda": "",
    },
    {
        "Name": "Shinjuku South Latte Lab",
        "Lat": "35.6895",
        "Lng": "139.7005",
        "Address": "Tokyo, Shinjuku",
        "Features": "Third wave espresso | Laptop friendly",
        "Agoda": "",
    },
    {
        "Name": "Shibuya Morning Club",
        "Lat": "35.6581",
        "Lng": "139.7017",
        "Address": "Tokyo, Shibuya",
        "Features": "Brunch set | Tourist friendly",
        "Agoda": "",
    },
    {
        "Name": "Ginza Patisserie Bloom",
        "Lat": "35.6718",
        "Lng": "139.7645",
        "Address": "Tokyo, Ginza",
        "Features": "Dessert pairing | English menu",
        "Agoda": "",
    },
    {
        "Name": "Ueno Parkside Drip",
        "Lat": "35.7089",
        "Lng": "139.7310",
        "Address": "Tokyo, Ueno",
        "Features": "Pour-over bar | Calm vibe",
        "Agoda": "",
    },
    {
        "Name": "Ebisu Workbench Cafe",
        "Lat": "35.6467",
        "Lng": "139.7100",
        "Address": "Tokyo, Ebisu",
        "Features": "Work-friendly | Wi-Fi",
        "Agoda": "",
    },
    {
        "Name": "Ikebukuro Sun City Espresso",
        "Lat": "35.7289",
        "Lng": "139.7101",
        "Address": "Tokyo, Ikebukuro",
        "Features": "House roast | Easy access",
        "Agoda": "",
    },
    {
        "Name": "Roppongi Origin Lab",
        "Lat": "35.6655",
        "Lng": "139.7293",
        "Address": "Tokyo, Roppongi",
        "Features": "Single origin | Late hours",
        "Agoda": "",
    },
]

# Legacy expand pool for okramen / okonsen / okcaddie (seed CSV 추가; AI 목록 추가가 우선).
POI_EXPAND_SEEDS: list[dict[str, str]] = [
    {"Name": "Yokohama Minato Mirai Cafe", "Lat": "35.4564", "Lng": "139.6340", "Address": "Kanagawa, Yokohama", "Features": "Waterfront | Wi-Fi", "Agoda": ""},
    {"Name": "Kamakura Komachi Drip", "Lat": "35.3192", "Lng": "139.5503", "Address": "Kanagawa, Kamakura", "Features": "Historic street | Matcha", "Agoda": ""},
    {"Name": "Nagoya Sakae Espresso", "Lat": "35.1709", "Lng": "136.9066", "Address": "Aichi, Nagoya", "Features": "City center | House roast", "Agoda": ""},
    {"Name": "Kanazawa Higashi Chaya Cafe", "Lat": "36.5713", "Lng": "136.6622", "Address": "Ishikawa, Kanazawa", "Features": "Traditional district", "Agoda": ""},
    {"Name": "Hiroshima Peace Park Cafe", "Lat": "34.3955", "Lng": "132.4536", "Address": "Hiroshima", "Features": "Tourist area | Calm", "Agoda": ""},
    {"Name": "Sendai Ichibancho Latte", "Lat": "38.2606", "Lng": "140.8829", "Address": "Miyagi, Sendai", "Features": "Shopping street", "Agoda": ""},
    {"Name": "Naha Kokusai Street Coffee", "Lat": "26.2140", "Lng": "127.6889", "Address": "Okinawa, Naha", "Features": "Island blend | AC", "Agoda": ""},
    {"Name": "Hakodate Morning Market Cafe", "Lat": "41.7687", "Lng": "140.7290", "Address": "Hokkaido, Hakodate", "Features": "Morning set", "Agoda": ""},
    {"Name": "Asahikawa Winter Roast", "Lat": "43.7706", "Lng": "142.3650", "Address": "Hokkaido, Asahikawa", "Features": "Warm interior", "Agoda": ""},
    {"Name": "Nara Parkside Kissaten", "Lat": "34.6851", "Lng": "135.8050", "Address": "Nara", "Features": "Deer area nearby", "Agoda": ""},
    {"Name": "Kobe Harborland Cafe", "Lat": "34.6795", "Lng": "135.1830", "Address": "Hyogo, Kobe", "Features": "Harbor view", "Agoda": ""},
    {"Name": "Matsuyama Dogo Onsen Cafe", "Lat": "33.8518", "Lng": "132.7860", "Address": "Ehime, Matsuyama", "Features": "Onsen town", "Agoda": ""},
    {"Name": "Takamatsu Ritsurin Garden Cafe", "Lat": "34.3299", "Lng": "134.0445", "Address": "Kagawa, Takamatsu", "Features": "Garden district", "Agoda": ""},
    {"Name": "Kumamoto Castle Town Cafe", "Lat": "32.8062", "Lng": "130.7059", "Address": "Kumamoto", "Features": "Castle area", "Agoda": ""},
    {"Name": "Otaru Canal Coffee", "Lat": "43.1967", "Lng": "141.0014", "Address": "Hokkaido, Otaru", "Features": "Canal view", "Agoda": ""},
    {"Name": "Miyazaki Phoenix Cafe", "Lat": "31.9077", "Lng": "131.4202", "Address": "Miyazaki", "Features": "Coastal city", "Agoda": ""},
    {"Name": "Niigata Bandai Brew", "Lat": "37.9161", "Lng": "139.0364", "Address": "Niigata", "Features": "Rice country roast", "Agoda": ""},
    {"Name": "Matsumoto Castle Cafe", "Lat": "36.2380", "Lng": "137.9690", "Address": "Nagano, Matsumoto", "Features": "Castle town", "Agoda": ""},
    {"Name": "Okayama Korakuen Cafe", "Lat": "34.6650", "Lng": "133.9355", "Address": "Okayama", "Features": "Garden area", "Agoda": ""},
    {"Name": "Shizuoka Station Espresso", "Lat": "34.9717", "Lng": "138.3890", "Address": "Shizuoka", "Features": "Tea country | Wi-Fi", "Agoda": ""},
]

DEFAULT_GUIDE_SEEDS: list[dict[str, str]] = [
    {
        "id": "guide_seed_001",
        "topic_en": "Best Specialty Cafes in Tokyo (2026)",
        "topic_ko": "2026 도쿄 스페셜티 카페 가이드",
        "keywords": "tokyo specialty cafe",
    },
    {
        "id": "guide_seed_002",
        "topic_en": "Quiet Work-Friendly Cafes in Tokyo",
        "topic_ko": "도쿄 노트북 카페",
        "keywords": "tokyo work cafe wifi",
    },
    {
        "id": "guide_seed_003",
        "topic_en": "Best Dessert Cafes in Tokyo for Travelers",
        "topic_ko": "도쿄 디저트 카페",
        "keywords": "tokyo dessert cafe",
    },
]

ITEM_HEADERS = ["Name", "Lat", "Lng", "Address", "Features", "Agoda"]
GUIDE_HEADERS = ["id", "topic_en", "topic_ko", "keywords"]
KRCAMPUS_GUIDE_HEADERS = ["id", "topic_en", "topic_ja", "keywords"]
KRCAMPUS_GUIDE_SEEDS: list[dict[str, str]] = [
    {
        "id": "guide_visa",
        "topic_en": "Student Visa Guide for Korea (D-2 and D-4)",
        "topic_ja": "韓国留学ビザ完全ガイド（D-2・D-4）",
        "keywords": "korea student visa d-2 d-4",
    },
    {
        "id": "guide_cost",
        "topic_en": "1-Year Study Cost in Seoul: Realistic Budget",
        "topic_ja": "ソウル留学1年間の費用シミュレーション",
        "keywords": "study in korea cost budget seoul",
    },
    {
        "id": "guide_housing",
        "topic_en": "Student Housing in Korea: Dorm Goshiwon vs Apartment",
        "topic_ja": "韓国留学の住まい比較（学生寮・ゴシウォン・マンション）",
        "keywords": "korea student housing goshiwon dorm",
    },
]
KRCAMPUS_EXPAND_GUIDES: list[dict[str, str]] = [
    {
        "id": "guide_scholarship",
        "topic_en": "Scholarships for International Students in Korea",
        "topic_ja": "韓国留学の奨学金ガイド",
        "keywords": "korea scholarship international student",
    },
    {
        "id": "guide_topik",
        "topic_en": "TOPIK Exam Guide: Levels Schedule and Study Tips",
        "topic_ja": "TOPIK試験ガイド（レベル・日程・対策）",
        "keywords": "topik exam korea study tips",
    },
    {
        "id": "guide_seoul",
        "topic_en": "Studying in Seoul vs Busan: Which City Fits You?",
        "topic_ja": "ソウル留学 vs 釜山留学 徹底比較",
        "keywords": "seoul vs busan study abroad korea",
    },
]

KRCAMPUS_EXPAND_TOPIC_ROWS: list[dict[str, str]] = [
    {
        "slug": "gks-guide",
        "category": "Budget",
        "title": "GKS (KGSP) Scholarship Guide for Korea",
        "description": "Complete guide to Global Korea Scholarship.",
        "prompt": "Write a detailed GKS scholarship guide: eligibility, documents, timeline, and tips for language vs degree tracks.",
    },
    {
        "slug": "d4-to-d2",
        "category": "Visa",
        "title": "Switching from D-4 to D-2 Visa in Korea",
        "description": "How language students transition to degree visas.",
        "prompt": "Explain D-4 to D-2 visa change process, timing, documents, and common pitfalls for international students.",
    },
    {
        "slug": "seoul-neighborhoods",
        "category": "Region",
        "title": "Best Seoul Neighborhoods for Students",
        "description": "Sinchon vs Hongdae vs Gangnam for students.",
        "prompt": "Compare Sinchon, Hongdae, Gangnam, and Jamsil for student housing, commute, and lifestyle with a table.",
    },
    {
        "slug": "busan-student-life",
        "category": "Region",
        "title": "Student Life in Busan: Costs and Culture",
        "description": "Living and studying in Busan.",
        "prompt": "Compare Busan student life: rent, transit, beaches, language schools, and university access.",
    },
    {
        "slug": "goshiwon-guide",
        "category": "Housing",
        "title": "Goshiwon Guide for Korea Students",
        "description": "What to expect in Korean goshiwon.",
        "prompt": "Explain goshiwon housing: costs, contracts, pros/cons, and red flags for foreign students.",
    },
    {
        "slug": "dorm-application",
        "category": "Housing",
        "title": "How to Apply for University Dormitories in Korea",
        "description": "Dorm priority and deadlines.",
        "prompt": "Guide to Korean university dorm applications: deadlines, fees, roommate rules, and alternatives.",
    },
    {
        "slug": "topik-study-plan",
        "category": "Exam",
        "title": "3-Month TOPIK Study Plan",
        "description": "Structured TOPIK prep schedule.",
        "prompt": "Create a 12-week TOPIK study plan with weekly goals for vocabulary, grammar, reading, and listening.",
    },
    {
        "slug": "arc-registration",
        "category": "Settlement",
        "title": "Alien Registration Card (ARC) Guide",
        "description": "Step-by-step ARC application.",
        "prompt": "Write ARC registration guide: where to go, documents, photo rules, and re-entry permit basics.",
    },
    {
        "slug": "sim-esim-korea",
        "category": "Settlement",
        "title": "SIM and eSIM Plans in Korea (2026)",
        "description": "Mobile setup for students.",
        "prompt": "Compare prepaid SIM, eSIM, and carrier plans (SKT, KT, LG U+) for short and long stays in Korea.",
    },
    {
        "slug": "monthly-budget-seoul",
        "category": "Budget",
        "title": "Monthly Student Budget in Seoul (2026)",
        "description": "Seoul cost breakdown.",
        "prompt": "Provide detailed monthly budget for Seoul students by frugal vs comfortable lifestyle.",
    },
    {
        "slug": "winter-korea-student",
        "category": "Life",
        "title": "Surviving Korean Winter as a Student",
        "description": "Heating, clothing, and indoor life tips.",
        "prompt": "Guide international students through Korean winter: heating bills, layering, indoor activities, and health tips.",
    },
    {
        "slug": "summer-internship-korea",
        "category": "Career",
        "title": "Summer Internships for International Students in Korea",
        "description": "Finding legal short internships.",
        "prompt": "Explain summer internship options, visa rules, and where to search for international students in Korea.",
    },
    {
        "slug": "korean-food-student-budget",
        "category": "Life",
        "title": "Cheap Korean Food for Students on a Budget",
        "description": "Affordable meals near campus.",
        "prompt": "List budget-friendly Korean meals, convenience store hacks, and student cafeteria tips with approximate prices.",
    },
]

# Weekly guide topic pool (deduped by id) for dual-csv sites.
EXPAND_GUIDE_SEEDS: list[dict[str, str]] = [
    {
        "id": "guide_expand_001",
        "topic_en": "How to read a Japanese menu at cafes and restaurants",
        "topic_ko": "일본 식당·카페 메뉴 읽는 법",
        "keywords": "japanese menu reading",
    },
    {
        "id": "guide_expand_002",
        "topic_en": "Cashless payment and IC cards for travelers in Japan",
        "topic_ko": "일본 여행 결제·교통카드 가이드",
        "keywords": "japan suica paypay cashless",
    },
    {
        "id": "guide_expand_003",
        "topic_en": "Seasonal travel tips for Japan (spring to winter)",
        "topic_ko": "일본 계절별 여행 팁",
        "keywords": "japan seasonal travel",
    },
    {
        "id": "guide_expand_004",
        "topic_en": "Etiquette at shrines and temples in Japan",
        "topic_ko": "일본 신사·절 예절",
        "keywords": "japan shrine etiquette",
    },
    {
        "id": "guide_expand_005",
        "topic_en": "Using Google Maps and transit apps in Tokyo",
        "topic_ko": "도쿄 지도·교통 앱 활용",
        "keywords": "tokyo maps transit apps",
    },
    {
        "id": "guide_expand_006",
        "topic_en": "Allergies and dietary restrictions when dining in Japan",
        "topic_ko": "일본 식사 알레르기·식단 제한",
        "keywords": "japan food allergy halal vegan",
    },
    {
        "id": "guide_expand_007",
        "topic_en": "Japan train etiquette and reserved vs non-reserved seats",
        "topic_ko": "일본 기차 예절·좌석 종류",
        "keywords": "japan train shinkansen reserved seat",
    },
    {
        "id": "guide_expand_008",
        "topic_en": "Convenience store survival guide for travelers in Japan",
        "topic_ko": "일본 편의점 활용 가이드",
        "keywords": "japan konbini guide 7-eleven lawson",
    },
    {
        "id": "guide_expand_009",
        "topic_en": "How to handle earthquakes and typhoons in Japan",
        "topic_ko": "일본 지진·태풍 대비",
        "keywords": "japan earthquake typhoon safety",
    },
]

# StatFacts weekly pools (not Japan travel guides).
STATFACTS_GUIDE_EXPAND: list[dict[str, str]] = [
    {
        "id": "benchmark-segmentation",
        "topic_en": "Segmenting benchmarks by device and traffic source",
        "topic_ko": "",
        "keywords": "benchmark segmentation mobile desktop",
    },
    {
        "id": "guardrail-metrics-ab-tests",
        "topic_en": "Choosing guardrail metrics for A/B tests",
        "topic_ko": "",
        "keywords": "guardrail metrics ab test",
    },
    {
        "id": "reading-meta-analysis-limits",
        "topic_en": "What meta-analysis can and cannot tell product teams",
        "topic_ko": "",
        "keywords": "meta analysis limits product",
    },
    {
        "id": "documenting-experiment-priors",
        "topic_en": "Documenting external priors in experiment briefs",
        "topic_ko": "",
        "keywords": "experiment brief benchmark prior",
    },
    {
        "id": "seasonality-and-benchmarks",
        "topic_en": "Adjusting benchmarks for seasonality and campaigns",
        "topic_ko": "",
        "keywords": "seasonality benchmark context",
    },
    {
        "id": "sample-ratio-mismatch",
        "topic_en": "Detecting sample ratio mismatch in experiments",
        "topic_ko": "",
        "keywords": "srm sample ratio mismatch",
    },
]

STATFACTS_INSIGHT_EXPAND: list[dict[str, str]] = [
    {
        "id": "guest-checkout-conversion",
        "topic": "Guest checkout",
        "intervention": "Add guest checkout without forced account creation",
        "outcome": "Checkout completion rate",
        "effect_min": "6",
        "effect_max": "14",
        "effect_unit": "percent_relative",
        "categories": "ux,checkout,business",
        "confidence": "ab_test",
        "keywords": "guest checkout account friction",
    },
    {
        "id": "trust-badges-checkout",
        "topic": "Trust badges at checkout",
        "intervention": "Show security and payment trust badges near pay button",
        "outcome": "Checkout completion rate",
        "effect_min": "3",
        "effect_max": "9",
        "effect_unit": "percent_relative",
        "categories": "ux,checkout,business",
        "confidence": "ab_test",
        "keywords": "trust badge checkout security",
    },
    {
        "id": "mobile-form-field-count",
        "topic": "Mobile form field count",
        "intervention": "Reduce visible fields on mobile signup to five or fewer",
        "outcome": "Signup completion rate",
        "effect_min": "8",
        "effect_max": "18",
        "effect_unit": "percent_relative",
        "categories": "ux,signup,business",
        "confidence": "meta_analysis",
        "keywords": "mobile signup form fields",
    },
    {
        "id": "annual-plan-discount-callout",
        "topic": "Annual plan savings callout",
        "intervention": "Highlight annual savings percentage on pricing page",
        "outcome": "Share choosing annual billing",
        "effect_min": "10",
        "effect_max": "25",
        "effect_unit": "percent_relative",
        "categories": "business,saas",
        "confidence": "ab_test",
        "keywords": "annual billing pricing page",
    },
    {
        "id": "onboarding-checklist-activation",
        "topic": "Onboarding checklist",
        "intervention": "Show a 3–5 step onboarding checklist in first session",
        "outcome": "Week-1 activation rate",
        "effect_min": "12",
        "effect_max": "28",
        "effect_unit": "percent_relative",
        "categories": "ux,business,saas",
        "confidence": "ab_test",
        "keywords": "onboarding checklist activation",
    },
    {
        "id": "push-notification-opt-in-timing",
        "topic": "Push opt-in timing",
        "intervention": "Delay push permission prompt until after first value moment",
        "outcome": "Push opt-in rate",
        "effect_min": "15",
        "effect_max": "40",
        "effect_unit": "percent_relative",
        "categories": "ux,business",
        "confidence": "ab_test",
        "keywords": "push notification permission prompt",
    },
    {
        "id": "interval-training-5k-time",
        "topic": "Interval training for 5K",
        "intervention": "Add twice-weekly interval sessions to base training",
        "outcome": "5K race time improvement",
        "effect_min": "2",
        "effect_max": "5",
        "effect_unit": "percent_relative",
        "categories": "sports,running",
        "confidence": "study",
        "keywords": "interval training 5k running",
    },
    {
        "id": "protein-post-workout-recovery",
        "topic": "Post-workout protein timing",
        "intervention": "Consume 20–30g protein within 2 hours after strength training",
        "outcome": "Muscle soreness and recovery scores",
        "effect_min": "10",
        "effect_max": "22",
        "effect_unit": "percent_relative",
        "categories": "health,sports",
        "confidence": "study",
        "keywords": "protein recovery strength training",
    },
    {
        "id": "mindfulness-break-work-stress",
        "topic": "Micro mindfulness breaks",
        "intervention": "Offer guided 5-minute mindfulness breaks during workday",
        "outcome": "Self-reported stress scores",
        "effect_min": "8",
        "effect_max": "18",
        "effect_unit": "percent_relative",
        "categories": "health,hr",
        "confidence": "study",
        "keywords": "mindfulness workplace stress",
    },
    {
        "id": "meal-kit-portion-adherence",
        "topic": "Meal kit portion control",
        "intervention": "Switch to pre-portioned meal kits for weekday dinners",
        "outcome": "Weekly calorie intake",
        "effect_min": "5",
        "effect_max": "12",
        "effect_unit": "percent_relative",
        "categories": "food,health",
        "confidence": "study",
        "keywords": "meal kit portion calories",
    },
    {
        "id": "tutorial-skip-option-games",
        "topic": "Skippable game tutorial",
        "intervention": "Allow skipping the opening tutorial with clear later access",
        "outcome": "Day-1 retention",
        "effect_min": "4",
        "effect_max": "11",
        "effect_unit": "percent_relative",
        "categories": "gaming,ux",
        "confidence": "ab_test",
        "keywords": "game tutorial skip retention",
    },
    {
        "id": "async-video-interview-completion",
        "topic": "Async video interviews",
        "intervention": "Replace live phone screen with async one-way video interview",
        "outcome": "Candidate screen completion rate",
        "effect_min": "12",
        "effect_max": "30",
        "effect_unit": "percent_relative",
        "categories": "hr,business",
        "confidence": "estimate",
        "keywords": "async interview hiring funnel",
    },
]

STARFUL_EXPAND_POSITIONS = [
    "Site Reliability Engineer",
    "MLOps Engineer",
    "Platform Engineer",
    "Security Engineer",
    "Technical Program Manager",
    "Solutions Architect",
    "Mobile Engineer",
    "iOS Engineer",
    "Android Engineer",
    "Game Developer",
]

JPCAMPUS_EXPAND_GUIDES = [
    {
        "slug": "parttime-seed",
        "category": "Work",
        "title": "Part-time jobs for international students",
        "description": "Work rules overview",
        "prompt": "Explain part-time work rules and popular jobs for students in Japan.",
    },
    {
        "slug": "healthcare-seed",
        "category": "Life",
        "title": "Healthcare for students in Japan",
        "description": "Clinics and insurance",
        "prompt": "Guide to student health insurance and visiting clinics in Japan.",
    },
    {
        "slug": "bank-seed",
        "category": "Life",
        "title": "Opening a bank account as a student",
        "description": "Bank account steps",
        "prompt": "Step-by-step bank account opening for international students.",
    },
    {
        "slug": "transport-seed",
        "category": "Life",
        "title": "Student commuter passes in Japan",
        "description": "Suica, commuter tickets, and discounts",
        "prompt": "Explain student commuter passes, Suica/Pasmo, and monthly train discounts in major Japanese cities.",
    },
    {
        "slug": "jlpt-seed",
        "category": "Exam",
        "title": "JLPT exam guide for international students",
        "description": "Levels, schedule, and study tips",
        "prompt": "Write a JLPT guide: N5–N1 overview, exam schedule, registration, and study strategies for university admission.",
    },
    {
        "slug": "classroom-culture-seed",
        "category": "Culture",
        "title": "Japanese classroom culture for newcomers",
        "description": "Participation, punctuality, and group work",
        "prompt": "Explain Japanese classroom norms: attendance, group projects, speaking up, and relationship with professors.",
    },
]

SITE_GCS_BUCKETS: dict[str, str] = {
    "okramen": "gs://ok-project-assets/okramen",
    "okonsen": "gs://ok-project-assets/okonsen",
    "okcaddie": "gs://ok-project-assets/okcaddie",
    "okstats": "gs://ok-project-assets/statfacts",
    "krcampus": "gs://ok-project-assets/krcampus",
    "starful.biz": "gs://starful-biz-assets",
}

SITE_GCS_IMAGE_DIRS: dict[str, str] = {
    "starful.biz": "app/static/img",
}

_CONTENT_ZERO_PATTERNS = (
    "no new guides to generate",
    "no missing en/ko",
    "no guide orphans",
    "no new items",
    "생성할 새",
    "모든 가이드가 이미",
    "모든 코스 콘텐츠가 이미",
    "모든 파일이 생성済",
    "すべてのファイルが生成済",
    "새로 생성할 컨텐츠가 없",
    "pending: 0",
)
_CONTENT_GEN_PATTERNS = (
    r"starting generation for (\d+)",
    r"generating (\d+) missing",
    r"🔔 (\d+) topic",
    r"🔔 (\d+)개",
    r"✅ \[done\]",
    r"✅ \[완료\]",
    r"✅ success:",
    r"✅ 完了:",
    r"✅ 생성 완료 \(\d+\)",
)


def _log_dir() -> Path:
    base = Path(__file__).resolve().parent / "data" / "content_logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def pipeline_log_path(site_id: str) -> Path:
    return _log_dir() / f"{site_id}_pipeline.log"


def pipeline_status_path(site_id: str) -> Path:
    return _log_dir() / f"{site_id}_pipeline_status.json"


def read_pipeline_status(site_id: str) -> dict[str, Any] | None:
    path = pipeline_status_path(site_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_pipeline_status(site_id: str, data: dict[str, Any]) -> None:
    stamped = _stamp_pipeline_result(data)
    pipeline_status_path(site_id).write_text(
        json.dumps(stamped, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


_PIPELINE_HEADER_RE = re.compile(
    r"^# (\S+) pipeline (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*$",
    re.MULTILINE,
)


def _stamp_pipeline_result(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    if "finished_at" not in out:
        out["finished_at"] = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    return out


def _parse_run_datetime(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:19])
    except ValueError:
        return None


def pipeline_last_run(site_id: str) -> dict[str, Any]:
    """Last pipeline run time for UI (status file, log header, or file mtime)."""
    status = read_pipeline_status(site_id)
    ok: bool | None = status.get("ok") if status else None
    at: datetime | None = None

    status_path = pipeline_status_path(site_id)
    if status:
        at = _parse_run_datetime(str(status.get("finished_at") or status.get("last_run_at") or ""))
        if at is None and status_path.is_file():
            at = datetime.fromtimestamp(status_path.stat().st_mtime)

    log_path = pipeline_log_path(site_id)
    if at is None and log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        matches = _PIPELINE_HEADER_RE.findall(text)
        for sid, ts in reversed(matches):
            if sid == site_id:
                at = _parse_run_datetime(ts)
                break
        if at is None:
            at = datetime.fromtimestamp(log_path.stat().st_mtime)

    display = at.strftime("%Y-%m-%d %H:%M") if at else None
    return {
        "last_run_at": at.isoformat(sep=" ") if at else None,
        "last_run_display": display,
        "last_run_ok": ok,
    }


def _count_csv_rows(path: Path, *, required_col: str | None = None) -> int:
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return 0
    reader = csv.DictReader(io.StringIO(text))
    n = 0
    for row in reader:
        if required_col:
            if not (row.get(required_col) or "").strip():
                continue
        n += 1
    return n


def _normalize_csv_row(raw: dict[str, Any], headers: list[str]) -> dict[str, str]:
    """Merge DictReader restkey (None) into the last column — fixes unquoted commas in CSV."""
    row = {h: (raw.get(h) or "").strip() for h in headers}
    extra = raw.get(None)
    if extra is not None:
        extras = extra if isinstance(extra, list) else [str(extra)]
        tail = headers[-1] if headers else ""
        if tail:
            parts = [row.get(tail, "")] + [str(x).strip() for x in extras if str(x).strip()]
            row[tail] = ",".join(p for p in parts if p)
    return row


def _read_csv_dicts(path: Path, headers: list[str]) -> list[dict[str, str]]:
    if not path.is_file() or not path.read_text(encoding="utf-8-sig").strip():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return [_normalize_csv_row(r, headers) for r in csv.DictReader(f)]


def _write_csv_dicts(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows({h: (r.get(h) or "") for h in headers} for r in rows)
    path.write_text(buf.getvalue(), encoding="utf-8-sig")


def _csv_coord_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    keys: set[str] = set()
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lat = (row.get("Lat") or row.get("lat") or "").strip()
            lng = (row.get("Lng") or row.get("lng") or "").strip()
            if not lat or not lng:
                continue
            try:
                keys.add(f"{float(lat):.4f},{float(lng):.4f}")
            except ValueError:
                continue
    return keys


def _append_csv_rows_by_coord(
    path: Path,
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    max_add: int,
) -> int:
    if max_add <= 0:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_csv_dicts(path, headers)
    coord_keys = _csv_coord_keys(path)
    added = 0
    for row in rows:
        if added >= max_add:
            break
        lat = (row.get("Lat") or "").strip()
        lng = (row.get("Lng") or "").strip()
        if not lat or not lng:
            continue
        try:
            key = f"{float(lat):.4f},{float(lng):.4f}"
        except ValueError:
            continue
        if key in coord_keys:
            continue
        existing.append({h: row.get(h, "") for h in headers})
        coord_keys.add(key)
        added += 1
    if not added:
        return 0
    _write_csv_dicts(path, headers, existing)
    return added


def _append_csv_rows_limited(
    path: Path,
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    key_col: str,
    max_add: int,
) -> int:
    if max_add <= 0:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_csv_dicts(path, headers)
    keys = {(r.get(key_col) or "").strip().lower() for r in existing}
    added = 0
    for row in rows:
        if added >= max_add:
            break
        key = (row.get(key_col) or "").strip().lower()
        if key and key in keys:
            continue
        existing.append({h: row.get(h, "") for h in headers})
        keys.add(key)
        added += 1
    if not added:
        return 0
    _write_csv_dicts(path, headers, existing)
    return added


def _append_csv_rows(path: Path, headers: list[str], rows: list[dict[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_csv_dicts(path, headers)
    names = {(r.get(headers[0]) or "").strip().lower() for r in existing}
    added = 0
    for row in rows:
        key = (row.get(headers[0]) or "").strip().lower()
        if key and key in names:
            continue
        existing.append({h: row.get(h, "") for h in headers})
        names.add(key)
        added += 1
    _write_csv_dicts(path, headers, existing)
    return added


_STEP_FAILURE_MARKERS = (
    "❌ CSV file not found:",
    "Traceback (most recent call last):",
)


def _step_output_indicates_failure(text: str) -> bool:
    if not text:
        return False
    return any(marker in text for marker in _STEP_FAILURE_MARKERS)


def _run_step(
    repo: Path,
    logf,
    *,
    label: str,
    argv: list[str],
    env: dict[str, str],
    timeout: int = 3600,
) -> dict[str, Any]:
    logf.write(f"\n{'=' * 50}\n[{datetime.now():%F %T}] {label}\n")
    logf.write(" ".join(argv) + "\n")
    logf.flush()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        logf.write(f"TIMEOUT after {timeout}s\n")
        if e.stdout:
            logf.write(e.stdout)
        if e.stderr:
            logf.write(e.stderr)
        return {"ok": False, "label": label, "error": "timeout", "exit_code": -1}

    if proc.stdout:
        logf.write(proc.stdout)
    if proc.stderr:
        logf.write(proc.stderr)
    logf.flush()
    combined_out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and not _step_output_indicates_failure(combined_out)
    err_tail = ""
    if not ok:
        lines = [ln for ln in combined_out.splitlines() if ln.strip()]
        err_tail = "\n".join(lines[-12:])
    return {
        "ok": ok,
        "label": label,
        "exit_code": proc.returncode,
        "error": err_tail if not ok else "",
        "output": combined_out[-8000:],
    }


def _merge_pipeline_env(repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "CONTENT_LIMIT",
        "GUIDE_LIMIT",
        "SCHOOL_LIMIT",
        "UNIVERSITY_LIMIT",
        "HATENA_MAX_POSTS",
        "KOREAN_LIMIT",
        "JAPANESE_LIMIT",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GOOGLE_PLACES_API_KEY",
        "KRCAMPUS_GOOGLE_MAPS_API_KEY",
    ):
        if key not in env:
            if key == "CONTENT_LIMIT":
                env[key] = str(DEFAULT_CONTENT_LIMIT)
            elif key == "GUIDE_LIMIT":
                env[key] = str(DEFAULT_GUIDE_LIMIT)
            elif key == "HATENA_MAX_POSTS":
                env[key] = str(DEFAULT_HATENA_MAX_POSTS)
            elif key == "KOREAN_LIMIT":
                env[key] = str(DEFAULT_KOREAN_LIMIT)
            elif key == "JAPANESE_LIMIT":
                env[key] = str(DEFAULT_JAPANESE_LIMIT)
    repo_env = repo / ".env"
    if repo_env.is_file():
        try:
            from dotenv import dotenv_values

            for k, v in (dotenv_values(repo_env) or {}).items():
                if v and k not in env:
                    env[k] = str(v)
        except ImportError:
            pass
    okadmin_env = Path(__file__).resolve().parent / ".env"
    if okadmin_env.is_file():
        try:
            from dotenv import dotenv_values

            for k, v in (dotenv_values(okadmin_env) or {}).items():
                if v and k in (
                    "GEMINI_API_KEY",
                    "GEMINI_MODEL",
                    "GOOGLE_PLACES_API_KEY",
                    "KRCAMPUS_GOOGLE_MAPS_API_KEY",
                    "HATENA_USERNAME",
                    "HATENA_PYTHON_BLOG_ID",
                    "HATENA_PYTHON_API_KEY",
                ) and k not in env:
                    env[k] = str(v)
        except ImportError:
            pass
    _sanitize_pipeline_limits(env)
    return env


def ensure_okstats_csv(repo: Path, logf, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Sync topic bank state only — queue growth is via 목록 추가 (AI)."""
    from topic_bank_pipeline import topic_bank_sync_only

    return topic_bank_sync_only("okstats", repo, logf)


def ensure_poi_site_csv(site_id: str, repo: Path, logf, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Sync topic bank state only — queue growth is via 목록 추가 (AI)."""
    from topic_bank_pipeline import topic_bank_sync_only

    return topic_bank_sync_only(site_id, repo, logf)


def ensure_topic_bank_sync_only(site_id: str, repo: Path, logf, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Sync topic bank state only — queue growth is via 목록 추가 (AI)."""
    from topic_bank_pipeline import topic_bank_sync_only

    return topic_bank_sync_only(site_id, repo, logf)


def ensure_site_csv_from_bank(site_id: str, repo: Path, logf, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    from topic_bank_pipeline import prepare_topics_for_generation

    env = env or {}
    content_limit = _bounded_limit(
        env, "CONTENT_LIMIT", default=DEFAULT_CONTENT_LIMIT, ceiling=MAX_CONTENT_LIMIT
    )
    guide_limit = _bounded_limit(
        env, "GUIDE_LIMIT", default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT
    )
    return prepare_topics_for_generation(
        site_id,
        repo,
        logf,
        content_limit=content_limit,
        guide_limit=guide_limit,
    )


def _places_fetch_argv(site_id: str, repo: Path) -> list[str]:
    from topic_bank import ensure_bootstrapped, queue_path

    ensure_bootstrapped(site_id, repo)
    q = queue_path(site_id, "items")
    return [
        "python3",
        "script/fetch_items_from_places.py",
        "--input",
        str(q),
        "--in-place",
    ]


def ensure_dual_csv(
    repo: Path,
    logf,
    *,
    items_rel: str,
    guides_rel: str,
    item_headers: list[str],
    guide_headers: list[str],
    item_seeds: list[dict[str, str]],
    guide_seeds: list[dict[str, str]],
    item_col: str = "Name",
    guide_col: str = "topic_en",
    expand_coords: list[dict[str, str]] | None = None,
    item_expand_seeds: list[dict[str, str]] | None = None,
    guide_expand_seeds: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    items_path = repo / items_rel
    guides_path = repo / guides_rel
    out: dict[str, Any] = {"messages": [], "expanded_items": 0, "expanded_guides": 0}
    n_items = _count_csv_rows(items_path, required_col=item_col)
    if n_items < MIN_ITEM_ROWS:
        added = _append_csv_rows(items_path, item_headers, item_seeds)
        out["seeded_items"] = added
        msg = f"{items_rel}: {n_items}행 → +{added}행 시드"
        out["messages"].append(msg)
        logf.write(msg + "\n")
    else:
        logf.write(f"{items_rel}: {n_items}행 (시드 생략)\n")

    if item_expand_seeds:
        expand_limit = _bounded_limit(
            os.environ,
            "CONTENT_LIMIT",
            default=DEFAULT_CONTENT_LIMIT,
            ceiling=MAX_CONTENT_LIMIT,
        )
        expanded = _append_csv_rows_limited(
            items_path,
            item_headers,
            item_expand_seeds,
            key_col=item_col,
            max_add=expand_limit,
        )
        out["expanded_items"] = expanded
        if expanded:
            msg = f"{items_rel}: 주간 insight 시드 +{expanded}행"
            out["messages"].append(msg)
            logf.write(msg + "\n")
    elif expand_coords and "Lat" in item_headers:
        expand_limit = _bounded_limit(
            os.environ,
            "CONTENT_LIMIT",
            default=DEFAULT_CONTENT_LIMIT,
            ceiling=MAX_CONTENT_LIMIT,
        )
        pool = list(item_seeds) + list(expand_coords)
        expanded = _append_csv_rows_by_coord(items_path, item_headers, pool, max_add=expand_limit)
        out["expanded_items"] = expanded
        if expanded:
            msg = f"{items_rel}: 주간 확장 +{expanded}행"
            out["messages"].append(msg)
            logf.write(msg + "\n")

    n_guides = _count_csv_rows(guides_path, required_col=guide_col)
    if n_guides < MIN_GUIDE_ROWS:
        added = _append_csv_rows(guides_path, guide_headers, guide_seeds)
        out["seeded_guides"] = added
        msg = f"{guides_rel}: {n_guides}행 → +{added}행 시드"
        out["messages"].append(msg)
        logf.write(msg + "\n")
    else:
        logf.write(f"{guides_rel}: {n_guides}행 (시드 생략)\n")

    guide_expand_limit = _bounded_limit(
        os.environ,
        "GUIDE_LIMIT",
        default=DEFAULT_GUIDE_LIMIT,
        ceiling=MAX_GUIDE_LIMIT,
    )
    guide_pool = EXPAND_GUIDE_SEEDS if guide_expand_seeds is None else guide_expand_seeds
    if guide_pool:
        g_added = _append_csv_rows_limited(
            guides_path,
            guide_headers,
            guide_pool,
            key_col="id",
            max_add=guide_expand_limit,
        )
        out["expanded_guides"] = g_added
        if g_added:
            msg = f"{guides_rel}: 주간 가이드 토픽 +{g_added}행"
            out["messages"].append(msg)
            logf.write(msg + "\n")

    out["item_rows"] = _count_csv_rows(items_path, required_col=item_col)
    out["guide_rows"] = _count_csv_rows(guides_path, required_col=guide_col)
    return out


def ensure_starful_csv(repo: Path, logf, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    return ensure_topic_bank_sync_only("starful.biz", repo, logf, env=env)


def ensure_hatena_csv(repo: Path, logf, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    return ensure_site_csv_from_bank("hatena", repo, logf, env=env)


def ensure_jpcampus_csv(repo: Path, logf, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    return ensure_topic_bank_sync_only("jpcampus", repo, logf, env=env)


def ensure_krcampus_csv(repo: Path, logf, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    from topic_bank_pipeline import topic_bank_release_queues

    env = env or {}
    guide_limit = _int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
    school_limit = _int_env_allow_zero(env, "SCHOOL_LIMIT", DEFAULT_KRCAMPUS_SCHOOL_LIMIT)
    university_limit = _int_env_allow_zero(env, "UNIVERSITY_LIMIT", DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT)
    return topic_bank_release_queues(
        "krcampus",
        repo,
        logf,
        content_limit=0,
        guide_limit=guide_limit,
        school_limit=school_limit,
        university_limit=university_limit,
        content_limit_each=False,
    )


def _execute_pipeline(
    site_id: str,
    repo: Path,
    *,
    ensure_fn,
    steps: list[tuple[str, str, list[str], int]],
    env: dict[str, str],
    optional_steps: list[tuple[str, str, list[str], int]] | None = None,
    extra_steps: list[tuple[str, str, list[str], int]] | None = None,
    post_steps: list[tuple[str, Callable[[Path, Any], dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    log_path = pipeline_log_path(site_id)
    steps_out: list[dict[str, Any]] = []
    optional_steps = optional_steps or []
    extra_steps = extra_steps or []
    post_steps = post_steps or []

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n\n{'#' * 60}\n# {site_id} pipeline {datetime.now():%F %T}\n")
        if site_id == "krcampus":
            logf.write(
                "run limits: "
                f"guides={env.get('GUIDE_LIMIT', '?')} "
                f"schools={env.get('SCHOOL_LIMIT', '?')} "
                f"universities={env.get('UNIVERSITY_LIMIT', '?')}\n"
            )
        if ensure_fn:
            seed_info = _call_ensure_csv(ensure_fn, repo, logf, env)
            steps_out.append({"step": "ensure_csv", "ok": True, **seed_info})
            from topic_queue_env import queue_env_for_site

            env.update(queue_env_for_site(site_id, sync=False))

        for step_id, label, argv, timeout in extra_steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r})
            if not r["ok"]:
                return _fail(site_id, steps_out, r, log_path)

        for step_id, label, argv, timeout in steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r})
            if r.get("ok"):
                try:
                    from ai_spend import record_pipeline_step

                    record_pipeline_step(site_id, step_id, env, r.get("output") or "")
                except Exception:
                    pass
            if not r["ok"]:
                return _fail(site_id, steps_out, r, log_path)

        for step_id, label, argv, timeout in optional_steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r, "optional": True})
            if not r["ok"]:
                logf.write(f"⚠ optional step failed (continuing): {label}\n")

        for step_id, fn in post_steps:
            r = fn(repo, logf)
            steps_out.append({"step": step_id, **r, "optional": True})
            if not r.get("ok"):
                logf.write(f"⚠ post step failed (continuing): {r.get('label') or step_id}\n")

        logf.write(f"\n[{datetime.now():%F %T}] Pipeline OK\n")

        warn = _content_generation_warning(steps_out)
        if warn:
            logf.write(f"⚠ content: {warn}\n")

    payload: dict[str, Any] = {
        "ok": True,
        "site_id": site_id,
        "steps": steps_out,
        "log_path": str(log_path),
        "message": f"{site_id} 콘텐츠 파이프라인 완료",
    }
    if warn:
        payload["content_warning"] = warn
        payload["message"] = f"{site_id} 완료 — {warn}"
    return _stamp_pipeline_result(payload)


def _content_generation_warning(steps: list[dict[str, Any]]) -> str | None:
    """True when generate steps ran OK but logs suggest zero new MD/posts."""
    gen_ids = {
        "guides",
        "universities",
        "items",
        "guides_md",
        "py",
        "cloud",
        "korean",
    }
    gen_steps = [s for s in steps if s.get("step") in gen_ids and s.get("ok")]
    if not gen_steps:
        return None
    saw_zero = False
    saw_gen = False
    for step in gen_steps:
        text = (step.get("output") or "").lower()
        if not text:
            continue
        if any(p in text for p in _CONTENT_ZERO_PATTERNS):
            saw_zero = True
        if any(re.search(p, text) for p in _CONTENT_GEN_PATTERNS):
            saw_gen = True
    if saw_zero and not saw_gen:
        return "이번 실행에서 신규 콘텐츠 0건 (백로그 없음 또는 이미 완료)"
    return None


def _gcs_images_dir(repo: Path, site_id: str) -> Path:
    rel = SITE_GCS_IMAGE_DIRS.get(site_id, "app/static/images")
    return repo / rel


def _starful_gcs_normalize(repo: Path, logf) -> dict[str, Any]:
    """GCS rsync 전 legacy hyphen blob 정리."""
    script = repo / "scripts/normalize_image_names.py"
    logf.write(f"\n[{datetime.now():%F %T}] starful GCS image name normalize\n")
    if not script.is_file():
        return {"ok": False, "label": "GCS normalize", "error": "normalize_image_names.py missing"}
    try:
        proc = subprocess.run(
            ["python3", str(script), "--gcs"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "label": "GCS normalize", "error": "timeout"}
    if proc.stdout:
        logf.write(proc.stdout)
    if proc.stderr:
        logf.write(proc.stderr)
    logf.flush()
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "label": "GCS normalize",
        "exit_code": proc.returncode,
        "error": "" if ok else (proc.stderr or proc.stdout or "normalize failed")[-500:],
    }


def _gcs_image_sync(repo: Path, logf, site_id: str) -> dict[str, Any]:
    """Upload site image dir to GCS; never overwrite newer GCS blobs (admin uploads)."""
    images_dir = _gcs_images_dir(repo, site_id)
    env_key = f"{site_id.upper().replace('.', '_')}_GCS_BUCKET"
    bucket = os.environ.get(env_key) or SITE_GCS_BUCKETS.get(site_id, "")
    logf.write(f"\n{'=' * 50}\n[{datetime.now():%F %T}] GCS image sync\n")
    logf.flush()
    if not bucket:
        return {"ok": False, "label": "GCS images", "error": f"no GCS bucket for {site_id}"}
    if not images_dir.is_dir():
        return {"ok": False, "label": "GCS images", "error": "images dir missing"}

    rsync_flags = ["--recursive", "--checksums-only", "--skip-if-dest-has-newer-mtime"]

    # starful: pull newer GCS → local first (admin upload → repo stays current)
    if site_id == "starful.biz":
        logf.write(f"gcloud storage rsync {bucket} {images_dir} (pull newer)\n")
        logf.flush()
        try:
            pull = subprocess.run(
                ["gcloud", "storage", "rsync", bucket, str(images_dir), *rsync_flags],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            if pull.stdout:
                logf.write(pull.stdout)
            if pull.stderr:
                logf.write(pull.stderr)
        except subprocess.TimeoutExpired:
            return {"ok": False, "label": "GCS images", "error": "pull timeout"}

    logf.write(f"gcloud storage rsync {images_dir} {bucket} (push, skip newer dest)\n")
    logf.flush()
    try:
        proc = subprocess.run(
            ["gcloud", "storage", "rsync", str(images_dir), bucket, *rsync_flags],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "label": "GCS images", "error": "timeout"}
    if proc.stdout:
        logf.write(proc.stdout)
    if proc.stderr:
        logf.write(proc.stderr)
    logf.flush()
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "label": "GCS images",
        "exit_code": proc.returncode,
        "error": "" if ok else (proc.stderr or proc.stdout or "gcloud rsync failed")[-500:],
    }


def _item_incomplete_argv(env: dict[str, str]) -> list[str]:
    return [
        "python3",
        "script/item_generator.py",
        "--limit",
        env["CONTENT_LIMIT"],
        "--incomplete-only",
    ]


def _ok_series_content_steps(
    env: dict[str, str],
    site_id: str,
    *,
    item_step: tuple[str, str, list[str], int],
    guide_first: bool = True,
    image_step: tuple[str, str, list[str], int] | None = None,
) -> list[tuple[str, str, list[str], int]]:
    guide_step = ("guides", "guide_generator", _guide_generator_argv(env, site_id), 3600)
    if guide_first:
        head: list[tuple[str, str, list[str], int]] = [guide_step, item_step]
    else:
        head = [item_step, guide_step]
    if image_step is None:
        image_step = ("images", "fetch_images", ["python3", "script/fetch_images.py"], 2400)
    return head + [
        image_step,
        ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
        ("build", "build_data", ["python3", "script/build_data.py"], 600),
    ]


def _pipeline_post_steps(site_id: str) -> list[tuple[str, Callable[[Path, Any], dict[str, Any]]]]:
    if site_id in SITE_GCS_BUCKETS:
        return [("gcs_images", lambda repo, logf, sid=site_id: _gcs_image_sync(repo, logf, sid))]
    return []


def _run_ok_site_pipeline(
    site_id: str,
    repo: Path,
    env: dict[str, str],
    *,
    ensure_fn,
    steps: list[tuple[str, str, list[str], int]],
    extra_steps: list[tuple[str, str, list[str], int]] | None = None,
) -> dict[str, Any]:
    return _execute_pipeline(
        site_id,
        repo,
        ensure_fn=ensure_fn,
        steps=steps,
        env=env,
        extra_steps=extra_steps or [],
        post_steps=_pipeline_post_steps(site_id),
    )


def _pipeline_for_site(site_id: str, repo: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or pipeline_env_for_site(site_id)
    optional: list[tuple[str, str, list[str], int]] = []
    extra: list[tuple[str, str, list[str], int]] = []
    steps: list[tuple[str, str, list[str], int]] = []

    if site_id == "okramen":
        def ensure(repo_p: Path, logf, env=None):
            return ensure_poi_site_csv("okramen", repo_p, logf, env=env)

        limit = env["CONTENT_LIMIT"]
        steps = [
            ("items", "ramen_generator", ["python3", "script/ramen_generator.py", limit], 3600),
            ("guides", "guide_generator", _guide_generator_argv(env, site_id), 3600),
            ("images_places", "fetch_images", ["python3", "script/fetch_images.py"], 2400),
            ("images", "generate_images", ["python3", "script/generate_images.py"], 2400),
            ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return _run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure, steps=steps)

    if site_id == "okonsen":
        def ensure(repo_p: Path, logf, env=None):
            return ensure_poi_site_csv("okonsen", repo_p, logf, env=env)

        limit = env["CONTENT_LIMIT"]
        steps = _ok_series_content_steps(
            env,
            site_id,
            item_step=("items", "onsen_generator", ["python3", "script/onsen_generator.py", limit], 3600),
            guide_first=False,
        )
        return _run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure, steps=steps)

    if site_id == "okcaddie":
        def ensure(repo_p: Path, logf, env=None):
            return ensure_poi_site_csv("okcaddie", repo_p, logf, env=env)

        limit = env["CONTENT_LIMIT"]
        steps = _ok_series_content_steps(
            env,
            site_id,
            item_step=("items", "course_generator", ["python3", "script/course_generator.py", limit], 3600),
            guide_first=False,
        )
        return _run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure, steps=steps)

    if site_id == "okstats":
        def ensure(repo_p: Path, logf, env=None):
            return ensure_okstats_csv(repo_p, logf, env=env)

        steps = [
            ("guides", "guide_generator", _guide_generator_argv(env, site_id), 3600),
            ("items", "insight_generator", _insight_generator_argv(env), 3600),
            ("images", "fetch_images", ["python3", "script/fetch_images.py"], 2400),
            ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return _run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure, steps=steps)

    if site_id == "starful.biz":
        steps = [
            ("guides", "generate_md_guides", ["python3", "scripts/generate_md_guides.py"], 3600),
            ("images", "generate_images", ["python3", "scripts/generate_images.py"], 600),
            ("images_opt", "resize_images", ["python3", "scripts/resize_images.py"], 900),
            ("img_names", "normalize_image_names", ["python3", "scripts/normalize_image_names.py"], 300),
            ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
        ]
        return _execute_pipeline(
            site_id,
            repo,
            ensure_fn=ensure_starful_csv,
            steps=steps,
            env=env,
            post_steps=[("gcs_normalize", lambda repo, logf: _starful_gcs_normalize(repo, logf))]
            + _pipeline_post_steps(site_id),
        )

    if site_id == "hatena":
        max_posts = env["HATENA_MAX_POSTS"]
        steps = [
            ("py", "unified_poster py", ["python3", "unified_poster.py", "py", "--max_posts", max_posts], 3600),
            ("cloud", "unified_poster cloud", ["python3", "unified_poster.py", "cloud", "--max_posts", max_posts], 3600),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure_hatena_csv, steps=steps, env=env)

    if site_id == "jpcampus":
        guide_n = _int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
        university_n = _int_env_allow_zero(env, "UNIVERSITY_LIMIT", DEFAULT_CONTENT_LIMIT)
        steps = []
        if guide_n > 0:
            steps.append(("guides", "AI guides", ["python3", "scripts/2.generate_ai_guides.py"], 3600))
        if university_n > 0:
            steps.append(
                ("universities", "universities", ["python3", "scripts/1.collect_universities.py"], 3600)
            )
        steps.extend(
            [
                ("korean", "Korean content", ["python3", "scripts/3.create_korean_content.py"], 3600),
                ("featured", "featured articles", ["python3", "scripts/auto_generate_featured.py"], 1800),
                ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
            ]
        )
        optional = [
            ("seo", "seo_guard", ["python3", "scripts/seo_guard.py"], 300),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure_jpcampus_csv, steps=steps, env=env, optional_steps=optional)

    if site_id == "krcampus":
        guide_n = _int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
        school_n = _int_env_allow_zero(env, "SCHOOL_LIMIT", DEFAULT_KRCAMPUS_SCHOOL_LIMIT)
        university_n = _int_env_allow_zero(env, "UNIVERSITY_LIMIT", DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT)
        steps = []
        if guide_n > 0:
            steps.append(("guides", "AI guides", ["python3", "scripts/2.generate_ai_guides.py"], 3600))
        if school_n > 0:
            steps.append(
                ("schools", "language schools", ["python3", "scripts/1.collect_language_schools.py"], 3600)
            )
        if university_n > 0:
            steps.append(
                ("universities", "universities", ["python3", "scripts/1.collect_universities.py"], 3600)
            )
        steps.extend(
            [
                ("japanese", "Japanese native", ["python3", "scripts/3.generate_japanese_native.py"], 3600),
                ("featured", "featured articles", ["python3", "scripts/auto_generate_featured.py"], 1800),
                ("images", "fetch_images", ["python3", "scripts/fetch_images.py"], 2400),
                ("images_opt", "optimize_images", ["python3", "scripts/optimize_images.py"], 900),
                ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
            ]
        )
        optional = [
            ("seo", "seo_guard", ["python3", "scripts/seo_guard.py"], 300),
        ]
        return _execute_pipeline(
            site_id,
            repo,
            ensure_fn=ensure_krcampus_csv,
            steps=steps,
            env=env,
            optional_steps=optional,
            post_steps=_pipeline_post_steps("krcampus"),
        )

    return {"ok": False, "error": f"no pipeline definition for {site_id}"}


def run_post_pipeline_deploy(
    site_id: str,
    *,
    on_job_started: Any = None,
) -> dict[str, Any]:
    """After content pipeline OK: git push + Cloud Build."""
    import os

    from git_ops import deploy_script_path, start_deploy, wait_for_deploy_job

    if site_id == "hatena":
        return {"ok": True, "skipped": True, "message": "Hatena: deploy.sh 없음"}

    with_git = os.environ.get("CONTENT_PIPELINE_WITH_GIT", "1").strip() not in ("0", "false", "no")
    with_deploy = os.environ.get("CONTENT_PIPELINE_WITH_DEPLOY", "1").strip() not in (
        "0",
        "false",
        "no",
    )

    svc = get_service(site_id)
    if not svc:
        return {"ok": False, "error": f"{site_id} not in sites.yaml"}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {"ok": False, "error": f"missing repo {repo}"}
    if not deploy_script_path(repo):
        return {"ok": False, "error": "deploy.sh not found"}

    started = start_deploy(
        repo,
        site_id=site_id,
        mode="deploy-only",
        with_git=with_git,
        with_deploy=with_deploy,
        include_build_data=False,
    )
    if not started.get("ok"):
        return started

    if on_job_started is not None and callable(on_job_started):
        on_job_started(started["job_id"], started)

    log_path = pipeline_log_path(site_id)
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(
            f"\n[{datetime.now():%F %T}] deploy.sh --deploy-only"
            f"{' --with-git' if with_git else ''}"
            f"{' --with-deploy' if with_deploy else ''}\n"
            f"log: {started.get('log_path')}\n"
        )

    final = wait_for_deploy_job(started["job_id"], site_id=site_id)
    final.setdefault("log_path", started.get("log_path"))
    return final


def run_pipeline(
    site_id: str,
    *,
    guide_count: int | None = None,
    school_count: int | None = None,
    university_count: int | None = None,
) -> dict[str, Any]:
    if not work_root_available():
        return {"ok": False, "error": "WORK_ROOT not available"}
    svc = get_service(site_id)
    if not svc:
        return {"ok": False, "error": f"{site_id} not in sites.yaml"}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {"ok": False, "error": f"missing repo {repo}"}
    env = pipeline_env_for_site(site_id, krcampus_defaults=False)
    try:
        from ai_spend import spend_preflight

        pf = spend_preflight()
        if pf.get("block_gemini"):
            return {"ok": False, "error": pf.get("message") or "Gemini 월 예산 초과", "ai_spend": pf.get("summary")}
    except Exception:
        pass
    if site_id == "krcampus":
        if any(x is not None for x in (guide_count, school_count, university_count)):
            guide_count = 0 if guide_count is None else guide_count
            school_count = 0 if school_count is None else school_count
            university_count = 0 if university_count is None else university_count
        limits = _apply_krcampus_run_limits(
            env,
            guide_count=guide_count,
            school_count=school_count,
            university_count=university_count,
        )
        if limits["guide"] == limits["school"] == limits["university"] == 0:
            return {
                "ok": False,
                "error": "가이드·어학원·대학 중 1개 이상 입력하세요",
            }
    elif site_id == "jpcampus" and (guide_count is not None or university_count is not None):
        g = _user_run_limit(guide_count, default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT)
        u = _user_run_limit(
            university_count,
            default=DEFAULT_CONTENT_LIMIT,
            ceiling=MAX_UNIVERSITY_LIMIT,
        )
        if g == u == 0:
            return {"ok": False, "error": "가이드·대학 중 1개 이상 입력하세요"}
        env["GUIDE_LIMIT"] = str(g)
        env["UNIVERSITY_LIMIT"] = str(u)
    return _pipeline_for_site(site_id, repo, env=env)


def _fail(site_id: str, steps: list, last: dict, log_path: Path) -> dict[str, Any]:
    return _stamp_pipeline_result(
        {
            "ok": False,
            "site_id": site_id,
            "steps": steps,
            "failed_step": last.get("label"),
            "error": last.get("error") or f"exit {last.get('exit_code')}",
            "log_path": str(log_path),
        }
    )


def tail_pipeline_log(site_id: str, *, max_chars: int = 16000) -> str:
    path = pipeline_log_path(site_id)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]


def _int_env(env: dict[str, str], key: str, default: int) -> int:
    try:
        return int(str(env.get(key, default)).strip() or default)
    except (TypeError, ValueError):
        return default


def _int_env_allow_zero(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def _user_run_limit(
    explicit: int | None,
    *,
    default: int,
    ceiling: int,
) -> int:
    if explicit is not None:
        return min(max(0, int(explicit)), ceiling)
    return min(max(0, default), ceiling)


def _bounded_limit(
    env: dict[str, str],
    key: str,
    *,
    default: int,
    ceiling: int,
) -> int:
    """Per-run limit for hub pipelines; 0 or negative → default (never unlimited)."""
    n = _int_env(env, key, default)
    if n <= 0:
        n = default
    return min(n, ceiling)


def _guide_cli_limit(env: dict[str, str], site_id: str) -> str:
    """CLI limit for guide scripts (okonsen counts files, not topics)."""
    topics = _bounded_limit(
        env, "GUIDE_LIMIT", default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT
    )
    if site_id == "okonsen":
        return str(topics * 2)
    return str(topics)


def _insight_generator_argv(env: dict[str, str]) -> list[str]:
    return [
        "python3",
        "script/insight_generator.py",
        "--batch-missing",
        env["CONTENT_LIMIT"],
    ]


def _guide_generator_argv(env: dict[str, str], site_id: str) -> list[str]:
    glimit = _guide_cli_limit(env, site_id)
    if site_id in ("okramen", "okstats"):
        return ["python3", "script/guide_generator.py", "--batch-missing", glimit]
    return ["python3", "script/guide_generator.py", glimit]


def _sanitize_pipeline_limits(env: dict[str, str]) -> None:
    """Work Hub standard per-run caps (fixed): guide 3, content 6."""
    env["CONTENT_LIMIT"] = str(DEFAULT_CONTENT_LIMIT)
    env["GUIDE_LIMIT"] = str(DEFAULT_GUIDE_LIMIT)
    env["HATENA_MAX_POSTS"] = str(
        _bounded_limit(
            env,
            "HATENA_MAX_POSTS",
            default=DEFAULT_HATENA_MAX_POSTS,
            ceiling=MAX_HATENA_MAX_POSTS,
        )
    )
    env["KOREAN_LIMIT"] = str(
        _bounded_limit(
            env,
            "KOREAN_LIMIT",
            default=DEFAULT_KOREAN_LIMIT,
            ceiling=MAX_KOREAN_LIMIT,
        )
    )
    env["JAPANESE_LIMIT"] = str(
        _bounded_limit(
            env,
            "JAPANESE_LIMIT",
            default=DEFAULT_JAPANESE_LIMIT,
            ceiling=MAX_JAPANESE_LIMIT,
        )
    )


def _apply_krcampus_run_limits(
    env: dict[str, str],
    *,
    guide_count: int | None = None,
    school_count: int | None = None,
    university_count: int | None = None,
) -> dict[str, int]:
    """KR Campus per-run caps from UI (0 = skip that step)."""
    guide_n = _user_run_limit(guide_count, default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT)
    school_n = _user_run_limit(
        school_count,
        default=DEFAULT_KRCAMPUS_SCHOOL_LIMIT,
        ceiling=MAX_SCHOOL_LIMIT,
    )
    university_n = _user_run_limit(
        university_count,
        default=DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT,
        ceiling=MAX_UNIVERSITY_LIMIT,
    )
    env["GUIDE_LIMIT"] = str(guide_n)
    env["SCHOOL_LIMIT"] = str(school_n)
    env["UNIVERSITY_LIMIT"] = str(university_n)
    env["CONTENT_LIMIT"] = str(max(school_n, university_n))
    env["JAPANESE_LIMIT"] = str(max(guide_n, school_n, university_n))
    return {"guide": guide_n, "school": school_n, "university": university_n}


def pipeline_env_for_site(site_id: str, *, krcampus_defaults: bool = True) -> dict[str, str]:
    if not work_root_available():
        return {}
    svc = get_service(site_id)
    if not svc:
        return {}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {}
    env = _merge_pipeline_env(repo)
    from topic_queue_env import queue_env_for_site

    env.update(queue_env_for_site(site_id, sync=False))
    if site_id == "krcampus" and krcampus_defaults:
        _apply_krcampus_run_limits(env)
    return env


def pipeline_run_caps(site_id: str) -> dict[str, Any]:
    """Per-run caps shown in Work Hub (only missing MD/posts are actually created)."""
    env = pipeline_env_for_site(site_id)
    item_n = _bounded_limit(
        env, "CONTENT_LIMIT", default=DEFAULT_CONTENT_LIMIT, ceiling=MAX_CONTENT_LIMIT
    )
    guide_n = _bounded_limit(
        env, "GUIDE_LIMIT", default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT
    )
    hatena_n = _bounded_limit(
        env, "HATENA_MAX_POSTS", default=DEFAULT_HATENA_MAX_POSTS, ceiling=MAX_HATENA_MAX_POSTS
    )
    korean_n = _bounded_limit(
        env, "KOREAN_LIMIT", default=DEFAULT_KOREAN_LIMIT, ceiling=MAX_KOREAN_LIMIT
    )
    japanese_n = _bounded_limit(
        env, "JAPANESE_LIMIT", default=DEFAULT_JAPANESE_LIMIT, ceiling=MAX_JAPANESE_LIMIT
    )
    parts: list[dict[str, str]] = []

    if site_id in ("okramen", "okonsen", "okcaddie"):
        item_label = {"okramen": "라멘", "okonsen": "온천", "okcaddie": "코스"}.get(site_id, "아이템")
        image_cap = (
            "Places + default 복사 + optimize"
            if site_id in ("okonsen", "okcaddie")
            else "Imagen + optimize"
        )
        parts = [
            {
                "label": "가이드",
                "cap": f"토픽 {guide_n}개 · 최대 {guide_n * 2} MD",
                "note": "없는 en/ko만",
            },
            {
                "label": item_label,
                "cap": f"CSV {item_n}행 · 최대 {item_n * 2} MD",
                "note": "없는 en/ko만",
            },
            {"label": "이미지", "cap": image_cap, "note": "신규 MD만"},
            {"label": "빌드", "cap": "build_data 1회", "note": ""},
            {"label": "배포", "cap": "git + GCS + Cloud Build", "note": "생성 성공 후"},
        ]
    elif site_id == "okstats":
        parts = [
            {"label": "인사이트", "cap": f"큐 {item_n}행 · 최대 {item_n} MD", "note": "토픽뱅크 → AI"},
            {"label": "가이드", "cap": f"토픽 {guide_n}개", "note": "없는 .md만"},
            {"label": "이미지", "cap": "Imagen + optimize", "note": "신규 MD만"},
            {"label": "빌드", "cap": "build_data 1회", "note": ""},
            {"label": "GCS", "cap": "statfacts/", "note": "생성 후"},
            {"label": "배포", "cap": "git + Cloud Build", "note": "생성 성공 후"},
        ]
    elif site_id == "starful.biz":
        parts = [
            {"label": "가이드 MD", "cap": f"최대 {item_n}건", "note": "없는 MD만"},
            {"label": "이미지", "cap": "default 복사 + resize + 이름 정규화", "note": "snake_case"},
            {"label": "빌드", "cap": "build_data 1회", "note": ""},
            {"label": "GCS", "cap": "img → starful-biz-assets", "note": "생성 후"},
            {"label": "배포", "cap": "git + Cloud Build", "note": "생성 성공 후"},
        ]
    elif site_id == "hatena":
        parts = [
            {"label": "Python", "cap": f"최대 {hatena_n}건", "note": "신규 포스트"},
            {"label": "Cloud", "cap": f"최대 {hatena_n}건", "note": f"합 {hatena_n * 2}건"},
        ]
    elif site_id == "jpcampus":
        parts = [
            {"label": "가이드 AI", "cap": f"토픽 {guide_n}개", "note": "없는 가이드"},
            {"label": "대학", "cap": "univ_list_100.csv", "note": "AI univ_*.md"},
            {"label": "한국어", "cap": f"원본 {korean_n}건 · 최대 {korean_n} MD", "note": "없는 *_kr.md만"},
            {"label": "featured", "cap": "토픽별 고정", "note": ""},
            {"label": "빌드", "cap": "build_data 1회", "note": "seo_guard 선택"},
            {"label": "배포", "cap": "git + Cloud Build", "note": "생성 성공 후"},
        ]
    elif site_id == "krcampus":
        school_n = _int_env_allow_zero(env, "SCHOOL_LIMIT", DEFAULT_KRCAMPUS_SCHOOL_LIMIT)
        university_n = _int_env_allow_zero(env, "UNIVERSITY_LIMIT", DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT)
        parts = [
            {"label": "가이드 EN", "cap": f"토픽 {guide_n}개", "note": "토픽뱅크 큐"},
            {"label": "어학원 EN", "cap": f"최대 {school_n}개", "note": "language_schools 큐"},
            {"label": "대학 EN", "cap": f"최대 {university_n}개", "note": "universities 큐"},
            {"label": "日本語", "cap": f"종류별 {japanese_n}개", "note": "신규 *_ja 네이티브"},
            {"label": "이미지", "cap": "Places + default 복사 + optimize", "note": "school/univ MD"},
            {"label": "빌드", "cap": "build_data", "note": ""},
            {"label": "GCS", "cap": "krcampus/", "note": "생성 후"},
            {"label": "배포", "cap": "git + Cloud Build", "note": "생성 성공 후"},
        ]

    summary = " · ".join(f"{p['label']} {p['cap']}" for p in parts[:3])
    if len(parts) > 3:
        summary += " …"
    return {"parts": parts, "summary": summary or "—"}


def _latest_pipeline_section(log_text: str, site_id: str = "") -> str:
    if not log_text:
        return ""
    if site_id:
        pattern = rf"\n#+ *\n# {re.escape(site_id)} pipeline "
    else:
        pattern = r"\n#+ *\n# .+ pipeline "
    matches = list(re.finditer(pattern, log_text))
    if not matches:
        return log_text
    return log_text[matches[-1].start():]


def _extract_created_from_log(log_text: str, *, site_id: str = "") -> list[str]:
    """Parse generator output lines for files created in the latest pipeline run."""
    section = _latest_pipeline_section(log_text, site_id)
    created: list[str] = []
    seen: set[str] = set()
    if not log_text:
        return created
    for line in section.splitlines():
        for pat in (
            r"✅ \[Done\] (\S+)",
            r"✅ Image generated: (\S+)\.jpg",
        ):
            m = re.search(pat, line)
            if not m:
                continue
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            created.append(name)
    return created


def _label_created_item(name: str) -> str:
    if name.endswith(".jpg"):
        return f"이미지 · {name}"
    if name.endswith("_en.md") or name.endswith("_ko.md"):
        stem = name.replace("_en.md", "").replace("_ko.md", "")
        if stem.startswith("guide_"):
            return f"가이드 · {stem.replace('guide_', '')}"
        return f"MD · {stem}"
    if name.endswith(".md"):
        return f"MD · {name.replace('.md', '')}"
    if "." not in name:
        return f"이미지 · {name}.jpg"
    return name


def summarize_pipeline_status(status: dict[str, Any] | None, log_text: str = "") -> dict[str, Any]:
    """Short result for UI after a pipeline run."""
    lines: list[str] = []
    title = "대기"
    ok: bool | None = None

    if status:
        ok = status.get("ok")
        if ok is True:
            title = "완료"
            if status.get("content_warning"):
                title = "완료 (0건)"
        elif ok is False:
            title = "실패"
            failed = status.get("failed_step") or status.get("error") or ""
            if failed:
                lines.append(f"중단: {str(failed)[:120]}")

        if status.get("content_warning"):
            lines.append(f"⚠ {status['content_warning']}")
        deploy = status.get("deploy") or {}
        if deploy.get("skipped"):
            lines.append("— deploy: Hatena (생략)")
        elif deploy:
            if deploy.get("ok") is True or deploy.get("state") == "success":
                lines.append(f"✓ deploy · {deploy.get('message') or '완료'}")
            else:
                lines.append(f"✗ deploy · {deploy.get('message') or deploy.get('error') or '실패'}")

        for step in status.get("steps") or []:
            name = step.get("label") or step.get("step") or "?"
            if step.get("ok") is True:
                extra = []
                if step.get("item_rows"):
                    extra.append(f"items {step['item_rows']}행")
                if step.get("guide_rows"):
                    extra.append(f"guides {step['guide_rows']}행")
                if step.get("seeded_items"):
                    extra.append(f"시드 +{step['seeded_items']}")
                suffix = f" ({', '.join(extra)})" if extra else ""
                lines.append(f"✓ {name}{suffix}")
            elif step.get("ok") is False:
                code = step.get("exit_code")
                lines.append(f"✗ {name}" + (f" (exit {code})" if code is not None else ""))

    if log_text:
        site_id = str((status or {}).get("site_id") or "")
        created = _extract_created_from_log(log_text, site_id=site_id)
        for pat, label in (
            (r"Starting generation for (\d+) guide files", "가이드 생성 {0}건"),
            (r"Starting generation for (\d+) files", "아이템 생성 {0}건"),
            (r"No new guides to generate", "가이드: 신규 없음"),
            (r"No new items to generate", "아이템: 신규 없음"),
            (r"Wrote (\d+) rows", "CSV {0}행 기록"),
            (r"Pipeline OK", "파이프라인 정상 종료"),
        ):
            m = re.search(pat, log_text)
            if m:
                msg = label.format(m.group(1)) if "{0}" in label and m.lastindex else label
                if msg not in lines:
                    lines.append(msg)

    snippet = _log_snippet(log_text)
    site_id = str((status or {}).get("site_id") or "")
    created = _extract_created_from_log(log_text, site_id=site_id)
    return {
        "title": title,
        "ok": ok,
        "lines": lines[:12],
        "log_snippet": snippet,
        "created_items": created,
        "created_labels": [_label_created_item(n) for n in created],
    }


def _log_snippet(log_text: str, *, max_lines: int = 14) -> str:
    if not log_text:
        return ""
    picked: list[str] = []
    for line in log_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[") and "]" in s[:30]:
            picked.append(s)
        elif any(
            k in s
            for k in (
                "Starting generation",
                "No new",
                "Pipeline OK",
                "Failed",
                "Wrote ",
                "✨",
                "🔔",
                "✅",
                "❌",
                "⚠",
            )
        ):
            picked.append(s)
    if not picked:
        picked = [ln.strip() for ln in log_text.splitlines() if ln.strip()][-max_lines:]
    return "\n".join(picked[-max_lines:])


def _call_ensure_csv(ensure_fn, repo: Path, logf, env: dict[str, str]) -> dict[str, Any]:
    try:
        return ensure_fn(repo, logf, env=env)
    except TypeError:
        return ensure_fn(repo, logf)


def _csv_expand_rows_added(info: dict[str, Any]) -> int:
    if "rows_added" in info:
        return int(info.get("rows_added") or 0)
    bank = int(info.get("bank_rows_added") or 0)
    return bank + int(info.get("expanded") or 0) + int(info.get("expanded_items") or 0) + int(info.get("expanded_guides") or 0)


def run_csv_expand(
    site_id: str,
    *,
    insight_count: int | None = None,
    guide_count: int | None = None,
    school_count: int | None = None,
    university_count: int | None = None,
) -> dict[str, Any]:
    """Run CSV seed/expansion only (no content generation)."""
    if not work_root_available():
        return {"ok": False, "error": "WORK_ROOT not available"}
    svc = get_service(site_id)
    if not svc:
        return {"ok": False, "error": f"{site_id} not in sites.yaml"}
    if site_id not in CONTENT_PIPELINES:
        return {"ok": False, "error": "unknown pipeline"}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {"ok": False, "error": f"missing repo {repo}"}

    log_path = pipeline_log_path(site_id)
    messages: list[str] = []

    class _Log:
        def write(self, s: str) -> None:
            if s.strip():
                messages.append(s.rstrip())

        def flush(self) -> None:
            pass

    logf = _Log()

    if not banks_for_site(site_id):
        return {"ok": False, "error": f"no topic bank for {site_id}"}

    if site_id == "okstats":
        from statfacts_topic_ai import (
            DEFAULT_GUIDE_COUNT,
            DEFAULT_INSIGHT_COUNT,
            append_statfacts_topics,
        )

        i_n = insight_count if insight_count is not None else DEFAULT_INSIGHT_COUNT
        g_n = guide_count if guide_count is not None else DEFAULT_GUIDE_COUNT
        info = append_statfacts_topics(
            site_id,
            repo,
            logf,
            insight_count=i_n,
            guide_count=g_n,
        )
        if not info.get("ok"):
            return info
        messages.extend(info.get("messages") or [])
    elif site_id in ("okramen", "okonsen", "okcaddie"):
        from poi_topic_ai import (
            DEFAULT_GUIDE_COUNT,
            DEFAULT_ITEM_COUNT,
            append_poi_topics,
        )

        item_n = insight_count if insight_count is not None else DEFAULT_ITEM_COUNT
        g_n = guide_count if guide_count is not None else DEFAULT_GUIDE_COUNT
        info = append_poi_topics(
            site_id,
            repo,
            logf,
            item_count=item_n,
            guide_count=g_n,
        )
        if not info.get("ok"):
            return info
        messages.extend(info.get("messages") or [])
    elif site_id == "starful.biz":
        from starful_topic_ai import DEFAULT_POSITION_COUNT, append_starful_positions

        p_n = insight_count if insight_count is not None else DEFAULT_POSITION_COUNT
        info = append_starful_positions(site_id, repo, logf, position_count=p_n)
        if not info.get("ok"):
            return info
        messages.extend(info.get("messages") or [])
    elif site_id == "jpcampus":
        from campus_topic_ai import (
            DEFAULT_GUIDE_COUNT,
            DEFAULT_UNIVERSITY_COUNT,
            append_jpcampus_topics,
        )

        g_n = guide_count if guide_count is not None else DEFAULT_GUIDE_COUNT
        u_n = university_count if university_count is not None else DEFAULT_UNIVERSITY_COUNT
        info = append_jpcampus_topics(
            site_id,
            repo,
            logf,
            guide_count=g_n,
            university_count=u_n,
        )
        if not info.get("ok"):
            return info
        messages.extend(info.get("messages") or [])
    elif site_id == "krcampus":
        from campus_topic_ai import (
            DEFAULT_GUIDE_COUNT,
            DEFAULT_SCHOOL_COUNT,
            DEFAULT_UNIVERSITY_COUNT,
            append_krcampus_topics,
        )

        g_n = guide_count if guide_count is not None else DEFAULT_GUIDE_COUNT
        s_n = school_count if school_count is not None else DEFAULT_SCHOOL_COUNT
        u_n = university_count if university_count is not None else DEFAULT_UNIVERSITY_COUNT
        info = append_krcampus_topics(
            site_id,
            repo,
            logf,
            guide_count=g_n,
            school_count=s_n,
            university_count=u_n,
        )
        if not info.get("ok"):
            return info
        messages.extend(info.get("messages") or [])
    elif site_id == "hatena":
        from topic_bank_pipeline import topic_bank_release_and_sync

        env = pipeline_env_for_site(site_id)
        content_limit = _bounded_limit(
            env, "CONTENT_LIMIT", default=DEFAULT_CONTENT_LIMIT, ceiling=MAX_CONTENT_LIMIT
        )
        guide_limit = _bounded_limit(
            env, "GUIDE_LIMIT", default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT
        )
        info = topic_bank_release_and_sync(
            site_id,
            repo,
            logf,
            content_limit=content_limit,
            guide_limit=guide_limit,
        )
        messages.extend(info.get("messages") or [])
        for bank_id, n in (info.get("bank_appended") or {}).items():
            if n:
                messages.append(f"토픽뱅크 {bank_id}: 시드 +{n}행")
    else:
        return {"ok": False, "error": f"목록 추가 미지원: {site_id}"}

    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(f"\n[{datetime.now():%F %T}] CSV expand (manual)\n")
        for line in messages:
            lf.write(line + "\n")

    rows_added = _csv_expand_rows_added(info)
    if site_id in ("okstats", "okramen", "okonsen", "okcaddie", "starful.biz", "jpcampus", "krcampus"):
        try:
            from ai_spend import record_topic_seed

            record_topic_seed(site_id)
        except Exception:
            pass
    return {"ok": True, "site_id": site_id, "rows_added": rows_added, "messages": messages, **info}


CONTENT_PIPELINES: dict[str, dict[str, str]] = {
    "okramen": {"label": "OK Ramen", "description": "라멘 · 가이드 AI + build"},
    "okonsen": {"label": "OK Onsen", "description": "온천 · 가이드 AI + build"},
    "okcaddie": {"label": "OK Caddie", "description": "골프 · 가이드 AI + build"},
    "okstats": {"label": "StatFacts", "description": "인사이트 AI + 가이드 · Imagen · build · GCS"},
    "starful.biz": {"label": "Starful Biz", "description": "포지션 가이드 · 이미지 · build · GCS"},
    "hatena": {"label": "Hatena · okpy", "description": "Python / Cloud 포스트"},
    "jpcampus": {"label": "JP Campus", "description": "가이드 · 대학 · 한국어 · featured · build"},
    "krcampus": {"label": "KR Campus", "description": "韓国留学 · 가이드 · 어학원/대학 · EN/JA · build"},
}
