"""Content backlog snapshots (CSV vs MD). Refreshed on demand or after pipeline — not on every page load."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from config import get_service, repo_path, work_root_available
from pipeline_specs import POI_SITES

PLACEHOLDER_IMAGE_MAX = 50_000


def _log_dir() -> Path:
    base = Path(__file__).resolve().parent / "data" / "content_logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def backlog_snapshot_path(site_id: str) -> Path:
    return _log_dir() / f"{site_id}_backlog.json"


def read_backlog_snapshot(site_id: str) -> dict[str, Any] | None:
    path = backlog_snapshot_path(site_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_backlog_snapshot(site_id: str, data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    out.setdefault("site_id", site_id)
    if "computed_at" not in out:
        out["computed_at"] = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    backlog_snapshot_path(site_id).write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out



def _preview_csv_expand(site_id: str, repo: Path) -> dict[str, Any]:
    """How many rows topic bank would release (pending, capped by limits)."""
    from content_pipeline import (
        DEFAULT_CONTENT_LIMIT,
        DEFAULT_GUIDE_LIMIT,
        MAX_CONTENT_LIMIT,
        MAX_GUIDE_LIMIT,
        _bounded_limit,
        pipeline_env_for_site,
    )

    if site_id == "okstats":
        from statfacts_topic_ai import DEFAULT_GUIDE_COUNT, DEFAULT_INSIGHT_COUNT

        return {
            "items_expandable": DEFAULT_INSIGHT_COUNT,
            "guides_expandable": DEFAULT_GUIDE_COUNT,
            "statfacts_ai_queue": True,
            "ai_queue": True,
            "default_insights": DEFAULT_INSIGHT_COUNT,
            "default_guides": DEFAULT_GUIDE_COUNT,
        }

    if site_id in POI_SITES:
        from poi_topic_ai import DEFAULT_GUIDE_COUNT, DEFAULT_ITEM_COUNT

        return {
            "items_expandable": DEFAULT_ITEM_COUNT,
            "guides_expandable": DEFAULT_GUIDE_COUNT,
            "ai_queue": True,
            "default_items": DEFAULT_ITEM_COUNT,
            "default_guides": DEFAULT_GUIDE_COUNT,
        }

    if site_id == "starful.biz":
        from starful_topic_ai import DEFAULT_POSITION_COUNT

        return {
            "items_expandable": DEFAULT_POSITION_COUNT,
            "guides_expandable": 0,
            "ai_queue": True,
            "queue_mode": "positions",
            "default_positions": DEFAULT_POSITION_COUNT,
        }

    if site_id == "jpcampus":
        from campus_topic_ai import DEFAULT_GUIDE_COUNT, DEFAULT_UNIVERSITY_COUNT

        return {
            "items_expandable": DEFAULT_UNIVERSITY_COUNT,
            "guides_expandable": DEFAULT_GUIDE_COUNT,
            "ai_queue": True,
            "queue_mode": "jpcampus",
            "default_guides": DEFAULT_GUIDE_COUNT,
            "default_universities": DEFAULT_UNIVERSITY_COUNT,
        }

    if site_id == "krcampus":
        from campus_topic_ai import (
            DEFAULT_GUIDE_COUNT,
            DEFAULT_SCHOOL_COUNT,
            DEFAULT_UNIVERSITY_COUNT,
        )

        return {
            "items_expandable": DEFAULT_SCHOOL_COUNT + DEFAULT_UNIVERSITY_COUNT,
            "guides_expandable": DEFAULT_GUIDE_COUNT,
            "ai_queue": True,
            "queue_mode": "krcampus",
            "default_guides": DEFAULT_GUIDE_COUNT,
            "default_schools": DEFAULT_SCHOOL_COUNT,
            "default_universities": DEFAULT_UNIVERSITY_COUNT,
        }

    from topic_bank_pipeline import topic_bank_expand_preview

    env = pipeline_env_for_site(site_id)
    item_cap = _bounded_limit(env, "CONTENT_LIMIT", default=DEFAULT_CONTENT_LIMIT, ceiling=MAX_CONTENT_LIMIT)
    guide_cap = _bounded_limit(env, "GUIDE_LIMIT", default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT)
    return topic_bank_expand_preview(site_id, repo, content_limit=item_cap, guide_limit=guide_cap)


def compute_backlog(site_id: str) -> dict[str, Any]:
    if not work_root_available():
        return {"ok": False, "error": "WORK_ROOT not available"}
    svc = get_service(site_id)
    if not svc:
        return {"ok": False, "error": f"{site_id} not in sites.yaml"}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {"ok": False, "error": f"missing repo {repo}"}

    from content_pipeline import (
        pipeline_env_for_site,
        _bounded_limit,
        DEFAULT_CONTENT_LIMIT,
        DEFAULT_GUIDE_LIMIT,
        DEFAULT_KOREAN_LIMIT,
        MAX_CONTENT_LIMIT,
        MAX_GUIDE_LIMIT,
        MAX_KOREAN_LIMIT,
    )

    env = pipeline_env_for_site(site_id)
    item_limit = _bounded_limit(env, "CONTENT_LIMIT", default=DEFAULT_CONTENT_LIMIT, ceiling=MAX_CONTENT_LIMIT)
    guide_limit = _bounded_limit(env, "GUIDE_LIMIT", default=DEFAULT_GUIDE_LIMIT, ceiling=MAX_GUIDE_LIMIT)
    korean_limit = _bounded_limit(env, "KOREAN_LIMIT", default=DEFAULT_KOREAN_LIMIT, ceiling=MAX_KOREAN_LIMIT)

    raw: dict[str, Any] = {}
    from topic_bank_pipeline import topic_bank_backlog

    bank_raw = topic_bank_backlog(site_id, repo)
    if bank_raw:
        raw = bank_raw
    elif site_id == "hatena":
        raw = {"note": "Hatena는 CSV 미처리 포스트 기준 — 별도 집계 없음"}
    else:
        raw = {}

    expand = _preview_csv_expand(site_id, repo)

    from topic_bank import bank_stats
    from topic_bank_pipeline import refresh_topic_state

    refresh_topic_state(site_id, repo)
    topic_stats = bank_stats(site_id)

    items_pairs = int(raw.get("items_pairs") or 0)
    guides_topics = int(raw.get("guides_topics") or raw.get("guides_md") or 0)
    images = int(raw.get("images") or 0)
    korean = int(raw.get("korean_files") or 0)

    next_items = min(item_limit, items_pairs) if items_pairs else 0
    next_guides = min(guide_limit, guides_topics) if guides_topics else 0
    next_korean = min(korean_limit, korean) if korean else 0

    content_empty = items_pairs == 0 and guides_topics == 0 and korean == 0
    if site_id == "starful.biz":
        content_empty = int(raw.get("guides_md") or 0) == 0
    elif site_id == "jpcampus":
        content_empty = (
            int(raw.get("guides_topics") or 0) == 0
            and int(raw.get("univs_pending") or 0) == 0
        )
    elif site_id == "krcampus":
        content_empty = (
            int(raw.get("guides_topics") or 0) == 0
            and int(raw.get("schools_pending") or 0) == 0
            and int(raw.get("univs_pending") or 0) == 0
        )
    expand_avail = expand.get("items_expandable", 0) + expand.get("guides_expandable", 0)
    if site_id in (
        "okstats",
        "okramen",
        "okonsen",
        "okcaddie",
        "starful.biz",
        "jpcampus",
        "krcampus",
    ):
        csv_refresh_suggested = content_empty
    else:
        csv_refresh_suggested = content_empty and expand_avail > 0

    if site_id == "starful.biz":
        content_n = 0
        guide_n = int(raw.get("guides_md") or 0)
    elif site_id == "jpcampus":
        univs_n = int(raw.get("univs_pending") or 0)
        content_n = univs_n
        guide_n = guides_topics
    elif site_id == "krcampus":
        schools_n = int(raw.get("schools_pending") or 0)
        univs_n = int(raw.get("univs_pending") or 0)
        content_n = schools_n + univs_n
        guide_n = guides_topics
    elif site_id == "okstats":
        content_n = items_pairs
        guide_n = guides_topics
    elif site_id in POI_SITES:
        content_n = items_pairs
        guide_n = guides_topics
    else:
        content_n = items_pairs
        guide_n = guides_topics

    generatable: dict[str, Any] = {
        "content": content_n,
        "guides": guide_n,
        "total": content_n + guide_n,
    }
    if site_id == "krcampus":
        generatable["schools"] = int(raw.get("schools_pending") or 0)
        generatable["univs"] = int(raw.get("univs_pending") or 0)
        generatable["total"] = guide_n + generatable["schools"] + generatable["univs"]
    elif site_id == "starful.biz":
        generatable["total"] = guide_n
    elif site_id == "jpcampus":
        generatable["univs"] = int(raw.get("univs_pending") or 0)
        generatable["total"] = guide_n + generatable["univs"]

    if site_id == "okstats":
        total_gen = content_n + guide_n
        summary = f"생성 가능 {total_gen}건 (인사이트 {content_n} · 가이드 {guide_n})"
    elif site_id == "okramen":
        total_gen = content_n + guide_n
        summary = f"생성 가능 {total_gen}건 (라멘 {content_n} · 가이드 {guide_n})"
    elif site_id == "okonsen":
        total_gen = content_n + guide_n
        summary = f"생성 가능 {total_gen}건 (온천 {content_n} · 가이드 {guide_n})"
    elif site_id == "okcaddie":
        total_gen = content_n + guide_n
        summary = f"생성 가능 {total_gen}건 (코스 {content_n} · 가이드 {guide_n})"
    elif site_id == "starful.biz":
        total_gen = guide_n
        summary = f"생성 가능 {total_gen}건 (포지션 {guide_n})"
    elif site_id == "jpcampus":
        univs_n = int(raw.get("univs_pending") or 0)
        total_gen = guide_n + univs_n
        summary = f"생성 가능 {total_gen}건 (가이드 {guide_n} · 대학 {univs_n})"
    elif site_id == "krcampus":
        schools_n = int(raw.get("schools_pending") or 0)
        univs_n = int(raw.get("univs_pending") or 0)
        total_gen = guide_n + schools_n + univs_n
        summary = f"생성 가능 {total_gen}건 (가이드 {guide_n} · 어학원 {schools_n} · 대학 {univs_n})"
    else:
        summary = f"콘텐츠 {content_n} · 가이드 {guide_n}"

    csv_out: dict[str, Any] = {
        "items": raw.get("csv_items"),
        "guides": raw.get("csv_guides"),
    }
    if site_id == "krcampus":
        csv_out["schools"] = raw.get("csv_schools")
        csv_out["univs"] = raw.get("csv_univs")
    elif site_id == "jpcampus":
        csv_out["univs"] = raw.get("csv_univs")

    return {
        "ok": True,
        "site_id": site_id,
        "computed_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "generatable": generatable,
        "csv": csv_out,
        "backlog": {
            "items_pairs": items_pairs,
            "items_files": raw.get("items_files", 0),
            "guides_topics": guides_topics,
            "guides_files": raw.get("guides_files", 0),
            "images": images,
            "korean_files": korean,
            "schools_pending": raw.get("schools_pending", 0),
            "univs_pending": raw.get("univs_pending", 0),
        },
        "next_run": {
            "items_pairs": next_items,
            "guides_topics": next_guides,
            "korean_files": next_korean,
            "limits": {
                "content": item_limit,
                "guide": guide_limit,
                "korean": korean_limit,
            },
        },
        "csv_expand": {
            **expand,
            "suggested": csv_refresh_suggested,
            "topic_bank": topic_stats.get("banks") or {},
        },
        "summary": summary,
    }


def refresh_backlog_snapshot(site_id: str) -> dict[str, Any]:
    data = compute_backlog(site_id)
    if data.get("ok"):
        write_backlog_snapshot(site_id, data)
    return data


def refresh_all_backlog_snapshots(site_ids: list[str] | None = None) -> dict[str, Any]:
    from content_pipeline import CONTENT_PIPELINES

    ids = site_ids or list(CONTENT_PIPELINES.keys())
    done: list[str] = []
    errors: dict[str, str] = {}
    for sid in ids:
        r = refresh_backlog_snapshot(sid)
        if r.get("ok"):
            done.append(sid)
        else:
            errors[sid] = r.get("error") or "failed"
    return {"ok": not errors, "refreshed": done, "errors": errors}
