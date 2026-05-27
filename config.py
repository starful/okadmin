"""Work hub / OK Admin configuration."""
from __future__ import annotations

import os
from functools import lru_cache
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
    local = OKADMIN_ROOT / "ops"
    if local.is_dir():
        return local
    legacy = WORK_ROOT / "ops"
    return legacy if legacy.is_dir() else local


OPS_ROOT = _resolve_ops_root()
AUTO_REGISTER_SCRIPT = OPS_ROOT / "auto_register.sh"
AUTO_REGISTER_STATUS_SCRIPT = OPS_ROOT / "show_auto_register_status.sh"
STATE_FILE = OPS_ROOT / "state" / "auto-register.last-run"
LOG_DIR = OPS_ROOT / "logs"

AUTO_REGISTER_SCHEDULE = [
    ("Mon", "okramen"),
    ("Tue", "okonsen"),
    ("Wed", "okcaddie"),
    ("Thu", "oksushi"),
    ("Fri", "starful.biz"),
    ("Sat", "jpcampus"),
    ("Sun", "hatena · okpy.net"),
]

# 예전 GCal 서브캘린더 색과 동일 계열
SITE_COLORS: dict[str, str] = {
    "jpcampus": "#33b679",
    "hatena": "#f4511e",
    "okadmin": "#9e9e9e",
    "okcaddie": "#039be5",
    "okcafejp": "#8e24aa",
    "okonsen": "#e67c73",
    "okramen": "#f6bf26",
    "oksushi": "#0b8043",
    "oktemplate": "#3f51b5",
    "starful.biz": "#7986cb",
    "starful.net": "#d50000",
}

EVENT_KINDS = ["todo", "auto_register", "git_push", "gsc", "manual", "deploy", "content", "other"]
# 달력: 오늘 기준 앞뒤 N일
CALENDAR_WINDOW_DAYS = 14

EVENT_COLORS = {
    "todo": "#818cf8",
    "auto_register": "#22c55e",
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
    "oksushi",
    "okcafejp",
    "starful_biz",
)
DEFAULT_GCS_IMAGE_SITE = "okonsen"


def image_site_key(site_id: str) -> str:
    if site_id == "starful.biz":
        return "starful_biz"
    return site_id


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    if not SITES_YAML.is_file():
        return {"work_root": str(WORK_ROOT), "services": []}
    data = yaml.safe_load(SITES_YAML.read_text(encoding="utf-8")) or {}
    return data


def list_services() -> list[dict[str, Any]]:
    return list(load_registry().get("services") or [])


def get_service(site_id: str) -> dict[str, Any] | None:
    for svc in list_services():
        if svc.get("id") == site_id:
            return svc
    return None


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
