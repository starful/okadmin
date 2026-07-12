"""Google Trends → topic bank seed (Hatena excluded).

Uses rising related queries for site seed keywords, then appends guide/position
rows to the okadmin topic bank. Items/universities/schools are not seeded from
Trends (need structured entity data).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from config import get_service, repo_path, work_root_available
from pipeline_runner import pipeline_log_path
from statfacts_topic_ai import _clamp_count, _normalize_id
from topic_bank import _append_bank_rows, read_bank
from topic_bank_registry import banks_for_site

TRENDS_SITES: tuple[str, ...] = (
    "okramen",
    "okonsen",
    "okcaddie",
    "okstats",
    "starful.biz",
    "jpcampus",
    "krcampus",
)

DEFAULT_LIMIT = 8
MAX_LIMIT = 20
DEFAULT_SEED_CAP = 3  # seed keywords queried per run


@dataclass(frozen=True)
class SiteTrendsConfig:
    hl: str
    geo: str
    tz: int
    seeds: tuple[str, ...]
    timeframe: str = "today 3-m"
    category: str = "Guide"


_SITE_CONFIG: dict[str, SiteTrendsConfig] = {
    "okramen": SiteTrendsConfig(
        hl="en-US",
        geo="JP",
        tz=540,
        seeds=("ramen japan", "best ramen tokyo", "tsukemen", "tonkotsu ramen"),
        category="Food",
    ),
    "okonsen": SiteTrendsConfig(
        hl="en-US",
        geo="JP",
        tz=540,
        seeds=("onsen japan", "hot spring japan", "ryokan onsen", "hakone onsen"),
        category="Travel",
    ),
    "okcaddie": SiteTrendsConfig(
        hl="en-US",
        geo="JP",
        tz=540,
        seeds=("golf japan", "golf course tokyo", "golf resort japan"),
        category="Golf",
    ),
    "okstats": SiteTrendsConfig(
        hl="en-US",
        geo="",
        tz=0,
        seeds=("ux statistics", "conversion rate tips", "A/B testing results"),
        category="Research",
    ),
    "starful.biz": SiteTrendsConfig(
        hl="en-US",
        geo="US",
        tz=0,
        seeds=("software engineer interview", "product manager job", "data scientist career"),
        category="Career",
    ),
    "jpcampus": SiteTrendsConfig(
        hl="en-US",
        geo="JP",
        tz=540,
        seeds=("study in japan", "japan student visa", "japanese language school"),
        category="Visa",
    ),
    "krcampus": SiteTrendsConfig(
        hl="ja-JP",
        geo="JP",
        tz=540,
        seeds=("韓国留学", "語学堂", "D-4ビザ", "TOPIK"),
        category="Visa",
    ),
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_HAS_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def supports_trends_seed(site_id: str) -> bool:
    return site_id in TRENDS_SITES and site_id in _SITE_CONFIG


def _slugify(text: str, *, fallback: str = "topic") -> str | None:
    raw = (text or "").strip().lower()
    if not raw:
        return None
    # Keep ASCII slug; for CJK use short hash-like transliteration via normalize_id path
    ascii_part = _SLUG_RE.sub("-", raw).strip("-")
    if ascii_part and len(ascii_part) >= 3:
        return _normalize_id(ascii_part[:60])
    # CJK / non-latin: use compact token from codepoints
    compact = "-".join(f"{ord(c):x}" for c in text.strip()[:12] if not c.isspace())
    return _normalize_id(f"tr-{compact}"[:60]) or _normalize_id(fallback)


def _title_from_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    if _HAS_CJK.search(q):
        return q
    return " ".join(w.capitalize() if w.islower() else w for w in q.split())


def _fetch_rising_queries(
    seeds: list[str],
    *,
    hl: str,
    geo: str,
    tz: int,
    timeframe: str,
    per_seed: int = 8,
    sleep_s: float = 0.8,
) -> list[dict[str, Any]]:
    """Return list of {query, value, seed} from Google Trends rising related queries."""
    try:
        from pytrends.request import TrendReq
    except ImportError as exc:
        raise RuntimeError("pytrends 미설치 — pip install pytrends") from exc

    pytrends = TrendReq(hl=hl, tz=tz, retries=2, backoff_factor=0.4)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for seed in seeds:
        seed = (seed or "").strip()
        if not seed:
            continue
        try:
            pytrends.build_payload([seed], timeframe=timeframe, geo=geo or "")
            related = pytrends.related_queries() or {}
            block = related.get(seed) or {}
            rising = block.get("rising")
            if rising is None:
                # fallback to top if rising empty
                rising = block.get("top")
            if rising is None or getattr(rising, "empty", True):
                time.sleep(sleep_s)
                continue
            for _, row in rising.head(per_seed).iterrows():
                q = str(row.get("query") or "").strip()
                if not q:
                    continue
                key = q.lower()
                if key in seen or key == seed.lower():
                    continue
                seen.add(key)
                try:
                    value = int(row.get("value") or 0)
                except (TypeError, ValueError):
                    value = 0
                out.append({"query": q, "value": value, "seed": seed})
        except Exception:
            # Trends endpoints are flaky; continue other seeds
            pass
        time.sleep(sleep_s)

    out.sort(key=lambda x: (-int(x.get("value") or 0), x.get("query") or ""))
    return out


FetchFn = Callable[..., list[dict[str, Any]]]


def _existing_guide_ids_poi(site_id: str) -> set[str]:
    ids: set[str] = set()
    for row in read_bank(site_id, "guides"):
        gid = _normalize_id(row.get("id") or "")
        if gid:
            ids.add(gid)
    return ids


def _existing_guide_slugs_campus(site_id: str) -> set[str]:
    slugs: set[str] = set()
    for row in read_bank(site_id, "guide_topics"):
        s = _normalize_id(row.get("slug") or "")
        if s:
            slugs.add(s)
    return slugs


def _existing_positions(site_id: str) -> set[str]:
    names: set[str] = set()
    for row in read_bank(site_id, "positions"):
        pos = (row.get("position_name") or "").strip().lower()
        if pos:
            names.add(pos)
    return names


def _rows_for_poi_guides(
    site_id: str,
    queries: list[dict[str, Any]],
    *,
    limit: int,
    category: str,
) -> list[dict[str, str]]:
    existing = _existing_guide_ids_poi(site_id)
    rows: list[dict[str, str]] = []
    for item in queries:
        if len(rows) >= limit:
            break
        q = str(item.get("query") or "").strip()
        gid = _slugify(q)
        if not gid or gid in existing:
            continue
        title = _title_from_query(q)
        row = {
            "id": gid,
            "topic_en": title,
            "topic_ko": title if _HAS_CJK.search(title) else "",
            "keywords": f"{q}, {item.get('seed') or ''}".strip(", "),
        }
        rows.append(row)
        existing.add(gid)
    return rows


def _rows_for_campus_guides(
    site_id: str,
    queries: list[dict[str, Any]],
    *,
    limit: int,
    category: str,
    country: str,
) -> list[dict[str, str]]:
    existing = _existing_guide_slugs_campus(site_id)
    rows: list[dict[str, str]] = []
    for item in queries:
        if len(rows) >= limit:
            break
        q = str(item.get("query") or "").strip()
        slug = _slugify(q)
        if not slug or slug in existing:
            continue
        title = _title_from_query(q)
        seed = str(item.get("seed") or "")
        desc = f"Trending search guide: {q}" + (f" (related to {seed})" if seed else "")
        prompt = (
            f"Write a practical study-abroad guide for {country} covering: {q}. "
            f"Include costs, visas, timelines, and actionable tips for international students."
        )
        rows.append(
            {
                "slug": slug,
                "category": category,
                "title": title,
                "description": desc,
                "prompt": prompt,
            }
        )
        existing.add(slug)
    return rows


def _rows_for_starful(
    queries: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, str]]:
    existing = _existing_positions("starful.biz")
    rows: list[dict[str, str]] = []
    for item in queries:
        if len(rows) >= limit:
            break
        q = str(item.get("query") or "").strip()
        # Prefer short job-title-like phrases
        title = _title_from_query(q)
        # Strip trailing interview/career noise for position_name
        cleaned = re.sub(
            r"\b(interview|questions?|salary|resume|career|job|guide|tips?)\b",
            "",
            title,
            flags=re.I,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|/")
        if len(cleaned.split()) < 2:
            cleaned = title
        if not cleaned or cleaned.lower() in existing:
            continue
        if len(cleaned) > 60:
            continue
        rows.append({"position_name": cleaned})
        existing.add(cleaned.lower())
    return rows


def append_trends_topics(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    seed_cap: int = DEFAULT_SEED_CAP,
    fetch_fn: FetchFn | None = None,
) -> dict[str, Any]:
    if not supports_trends_seed(site_id):
        return {"ok": False, "error": f"Trends 시드 미지원: {site_id}"}

    cfg = _SITE_CONFIG[site_id]
    n = _clamp_count(limit, DEFAULT_LIMIT, MAX_LIMIT)
    seeds = list(cfg.seeds[: max(1, min(seed_cap, len(cfg.seeds)))])
    fetcher = fetch_fn or _fetch_rising_queries

    logf.write(f"Trends seed {site_id}: seeds={seeds} limit={n}\n")
    try:
        queries = fetcher(
            seeds,
            hl=cfg.hl,
            geo=cfg.geo,
            tz=cfg.tz,
            timeframe=cfg.timeframe,
        )
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"Trends 조회 실패: {exc}"}

    if not queries:
        return {
            "ok": True,
            "site_id": site_id,
            "rows_added": 0,
            "queries_found": 0,
            "bank_appended": {},
            "messages": ["Trends rising/related 결과 없음 (시드·지역 확인)"],
        }

    bank_appended: dict[str, int] = {}
    messages: list[str] = [f"Trends 후보 {len(queries)}건"]

    if site_id in ("okramen", "okonsen", "okcaddie", "okstats"):
        spec = next(s for s in banks_for_site(site_id) if s.bank_id == "guides")
        rows = _rows_for_poi_guides(site_id, queries, limit=n, category=cfg.category)
        added = _append_bank_rows(site_id, spec, rows)
        bank_appended["guides"] = added
        messages.append(f"guides +{added}")
    elif site_id in ("jpcampus", "krcampus"):
        spec = next(s for s in banks_for_site(site_id) if s.bank_id == "guide_topics")
        country = "Japan" if site_id == "jpcampus" else "South Korea"
        rows = _rows_for_campus_guides(
            site_id, queries, limit=n, category=cfg.category, country=country
        )
        added = _append_bank_rows(site_id, spec, rows)
        bank_appended["guide_topics"] = added
        messages.append(f"guide_topics +{added}")
    elif site_id == "starful.biz":
        spec = next(s for s in banks_for_site(site_id) if s.bank_id == "positions")
        rows = _rows_for_starful(queries, limit=n)
        added = _append_bank_rows(site_id, spec, rows)
        bank_appended["positions"] = added
        messages.append(f"positions +{added}")
    else:
        return {"ok": False, "error": f"adapter 없음: {site_id}"}

    try:
        from topic_bank_pipeline import refresh_topic_state

        refresh_topic_state(site_id, repo)
    except Exception as exc:
        messages.append(f"state refresh warn: {exc}")

    for line in messages:
        logf.write(line + "\n")

    rows_added = sum(bank_appended.values())
    return {
        "ok": True,
        "site_id": site_id,
        "rows_added": rows_added,
        "queries_found": len(queries),
        "bank_appended": bank_appended,
        "messages": messages,
        "sample_queries": [q.get("query") for q in queries[:8]],
    }


def run_trends_seed(site_id: str, *, limit: int | None = None) -> dict[str, Any]:
    if not work_root_available():
        return {"ok": False, "error": "WORK_ROOT not available"}
    if site_id == "hatena":
        return {"ok": False, "error": "hatena는 Trends 시드 대상이 아닙니다"}
    if not supports_trends_seed(site_id):
        return {"ok": False, "error": f"Trends 시드 미지원: {site_id}"}
    svc = get_service(site_id)
    if not svc:
        return {"ok": False, "error": f"{site_id} not in sites.yaml"}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {"ok": False, "error": f"missing repo {repo}"}

    messages: list[str] = []

    class _Log:
        def write(self, s: str) -> None:
            if s.strip():
                messages.append(s.rstrip())

        def flush(self) -> None:
            pass

    info = append_trends_topics(
        site_id,
        repo,
        _Log(),
        limit=limit if limit is not None else DEFAULT_LIMIT,
    )
    if messages and not info.get("messages"):
        info["messages"] = messages
    elif messages:
        info["messages"] = list(info.get("messages") or []) + messages

    log_path = pipeline_log_path(site_id)
    try:
        from datetime import datetime

        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n[{datetime.now():%F %T}] Trends seed (manual)\n")
            for line in info.get("messages") or []:
                lf.write(str(line) + "\n")
    except OSError:
        pass

    return info
