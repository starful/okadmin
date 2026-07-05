"""Hub pipeline per-run limits and env helpers."""
from __future__ import annotations

import os
from pathlib import Path

# Hub one-click caps: 가이드 3토픽(최대 6 MD) · 아이템 6행(최대 12 MD en/ko).
MIN_ITEM_ROWS = 8
MIN_GUIDE_ROWS = 3

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


def int_env(env: dict[str, str], key: str, default: int) -> int:
    try:
        return int(str(env.get(key, default)).strip() or default)
    except (TypeError, ValueError):
        return default


def int_env_allow_zero(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def user_run_limit(
    explicit: int | None,
    *,
    default: int,
    ceiling: int,
) -> int:
    if explicit is not None:
        return min(max(0, int(explicit)), ceiling)
    return min(max(0, default), ceiling)


def bounded_limit(
    env: dict[str, str],
    key: str,
    *,
    default: int,
    ceiling: int,
) -> int:
    """Per-run limit for hub pipelines; 0 or negative → default (never unlimited)."""
    n = int_env(env, key, default)
    if n <= 0:
        n = default
    return min(n, ceiling)


def sanitize_pipeline_limits(env: dict[str, str]) -> None:
    """Work Hub standard per-run caps (fixed): guide 3, content 6."""
    env["CONTENT_LIMIT"] = str(DEFAULT_CONTENT_LIMIT)
    env["GUIDE_LIMIT"] = str(DEFAULT_GUIDE_LIMIT)
    env["HATENA_MAX_POSTS"] = str(
        bounded_limit(
            env,
            "HATENA_MAX_POSTS",
            default=DEFAULT_HATENA_MAX_POSTS,
            ceiling=MAX_HATENA_MAX_POSTS,
        )
    )
    env["KOREAN_LIMIT"] = str(
        bounded_limit(
            env,
            "KOREAN_LIMIT",
            default=DEFAULT_KOREAN_LIMIT,
            ceiling=MAX_KOREAN_LIMIT,
        )
    )
    env["JAPANESE_LIMIT"] = str(
        bounded_limit(
            env,
            "JAPANESE_LIMIT",
            default=DEFAULT_JAPANESE_LIMIT,
            ceiling=MAX_JAPANESE_LIMIT,
        )
    )


def apply_krcampus_run_limits(
    env: dict[str, str],
    *,
    guide_count: int | None = None,
    school_count: int | None = None,
    university_count: int | None = None,
) -> dict[str, int]:
    """KR Campus per-run caps from UI (0 = skip that step)."""
    guide_n = user_run_limit(guide_count, default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT)
    school_n = user_run_limit(
        school_count,
        default=DEFAULT_KRCAMPUS_SCHOOL_LIMIT,
        ceiling=MAX_SCHOOL_LIMIT,
    )
    university_n = user_run_limit(
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


def merge_pipeline_env(repo: Path) -> dict[str, str]:
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
    sanitize_pipeline_limits(env)
    return env
