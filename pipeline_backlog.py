"""Content backlog snapshots (CSV vs MD). Refreshed on demand or after pipeline — not on every page load."""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import get_service, repo_path, work_root_available

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


def _item_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_").replace("'", ""))


def _count_csv(path: Path, col: str) -> int:
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return 0
    n = 0
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get(col) or "").strip():
            n += 1
    return n


def _ok_dual_backlog(repo: Path, *, items_rel: str, guides_rel: str, name_col: str = "Name") -> dict[str, Any]:
    content_dir = repo / "app" / "content"
    guides_dir = content_dir / "guides"
    images_dir = repo / "app" / "static" / "images"

    item_pairs_pending = 0
    item_files_pending = 0
    items_path = repo / items_rel
    if items_path.is_file():
        with items_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = (row.get(name_col) or "").strip()
                if not name:
                    continue
                slug = _item_slug(name)
                en = content_dir / f"{slug}_en.md"
                ko = content_dir / f"{slug}_ko.md"
                miss = int(not en.is_file()) + int(not ko.is_file())
                if miss:
                    item_pairs_pending += 1
                    item_files_pending += miss

    guide_topics_pending = 0
    guide_files_pending = 0
    guides_path = repo / guides_rel
    if guides_path.is_file():
        with guides_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                gid = (row.get("id") or "").strip()
                if not gid:
                    continue
                en = guides_dir / f"{gid}_en.md"
                ko = guides_dir / f"{gid}_ko.md"
                miss = int(not en.is_file()) + int(not ko.is_file())
                if miss:
                    guide_topics_pending += 1
                    guide_files_pending += miss

    images_pending = 0
    if content_dir.is_dir():
        for md in content_dir.glob("*_en.md"):
            if md.name.startswith("guide"):
                continue
            stem = md.stem.replace("_en", "")
            img = images_dir / f"{stem}.jpg"
            if not img.is_file() or img.stat().st_size < PLACEHOLDER_IMAGE_MAX:
                images_pending += 1

    return {
        "items_pairs": item_pairs_pending,
        "items_files": item_files_pending,
        "guides_topics": guide_topics_pending,
        "guides_files": guide_files_pending,
        "images": images_pending,
        "csv_items": _count_csv(items_path, name_col),
        "csv_guides": _count_csv(guides_path, "topic_en"),
    }


def _okstats_backlog(repo: Path) -> dict[str, Any]:
    content_dir = repo / "app" / "content"
    guides_dir = content_dir / "guides"
    images_dir = repo / "app" / "static" / "images"

    insights_pending = 0
    insight_files_pending = 0
    insights_path = repo / "script/csv/insights.csv"
    if insights_path.is_file():
        with insights_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if (row.get("id") or "").strip().startswith("#"):
                    continue
                iid = (row.get("id") or "").strip()
                if not iid:
                    continue
                md = content_dir / f"{iid}_en.md"
                if not md.is_file():
                    insights_pending += 1
                    insight_files_pending += 1

    guide_topics_pending = 0
    guide_files_pending = 0
    guides_path = repo / "script/csv/guides.csv"
    if guides_path.is_file():
        with guides_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                gid = (row.get("id") or "").strip()
                if not gid:
                    continue
                candidates = [guides_dir / f"{gid}.md", guides_dir / f"{gid}_en.md"]
                if not any(p.is_file() for p in candidates):
                    guide_topics_pending += 1
                    guide_files_pending += 1

    images_pending = 0
    if content_dir.is_dir():
        for md in content_dir.glob("*_en.md"):
            stem = md.stem.replace("_en", "")
            img = images_dir / f"{stem}.jpg"
            if not img.is_file() or img.stat().st_size < PLACEHOLDER_IMAGE_MAX:
                images_pending += 1

    return {
        "items_pairs": insights_pending,
        "items_files": insight_files_pending,
        "guides_topics": guide_topics_pending,
        "guides_files": guide_files_pending,
        "images": images_pending,
        "csv_items": _count_csv(insights_path, "id"),
        "csv_guides": _count_csv(guides_path, "topic_en"),
    }


from starful_assets import position_slug


def _starful_backlog(repo: Path) -> dict[str, Any]:
    csv_path = repo / "scripts/data/positions.csv"
    out_dir = repo / "app/contents"
    img_dir = repo / "app/static/img"
    pending = 0
    images = 0
    if csv_path.is_file() and out_dir.is_dir():
        with csv_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                pos = (row.get("position_name") or "").strip()
                if not pos:
                    continue
                slug = position_slug(pos)
                if not (out_dir / f"{slug}.md").is_file():
                    pending += 1
    if out_dir.is_dir():
        for md in out_dir.glob("*.md"):
            if not (img_dir / f"{md.stem}.png").is_file():
                images += 1
    return {
        "guides_md": pending,
        "images": images,
        "csv_items": _count_csv(csv_path, "position_name"),
    }


def _jpcampus_backlog(repo: Path) -> dict[str, Any]:
    topics_path = repo / "data/guide_topics.csv"
    content_dir = repo / "app" / "content"
    guides_pending = 0
    korean_pending = 0
    if topics_path.is_file():
        with topics_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                slug = (row.get("slug") or "").strip()
                if not slug:
                    continue
                en = content_dir / f"guide_{slug}.md"
                if not en.is_file():
                    guides_pending += 1
                kr = content_dir / f"guide_{slug}_kr.md"
                if en.is_file() and not kr.is_file():
                    korean_pending += 1
    return {
        "guides_topics": guides_pending,
        "korean_files": korean_pending,
        "csv_guides": _count_csv(topics_path, "slug"),
    }


def _krcampus_read_basic_names(md_path: Path) -> tuple[str, str]:
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    if not text.startswith("---"):
        return "", ""
    end = text.find("---", 3)
    if end < 0:
        return "", ""
    try:
        data = json.loads(text[3:end].strip())
    except json.JSONDecodeError:
        return "", ""
    basic = data.get("basic_info") or {}
    return (basic.get("name_ko") or "").strip(), (basic.get("name_en") or "").strip()


def _krcampus_name_index(content_dir: Path, prefix: str) -> tuple[set[str], set[str]]:
    """name_ko and lowercased name_en from existing {prefix}_*.md (EN base, not _ja)."""
    ko: set[str] = set()
    en: set[str] = set()
    if not content_dir.is_dir():
        return ko, en
    for md in content_dir.glob(f"{prefix}_*.md"):
        if md.stem.endswith("_ja"):
            continue
        name_ko, name_en = _krcampus_read_basic_names(md)
        if name_ko:
            ko.add(name_ko)
        if name_en:
            en.add(name_en.lower())
    return ko, en


def _krcampus_csv_pending(
    csv_path: Path,
    *,
    known_ko: set[str],
    known_en: set[str],
) -> int:
    if not csv_path.is_file():
        return 0
    pending = 0
    with csv_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name_ko = (row.get("name_ko") or "").strip()
            name_en = (row.get("name_en") or "").strip()
            if not name_ko and not name_en:
                continue
            if name_ko in known_ko:
                continue
            if name_en and name_en.lower() in known_en:
                continue
            pending += 1
    return pending


def _krcampus_backlog(repo: Path) -> dict[str, Any]:
    topics_path = repo / "data/guide_topics.csv"
    schools_path = repo / "data/language_schools.csv"
    univ_path = repo / "data/universities.csv"
    content_dir = repo / "app" / "content"

    guides_pending = 0
    ja_pending = 0
    if topics_path.is_file():
        with topics_path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                slug = (row.get("slug") or "").strip()
                if not slug:
                    continue
                en = content_dir / f"guide_{slug}.md"
                if not en.is_file():
                    guides_pending += 1
                ja = content_dir / f"guide_{slug}_ja.md"
                if en.is_file() and not ja.is_file():
                    ja_pending += 1

    school_ko, school_en = _krcampus_name_index(content_dir, "school")
    univ_ko, univ_en = _krcampus_name_index(content_dir, "univ")
    schools_pending = _krcampus_csv_pending(schools_path, known_ko=school_ko, known_en=school_en)
    univs_pending = _krcampus_csv_pending(univ_path, known_ko=univ_ko, known_en=univ_en)

    return {
        "guides_topics": guides_pending,
        "korean_files": ja_pending,
        "schools_pending": schools_pending,
        "univs_pending": univs_pending,
        "items_pairs": schools_pending + univs_pending,
        "csv_guides": _count_csv(topics_path, "slug"),
        "csv_schools": _count_csv(schools_path, "name_ko"),
        "csv_univs": _count_csv(univ_path, "name_ko"),
    }


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

    if site_id in ("okramen", "okonsen", "okcaddie"):
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
    elif site_id in ("okramen", "okonsen", "okcaddie"):
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
