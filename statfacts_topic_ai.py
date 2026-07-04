"""StatFacts: AI-generated insight/guide rows for topic bank (목록 추가)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config_gemini import ensure_gemini_api_key
from topic_bank import _append_bank_rows, read_bank
from topic_bank_registry import banks_for_site

STATFACTS_CATEGORIES: tuple[str, ...] = (
    "ux",
    "business",
    "gaming",
    "food",
    "hr",
    "travel",
    "sports",
    "health",
)

DEFAULT_INSIGHT_COUNT = 6
DEFAULT_GUIDE_COUNT = 3
MAX_INSIGHT_COUNT = 30
MAX_GUIDE_COUNT = 15

_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _clamp_count(n: int, default: int, ceiling: int) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = default
    if v < 0:
        v = 0
    return min(v, ceiling)


def distribute_category_counts(total: int, categories: tuple[str, ...]) -> dict[str, int]:
    if total <= 0 or not categories:
        return {}
    base, extra = divmod(total, len(categories))
    out = {c: base for c in categories}
    for cat in categories[:extra]:
        out[cat] += 1
    return {k: v for k, v in out.items() if v > 0}


def _normalize_id(raw: str) -> str | None:
    s = (raw or "").strip().lower().replace("_", "-")
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or not _ID_RE.match(s):
        return None
    return s


def _existing_insight_ids(site_id: str, repo: Path) -> set[str]:
    ids: set[str] = set()
    for row in read_bank(site_id, "insights"):
        iid = _normalize_id(row.get("id") or "")
        if iid:
            ids.add(iid)
    content = repo / "app" / "content"
    if content.is_dir():
        for md in content.glob("*_en.md"):
            ids.add(md.stem.replace("_en", ""))
    return ids


def _existing_guide_ids(site_id: str, repo: Path) -> set[str]:
    ids: set[str] = set()
    for row in read_bank(site_id, "guides"):
        gid = _normalize_id(row.get("id") or "")
        if gid:
            ids.add(gid)
    guides_dir = repo / "app" / "content" / "guides"
    if guides_dir.is_dir():
        for md in guides_dir.glob("*.md"):
            stem = md.stem.replace("_en", "")
            ids.add(stem)
    return ids


def _insights_by_category(site_id: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {c: [] for c in STATFACTS_CATEGORIES}
    for row in read_bank(site_id, "insights"):
        iid = (row.get("id") or "").strip()
        if not iid or iid.startswith("#"):
            continue
        topic = (row.get("topic") or iid).strip()
        cats = [c.strip().lower() for c in (row.get("categories") or "").split(",") if c.strip()]
        primary = next((c for c in cats if c in out), cats[0] if cats else "business")
        if primary in out:
            out[primary].append(f"{iid}: {topic}")
    return out


def _existing_guide_topics(site_id: str) -> list[str]:
    lines: list[str] = []
    for row in read_bank(site_id, "guides"):
        gid = (row.get("id") or "").strip()
        if not gid:
            continue
        topic = (row.get("topic_en") or gid).strip()
        lines.append(f"{gid}: {topic}")
    return lines


def _gemini_json(prompt: str) -> dict[str, Any] | None:
    if not ensure_gemini_api_key():
        return None
    try:
        import google.generativeai as genai
    except ImportError:
        return None
    import os

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model_name = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    model = genai.GenerativeModel(model_name)
    try:
        res = model.generate_content(prompt)
        text = (res.text or "").strip()
    except Exception:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def _format_category_distribution(per_cat: dict[str, int]) -> str:
    if not per_cat:
        return "(no insights requested)"
    return "\n".join(
        f'- category "{cat}": exactly {n} insight(s); "categories" must start with "{cat}"'
        for cat, n in sorted(per_cat.items())
    )


def _parse_insight_row(item: dict[str, Any], existing_ids: set[str]) -> dict[str, str] | None:
    iid = _normalize_id(str(item.get("id") or ""))
    if not iid or iid in existing_ids:
        return None
    cats_raw = str(item.get("categories") or "business").strip()
    primary = cats_raw.split(",")[0].strip().lower() if cats_raw else "business"
    row = {
        "id": iid,
        "topic": str(item.get("topic") or iid).strip(),
        "intervention": str(item.get("intervention") or "").strip(),
        "outcome": str(item.get("outcome") or "").strip(),
        "effect_min": str(item.get("effect_min") or "3").strip(),
        "effect_max": str(item.get("effect_max") or "10").strip(),
        "effect_unit": str(item.get("effect_unit") or "percent_relative").strip(),
        "categories": cats_raw or primary,
        "confidence": str(item.get("confidence") or "estimate").strip(),
        "keywords": str(item.get("keywords") or primary).strip(),
    }
    if not row["intervention"] or not row["outcome"]:
        return None
    existing_ids.add(iid)
    return row


def _parse_guide_row(item: dict[str, Any], existing_ids: set[str]) -> dict[str, str] | None:
    gid = _normalize_id(str(item.get("id") or ""))
    if not gid or gid in existing_ids:
        return None
    row = {
        "id": gid,
        "topic_en": str(item.get("topic_en") or gid).strip(),
        "topic_ko": "",
        "keywords": str(item.get("keywords") or "benchmark experiment").strip(),
    }
    if not row["topic_en"]:
        return None
    existing_ids.add(gid)
    return row


def _generate_topics_batch(
    insight_n: int,
    guide_n: int,
    per_cat: dict[str, int],
    existing_insight_ids: set[str],
    existing_guide_ids: set[str],
    insight_topics_by_cat: dict[str, list[str]],
    existing_guide_topics: list[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if insight_n <= 0 and guide_n <= 0:
        return [], []

    insight_avoid = "\n".join(
        f"- {t}"
        for topics in insight_topics_by_cat.values()
        for t in topics[:12]
    ) or "(none)"
    guide_avoid = "\n".join(f"- {t}" for t in existing_guide_topics[:50]) or "(none)"
    cat_spec = _format_category_distribution(per_cat)

    insight_block = ""
    if insight_n > 0:
        insight_block = f"""
Generate exactly {insight_n} NEW insight topic rows total, distributed across categories:
{cat_spec}

Each insight describes a specific intervention and measurable outcome with an effect-size range.
Do NOT duplicate these existing insight ids or near-duplicate topics:
ids: {", ".join(sorted(existing_insight_ids)[:80])}

Existing insight topics (sample):
{insight_avoid}
"""

    guide_block = ""
    if guide_n > 0:
        guide_block = f"""
Generate exactly {guide_n} NEW benchmark / A/B testing / analytics GUIDE topics (not product insights).
Guides explain how product teams read benchmarks, run experiments, or use statistics.
No product category tags. English only (topic_ko empty string).

Do NOT duplicate these guide ids or topics:
ids: {", ".join(sorted(existing_guide_ids)[:80])}

Existing guides:
{guide_avoid}
"""

    prompt = f"""You are an editor for StatFacts.net.
{insight_block}
{guide_block}
Return ONLY valid JSON with this shape (omit empty arrays):
{{
  "insights": [
    {{
      "id": "kebab-case-slug",
      "topic": "Short topic label",
      "intervention": "What changes",
      "outcome": "Measured outcome",
      "effect_min": "5",
      "effect_max": "12",
      "effect_unit": "percent_relative",
      "categories": "ux,optional-subtag",
      "confidence": "ab_test",
      "keywords": "comma separated"
    }}
  ],
  "guides": [
    {{
      "id": "kebab-case-slug",
      "topic_en": "Guide title in English",
      "topic_ko": "",
      "keywords": "benchmark experiment analytics"
    }}
  ]
}}

Rules:
- ids must be unique, lowercase kebab-case, 3-5 words
- insight confidence: ab_test | meta_analysis | study | estimate
- insight effect_unit: percent_relative | percent_point
"""

    data = _gemini_json(prompt)
    if not data:
        return [], []

    insight_ids = set(existing_insight_ids)
    guide_ids = set(existing_guide_ids)
    insights: list[dict[str, str]] = []
    for item in data.get("insights") or []:
        if not isinstance(item, dict) or len(insights) >= insight_n:
            break
        row = _parse_insight_row(item, insight_ids)
        if row:
            insights.append(row)

    guides: list[dict[str, str]] = []
    for item in data.get("guides") or []:
        if not isinstance(item, dict) or len(guides) >= guide_n:
            break
        row = _parse_guide_row(item, guide_ids)
        if row:
            guides.append(row)

    return insights, guides


def append_statfacts_topics(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    insight_count: int = DEFAULT_INSIGHT_COUNT,
    guide_count: int = DEFAULT_GUIDE_COUNT,
) -> dict[str, Any]:
    """AI-generate insight/guide rows and append to topic bank."""
    insight_n = _clamp_count(insight_count, DEFAULT_INSIGHT_COUNT, MAX_INSIGHT_COUNT)
    guide_n = _clamp_count(guide_count, DEFAULT_GUIDE_COUNT, MAX_GUIDE_COUNT)
    if insight_n == 0 and guide_n == 0:
        return {"ok": False, "error": "insight_count and guide_count are both 0"}

    if not ensure_gemini_api_key():
        return {"ok": False, "error": "GEMINI_API_KEY 없음"}

    insight_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "insights")
    guide_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "guides")

    existing_insight_ids = _existing_insight_ids(site_id, repo)
    existing_guide_ids = _existing_guide_ids(site_id, repo)
    by_cat = _insights_by_category(site_id)
    per_cat = distribute_category_counts(insight_n, STATFACTS_CATEGORIES)

    if logf:
        logf.write(f"StatFacts AI: 인사이트 {insight_n}건 · 가이드 {guide_n}건 단일 요청\n")

    new_insights, new_guides = _generate_topics_batch(
        insight_n,
        guide_n,
        per_cat,
        existing_insight_ids,
        existing_guide_ids,
        by_cat,
        _existing_guide_topics(site_id),
    )

    if logf:
        logf.write(f"  → 인사이트 {len(new_insights)}건 · 가이드 {len(new_guides)}건\n")

    added_i = _append_bank_rows(site_id, insight_spec, new_insights)
    added_g = _append_bank_rows(site_id, guide_spec, new_guides)
    from topic_bank_pipeline import refresh_topic_state

    refresh_topic_state(site_id, repo)

    total = added_i + added_g
    messages = []
    if added_i:
        messages.append(f"인사이트 +{added_i}")
    if added_g:
        messages.append(f"가이드 +{added_g}")
    if not total:
        messages.append("AI가 생성했지만 중복/검증 실패로 추가된 행 없음")

    return {
        "ok": True,
        "rows_added": total,
        "bank_rows_added": total,
        "bank_appended": {"insights": added_i, "guides": added_g},
        "expanded": total,
        "expanded_items": added_i,
        "expanded_guides": added_g,
        "messages": messages,
        "insight_count_requested": insight_n,
        "guide_count_requested": guide_n,
    }
