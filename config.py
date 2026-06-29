"""Work hub / OK Admin configuration."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

OKADMIN_ROOT = Path(__file__).resolve().parent

# auth 등 다른 모듈 import 전에 .env 로드
if os.environ.get("K_SERVICE") is None:
    try:
        from dotenv import load_dotenv

        load_dotenv(OKADMIN_ROOT / ".env")
    except ImportError:
        pass
WORK_ROOT = Path(os.environ.get("WORK_ROOT", "/opt/work"))
SITES_YAML = Path(os.environ.get("SITES_YAML", WORK_ROOT / "sites.yaml"))

COL_TODOS = "work_hub_todos"
COL_OPS_EVENTS = "work_hub_ops_events"
COL_META = "work_hub_meta"
COL_GSC_ACTIONS = "work_hub_gsc_actions"
META_DOC_ID = "settings"

def _resolve_ops_root() -> Path:
    return OKADMIN_ROOT / "ops"


OPS_ROOT = _resolve_ops_root()
LOG_DIR = OPS_ROOT / "logs"

# 예전 GCal 서브캘린더 색과 동일 계열
SITE_COLORS: dict[str, str] = {
    "jpcampus": "#33b679",
    "krcampus": "#c8102e",
    "hatena": "#f4511e",
    "okadmin": "#9e9e9e",
    "okcaddie": "#039be5",
    "okonsen": "#e67c73",
    "okramen": "#f6bf26",
    "starful.biz": "#7986cb",
    "okstats": "#2563eb",
}

EVENT_KINDS = ["todo", "git_push", "gsc", "manual", "deploy", "content", "other"]
# 달력 UI에 표시할 작업 종류 (SEO 콘텐츠 + GSC SEO)
CALENDAR_VISIBLE_KINDS = frozenset({"content", "gsc"})
SCHEDULE_EVENT_KINDS = ["content", "gsc"]
# 달력: 오늘 기준 앞뒤 N일
CALENDAR_WINDOW_DAYS = 7

EVENT_COLORS = {
    "todo": "#818cf8",
    "git_push": "#60a5fa",
    "gsc": "#f59e0b",
    "manual": "#7F77DD",
    "deploy": "#1D9E75",
    "content": "#EF9F27",
    "other": "#888780",
}

PLACES_TIMEOUT = 10
PROTECTED_IMAGES = {"logo.png", "logo.svg", "favicon.ico", "favicons.ico", "og_image.png"}

# GCS 이미지 탭: 예전 OK Admin 순서 (sites.yaml 순서와 무관)
GCS_IMAGE_SITE_ORDER = (
    "okonsen",
    "okramen",
    "okcaddie",
    "okstats",
    "krcampus",
    "starful_biz",
)
DEFAULT_GCS_IMAGE_SITE = "okonsen"


def image_site_key(site_id: str) -> str:
    if site_id == "starful.biz":
        return "starful_biz"
    return site_id


_registry_cache: tuple[float, dict[str, Any]] | None = None


def load_registry() -> dict[str, Any]:
    """Load sites.yaml; reload when the file mtime changes (no server restart needed)."""
    global _registry_cache
    mtime = SITES_YAML.stat().st_mtime if SITES_YAML.is_file() else 0.0
    if _registry_cache is not None and _registry_cache[0] == mtime:
        return _registry_cache[1]
    if not SITES_YAML.is_file():
        data: dict[str, Any] = {"work_root": str(WORK_ROOT), "services": []}
    else:
        data = yaml.safe_load(SITES_YAML.read_text(encoding="utf-8")) or {}
    _registry_cache = (mtime, data)
    return data


def list_services() -> list[dict[str, Any]]:
    return list(load_registry().get("services") or [])


def get_service(site_id: str) -> dict[str, Any] | None:
    for svc in list_services():
        if svc.get("id") == site_id:
            return svc
    return None


def site_favicon_urls() -> dict[str, str]:
    """Production favicon URL per site for calendar chips."""
    out: dict[str, str] = {}
    for svc in list_services():
        sid = svc.get("id") or ""
        prod = (svc.get("links") or {}).get("production") or ""
        if sid and prod:
            out[sid] = f"{str(prod).rstrip('/')}/static/images/favicon.ico"
    return out


def gcs_sites() -> dict[str, dict[str, Any]]:
    """Image-admin sites keyed by id (legacy okadmin tab order)."""
    by_key: dict[str, dict[str, Any]] = {}
    for svc in list_services():
        gcs = svc.get("gcs")
        if not gcs:
            continue
        sid = svc["id"]
        image_key = image_site_key(sid)
        by_key[image_key] = {
            "label": svc.get("label", sid),
            "bucket": gcs["bucket"],
            "prefix": gcs.get("prefix", ""),
            "search_type": gcs.get("search_type", []),
        }
        if gcs.get("prompt_template"):
            by_key[image_key]["prompt_template"] = gcs["prompt_template"]

    ordered: dict[str, dict[str, Any]] = {}
    for key in GCS_IMAGE_SITE_ORDER:
        if key in by_key:
            ordered[key] = by_key[key]
    for key, cfg in by_key.items():
        if key not in ordered:
            ordered[key] = cfg
    return ordered


def repo_path(svc: dict[str, Any]) -> Path:
    root = load_registry().get("work_root") or str(WORK_ROOT)
    return Path(root) / svc.get("path", svc["id"])


def work_root_available() -> bool:
    root = Path(load_registry().get("work_root") or WORK_ROOT)
    return root.is_dir() and OPS_ROOT.is_dir()


# Phase 2: 사이트별 콘텐츠 스크립트 (WORK_ROOT 기준)
CONTENT_JOBS: dict[str, list[dict[str, str]]] = {
    "starful.biz": [
        {
            "id": "md_guides",
            "label": "MD 가이드 생성",
            "command": "python3 scripts/generate_md_guides.py",
        },
        {
            "id": "build_data",
            "label": "build_data",
            "command": "python3 scripts/build_data.py",
        },
    ],
    "hatena": [
        {
            "id": "unified_poster",
            "label": "unified_poster (CSV 토픽)",
            "command": "python3 unified_poster.py",
        },
    ],
    "jpcampus": [
        {
            "id": "generate_guides",
            "label": "AI 가이드 생성",
            "command": "python3 scripts/2.generate_ai_guides.py",
        },
        {
            "id": "korean_content",
            "label": "한국어 콘텐츠",
            "command": "python3 scripts/3.create_korean_content.py",
        },
        {
            "id": "featured",
            "label": "featured 생성",
            "command": "python3 scripts/auto_generate_featured.py",
        },
        {
            "id": "build_data",
            "label": "build_data",
            "command": "python3 scripts/build_data.py",
        },
        {
            "id": "seo_guard",
            "label": "seo_guard",
            "command": "python3 scripts/seo_guard.py",
        },
    ],
}

# CSV 편집 (콘텐츠 페이지) — okadmin data/topic_banks (site repo CSV는 레거시)
CONTENT_CSV_FILES: dict[str, list[dict[str, Any]]] = {
    "hatena": [
        {
            "id": "python",
            "label": "python.csv",
            "rel_path": "csv/python.csv",
            "headers": ["lib_name"],
        },
        {
            "id": "cloud",
            "label": "cloud.csv",
            "rel_path": "csv/cloud.csv",
            "headers": ["Topic"],
        },
        {
            "id": "positions",
            "label": "positions.csv",
            "rel_path": "csv/positions.csv",
            "headers": ["position_name"],
        },
    ],
    "okramen": [
        {
            "id": "ramens",
            "label": "ramens.csv",
            "rel_path": "script/csv/ramens.csv",
            "headers": ["Name", "Lat", "Lng", "Address", "Thumbnail", "Features", "Agoda"],
        },
        {
            "id": "guides",
            "label": "guides.csv",
            "rel_path": "script/csv/guides.csv",
            "headers": ["id", "topic_en", "topic_ko", "keywords"],
        },
    ],
    "okonsen": [
        {
            "id": "onsens",
            "label": "onsens.csv",
            "rel_path": "script/csv/onsens.csv",
            "headers": ["Name", "Lat", "Lng", "Address", "Thumbnail", "Features", "Agoda"],
        },
        {
            "id": "guides",
            "label": "guides.csv",
            "rel_path": "script/csv/guides.csv",
            "headers": ["id", "topic_en", "topic_ko", "keywords"],
        },
    ],
    "okcaddie": [
        {
            "id": "courses",
            "label": "courses.csv",
            "rel_path": "script/csv/courses.csv",
            "headers": ["Name", "Lat", "Lng", "Address", "Features", "Booking"],
        },
        {
            "id": "guides",
            "label": "guides.csv",
            "rel_path": "script/csv/guides.csv",
            "headers": ["id", "topic_en", "topic_ko", "keywords"],
        },
    ],
    "starful.biz": [
        {
            "id": "positions",
            "label": "positions.csv",
            "rel_path": "scripts/data/positions.csv",
            "headers": ["position_name"],
        },
    ],
    "jpcampus": [
        {
            "id": "guide_topics",
            "label": "guide_topics.csv",
            "rel_path": "data/guide_topics.csv",
            "headers": ["slug", "category", "title", "description", "prompt"],
        },
    ],
    "krcampus": [
        {
            "id": "guide_topics",
            "label": "guide_topics.csv",
            "rel_path": "data/guide_topics.csv",
            "headers": ["slug", "category", "title", "description", "prompt"],
        },
        {
            "id": "language_schools",
            "label": "language_schools.csv",
            "rel_path": "data/language_schools.csv",
            "headers": ["name_ko", "name_en", "region", "city"],
        },
        {
            "id": "universities",
            "label": "universities.csv",
            "rel_path": "data/universities.csv",
            "headers": ["name_ko", "name_en", "region"],
        },
    ],
    "okstats": [
        {
            "id": "insights",
            "label": "insights.csv",
            "rel_path": "script/csv/insights.csv",
            "headers": [
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
            ],
        },
        {
            "id": "guides",
            "label": "guides.csv",
            "rel_path": "script/csv/guides.csv",
            "headers": ["id", "topic_en", "topic_ko", "keywords"],
        },
    ],
}
