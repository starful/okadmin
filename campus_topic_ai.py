"""JP/KR Campus: AI topic bank rows (목록 추가)."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from config_gemini import ensure_gemini_api_key
from statfacts_topic_ai import _clamp_count, _gemini_json
from topic_bank import _append_bank_rows, read_bank
from content_done import _read_univ_md_names
from topic_bank_registry import banks_for_site

DEFAULT_GUIDE_COUNT = 3
DEFAULT_SCHOOL_COUNT = 3
DEFAULT_UNIVERSITY_COUNT = 3
MAX_GUIDE_COUNT = 15
MAX_SCHOOL_COUNT = 15
MAX_UNIVERSITY_COUNT = 15

_KR_REGION_HINTS = (
    "Seoul",
    "Gyeonggi",
    "Incheon",
    "Busan",
    "Gyeongsang",
    "Daegu",
    "Ulsan",
    "Gwangju",
    "Jeolla",
    "Daejeon",
    "Chungcheong",
    "Gangwon",
    "Jeju",
    "Sejong",
)

_GUIDE_CATEGORIES = ("Visa", "Housing", "Budget", "Region", "Culture", "Exam", "Work", "Settlement")

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _normalize_slug(raw: str) -> str | None:
    s = (raw or "").strip().lower().replace("_", "-")
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or not _SLUG_RE.match(s):
        return None
    return s


def _existing_guide_slugs(site_id: str, repo: Path) -> tuple[set[str], list[str]]:
    slugs: set[str] = set()
    lines: list[str] = []
    for row in read_bank(site_id, "guide_topics"):
        slug = (row.get("slug") or "").strip()
        if not slug:
            continue
        slugs.add(slug.lower())
        title = (row.get("title") or slug).strip()
        lines.append(f"{slug}: {title}")
    content_dir = repo / "app" / "content"
    if content_dir.is_dir():
        for md in content_dir.glob("guide_*.md"):
            stem = md.stem.replace("guide_", "").replace("_kr", "").replace("_ja", "")
            if stem:
                slugs.add(stem.lower())
    return slugs, lines


def _existing_school_keys(site_id: str, repo: Path) -> tuple[set[str], list[str]]:
    keys: set[str] = set()
    lines: list[str] = []
    for row in read_bank(site_id, "language_schools"):
        ko = (row.get("name_ko") or "").strip()
        en = (row.get("name_en") or "").strip().lower()
        if ko:
            keys.add(ko)
            lines.append(ko)
        if en:
            keys.add(en)
    content_dir = repo / "app" / "content"
    if content_dir.is_dir():
        for md in content_dir.glob("school_*.md"):
            if md.stem.endswith("_ja"):
                continue
            keys.add(md.stem.replace("school_", ""))
    return keys, lines


def _existing_univ_keys(site_id: str, repo: Path) -> tuple[set[str], list[str]]:
    keys: set[str] = set()
    lines: list[str] = []
    is_jp = site_id == "jpcampus"
    for row in read_bank(site_id, "universities"):
        if is_jp:
            ja = (row.get("name_ja") or "").strip()
            en = (row.get("name_en") or "").strip().lower()
            if ja:
                keys.add(ja)
                lines.append(ja)
            if en:
                keys.add(en)
        else:
            ko = (row.get("name_ko") or "").strip()
            en = (row.get("name_en") or "").strip().lower()
            if ko:
                keys.add(ko)
                lines.append(ko)
            if en:
                keys.add(en)
    content_dir = repo / "app" / "content"
    if content_dir.is_dir():
        for md in content_dir.glob("univ_*.md"):
            if md.stem.endswith(("_ja", "_kr")):
                continue
            ja, ko, en = _read_univ_md_names(md)
            if ja:
                keys.add(ja)
            if ko:
                keys.add(ko)
            if en:
                keys.add(en)
            keys.add(md.stem.replace("univ_", ""))
    return keys, lines


def _parse_guide_row(item: dict[str, Any], existing: set[str], site_label: str) -> dict[str, str] | None:
    slug = _normalize_slug(str(item.get("slug") or ""))
    if not slug or slug in existing:
        return None
    title = str(item.get("title") or "").strip()
    prompt = str(item.get("prompt") or "").strip()
    if not title or not prompt:
        return None
    row = {
        "slug": slug,
        "category": str(item.get("category") or "Guide").strip(),
        "title": title,
        "description": str(item.get("description") or title).strip(),
        "prompt": prompt,
    }
    existing.add(slug)
    return row


def _parse_school_row(item: dict[str, Any], existing: set[str]) -> dict[str, str] | None:
    ko = str(item.get("name_ko") or "").strip()
    en = str(item.get("name_en") or "").strip()
    if not ko or not en:
        return None
    if ko in existing or en.lower() in existing:
        return None
    region = str(item.get("region") or "Seoul").strip()
    city = str(item.get("city") or region).strip()
    existing.add(ko)
    existing.add(en.lower())
    return {"name_ko": ko, "name_en": en, "region": region, "city": city}


def _parse_jp_univ_row(item: dict[str, Any], existing: set[str]) -> dict[str, str] | None:
    ja = str(item.get("name_ja") or "").strip()
    en = str(item.get("name_en") or "").strip()
    if not ja or not en:
        return None
    if ja in existing or en.lower() in existing:
        return None
    region = str(item.get("region") or "Tokyo").strip()
    existing.add(ja)
    existing.add(en.lower())
    return {"name_ja": ja, "name_en": en, "region": region}


def _parse_univ_row(item: dict[str, Any], existing: set[str]) -> dict[str, str] | None:
    ko = str(item.get("name_ko") or "").strip()
    en = str(item.get("name_en") or "").strip()
    if not ko or not en:
        return None
    if ko in existing or en.lower() in existing:
        return None
    region = str(item.get("region") or "Seoul").strip()
    existing.add(ko)
    existing.add(en.lower())
    return {"name_ko": ko, "name_en": en, "region": region}


def _bank_institution_lines(site_id: str, bank_id: str) -> list[str]:
    """Human-readable bank rows for gap-aware prompts."""
    lines: list[str] = []
    for row in read_bank(site_id, bank_id):
        ko = (row.get("name_ko") or "").strip()
        en = (row.get("name_en") or "").strip()
        region = (row.get("region") or "").strip()
        city = (row.get("city") or "").strip()
        if not ko and not en:
            continue
        loc = ", ".join(x for x in (city, region) if x)
        if ko and en:
            lines.append(f"{ko} / {en}" + (f" ({loc})" if loc else ""))
        else:
            lines.append((ko or en) + (f" ({loc})" if loc else ""))
    return lines


def _region_gap_block(site_id: str, bank_id: str) -> tuple[str, list[str]]:
    """Summarize region coverage and return underrepresented regions to prioritize."""
    counts: Counter[str] = Counter()
    for row in read_bank(site_id, bank_id):
        region = (row.get("region") or "").strip() or "Unknown"
        counts[region] += 1

    if not counts:
        return "(no rows in bank yet)", list(_KR_REGION_HINTS[:6])

    lines = [f"  {region}: {n}" for region, n in counts.most_common()]
    avg = sum(counts.values()) / max(len(counts), 1)
    threshold = max(1, int(avg * 0.6))
    under = [r for r, n in counts.items() if n <= threshold]
    missing = [r for r in _KR_REGION_HINTS if r not in counts]
    priority = list(dict.fromkeys(under + missing))[:10]
    return "\n".join(lines), priority


def _guide_gap_block(site_id: str) -> tuple[str, list[str]]:
    counts: Counter[str] = Counter()
    for row in read_bank(site_id, "guide_topics"):
        cat = (row.get("category") or "Guide").strip() or "Guide"
        counts[cat] += 1
    if not counts:
        return "(no guides in bank yet)", list(_GUIDE_CATEGORIES[:4])
    lines = [f"  {cat}: {n}" for cat, n in counts.most_common()]
    missing = [c for c in _GUIDE_CATEGORIES if c not in counts]
    low = [c for c, n in counts.items() if n <= 1]
    priority = list(dict.fromkeys(missing + low))[:6]
    return "\n".join(lines), priority


def _prompt_name_block(label: str, names: list[str], *, max_lines: int = 200) -> str:
    if not names:
        return f"{label}: (none yet)"
    if len(names) <= max_lines:
        body = "\n".join(f"- {n}" for n in names)
    else:
        body = "\n".join(f"- {n}" for n in names[:max_lines])
        body += f"\n- … and {len(names) - max_lines} more (all are forbidden duplicates)"
    return f"{label} ({len(names)} total — do NOT reuse any):\n{body}"


def _build_krcampus_gap_prompt(
    *,
    g_n: int,
    s_n: int,
    u_n: int,
    guide_slugs: set[str],
    guide_lines: list[str],
    school_keys: set[str],
    school_bank_lines: list[str],
    univ_keys: set[str],
    univ_bank_lines: list[str],
    school_gap_regions: list[str],
    univ_gap_regions: list[str],
    guide_gap_categories: list[str],
    retry_note: str = "",
) -> str:
    blocks = []
    if g_n:
        blocks.append(
            f"Generate exactly {g_n} NEW guide_topics that fill category gaps "
            f"(prioritize: {', '.join(guide_gap_categories) or 'under-covered topics'})."
        )
    if s_n:
        blocks.append(
            f"Generate exactly {s_n} NEW language_schools in under-covered regions "
            f"(prioritize: {', '.join(school_gap_regions) or 'outside Seoul'}). "
            "Prefer university-affiliated institutes and accredited academies not listed below."
        )
    if u_n:
        blocks.append(
            f"Generate exactly {u_n} NEW universities in under-covered regions "
            f"(prioritize: {', '.join(univ_gap_regions) or 'outside Seoul'}). "
            "Prefer regional/national universities and specialized schools NOT listed below."
        )

    school_region_summary, _ = _region_gap_block("krcampus", "language_schools")
    univ_region_summary, _ = _region_gap_block("krcampus", "universities")
    guide_cat_summary, _ = _guide_gap_block("krcampus")

    return f"""You are an editor for KR Campus — study-in-Korea content for Japanese readers.
Fill coverage GAPS: add institutions and guides we do not already have.
{retry_note}
Tasks:
{chr(10).join(blocks)}

Guide category coverage:
{guide_cat_summary}

Language school region coverage:
{school_region_summary}

University region coverage:
{univ_region_summary}

{_prompt_name_block("Existing guide slugs", sorted(guide_slugs))}
Guide samples:
{chr(10).join(f"- {t}" for t in guide_lines[:40]) or "(none)"}

{_prompt_name_block("Existing language schools", school_bank_lines)}

{_prompt_name_block("Existing universities", univ_bank_lines)}

Return ONLY valid JSON (omit empty arrays):
{{
  "guide_topics": [
    {{
      "slug": "jeju-student-housing",
      "category": "Region",
      "title": "Student Housing in Jeju",
      "description": "Rent and dorm options",
      "prompt": "Write a Jeju student housing guide in English."
    }}
  ],
  "language_schools": [
    {{
      "name_ko": "강원대학교 국제언어교육원",
      "name_en": "Kangwon National University Korean Language Institute",
      "region": "Gangwon",
      "city": "Chuncheon"
    }}
  ],
  "universities": [
    {{
      "name_ko": "강원대학교",
      "name_en": "Kangwon National University",
      "region": "Gangwon"
    }}
  ]
}}

Rules:
- Every name/slug MUST be absent from the existing lists above (no duplicates, no synonyms of listed schools)
- Do NOT suggest 서울대/연세대/고려대/성균관대/한양대 or their language institutes unless absent from lists
- Universities: prefer regional campuses (Gangwon, Jeolla, Jeju, Chungcheong, Gyeongsang outside Busan)
- Language schools: match the university or city you name; include city field
- guide slug: kebab-case; category: {' | '.join(_GUIDE_CATEGORIES)}
"""


def _parse_krcampus_response(
    data: dict[str, Any],
    *,
    g_n: int,
    s_n: int,
    u_n: int,
    guide_slugs: set[str],
    school_keys: set[str],
    univ_keys: set[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    slugs = set(guide_slugs)
    new_guides: list[dict[str, str]] = []
    for item in data.get("guide_topics") or []:
        if not isinstance(item, dict) or len(new_guides) >= g_n:
            break
        row = _parse_guide_row(item, slugs, "Korea")
        if row:
            new_guides.append(row)

    schools = set(school_keys)
    new_schools: list[dict[str, str]] = []
    for item in data.get("language_schools") or []:
        if not isinstance(item, dict) or len(new_schools) >= s_n:
            break
        row = _parse_school_row(item, schools)
        if row:
            new_schools.append(row)

    univs = set(univ_keys)
    new_univs: list[dict[str, str]] = []
    for item in data.get("universities") or []:
        if not isinstance(item, dict) or len(new_univs) >= u_n:
            break
        row = _parse_univ_row(item, univs)
        if row:
            new_univs.append(row)

    return new_guides, new_schools, new_univs


def append_jpcampus_topics(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    guide_count: int = DEFAULT_GUIDE_COUNT,
    university_count: int = DEFAULT_UNIVERSITY_COUNT,
) -> dict[str, Any]:
    if site_id != "jpcampus":
        return {"ok": False, "error": f"unsupported site {site_id}"}

    g_n = _clamp_count(guide_count, DEFAULT_GUIDE_COUNT, MAX_GUIDE_COUNT)
    u_n = _clamp_count(university_count, DEFAULT_UNIVERSITY_COUNT, MAX_UNIVERSITY_COUNT)
    if g_n == 0 and u_n == 0:
        return {"ok": False, "error": "guide_count and university_count are both 0"}
    if not ensure_gemini_api_key():
        return {"ok": False, "error": "GEMINI_API_KEY 없음"}

    guide_slugs, guide_lines = _existing_guide_slugs(site_id, repo)
    univ_keys, univ_lines = _existing_univ_keys(site_id, repo)

    blocks = []
    if g_n:
        blocks.append(f"Generate exactly {g_n} guide_topics (study abroad guides for Japan).")
    if u_n:
        blocks.append(f"Generate exactly {u_n} universities (real Japanese universities).")

    prompt = f"""You are an editor for JP Campus — study-in-Japan content for international students.
{chr(10).join(blocks)}

Existing guide slugs: {", ".join(sorted(guide_slugs)[:40])}
Guide samples:
{chr(10).join(f"- {t}" for t in guide_lines[:30]) or "(none)"}

Existing universities (do not duplicate):
{", ".join(list(univ_keys)[:50])}

Return ONLY valid JSON (omit empty arrays):
{{
  "guide_topics": [
    {{
      "slug": "cost-of-living-osaka",
      "category": "Budget",
      "title": "Cost of Living in Osaka for Students",
      "description": "Monthly budget breakdown",
      "prompt": "Write a practical monthly cost guide for students in Osaka."
    }}
  ],
  "universities": [
    {{
      "name_ja": "東京大学",
      "name_en": "The University of Tokyo",
      "region": "Tokyo"
    }}
  ]
}}

Rules:
- use real Japanese university names; name_ja in Japanese characters
- guide slug: kebab-case; category: Budget | Visa | Housing | Work | Life | Exam | Culture | Region
- prompt: detailed instruction for AI writer (English)
"""
    if logf:
        logf.write(f"JP Campus AI: 가이드 {g_n} · 대학 {u_n}건 단일 요청\n")

    data = _gemini_json(prompt) or {}
    guide_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "guide_topics")
    univ_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "universities")

    slugs = set(guide_slugs)
    new_guides: list[dict[str, str]] = []
    for item in data.get("guide_topics") or []:
        if not isinstance(item, dict) or len(new_guides) >= g_n:
            break
        row = _parse_guide_row(item, slugs, "Japan")
        if row:
            new_guides.append(row)

    univs = set(univ_keys)
    new_univs: list[dict[str, str]] = []
    for item in data.get("universities") or []:
        if not isinstance(item, dict) or len(new_univs) >= u_n:
            break
        row = _parse_jp_univ_row(item, univs)
        if row:
            new_univs.append(row)

    added_g = _append_bank_rows(site_id, guide_spec, new_guides) if g_n else 0
    added_u = _append_bank_rows(site_id, univ_spec, new_univs) if u_n else 0
    from topic_bank_pipeline import refresh_topic_state

    refresh_topic_state(site_id, repo)

    total = added_g + added_u
    if logf:
        logf.write(f"  → 가이드 {added_g} · 대학 {added_u}건\n")

    messages = []
    if added_g:
        messages.append(f"가이드 +{added_g}")
    if added_u:
        messages.append(f"대학 +{added_u}")
    if not total:
        messages.append("AI가 생성했지만 중복/검증 실패로 추가된 행 없음")

    return {
        "ok": True,
        "rows_added": total,
        "bank_rows_added": total,
        "bank_appended": {"guide_topics": added_g, "universities": added_u},
        "expanded": total,
        "expanded_guides": added_g,
        "expanded_items": added_u,
        "messages": messages,
        "guide_count_requested": g_n,
        "university_count_requested": u_n,
    }


def append_jpcampus_guides(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    guide_count: int = DEFAULT_GUIDE_COUNT,
) -> dict[str, Any]:
    return append_jpcampus_topics(
        site_id, repo, logf, guide_count=guide_count, university_count=0
    )


def append_krcampus_topics(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    guide_count: int = DEFAULT_GUIDE_COUNT,
    school_count: int = DEFAULT_SCHOOL_COUNT,
    university_count: int = DEFAULT_UNIVERSITY_COUNT,
) -> dict[str, Any]:
    if site_id != "krcampus":
        return {"ok": False, "error": f"unsupported site {site_id}"}

    g_n = _clamp_count(guide_count, DEFAULT_GUIDE_COUNT, MAX_GUIDE_COUNT)
    s_n = _clamp_count(school_count, DEFAULT_SCHOOL_COUNT, MAX_SCHOOL_COUNT)
    u_n = _clamp_count(university_count, DEFAULT_UNIVERSITY_COUNT, MAX_UNIVERSITY_COUNT)
    if g_n == 0 and s_n == 0 and u_n == 0:
        return {"ok": False, "error": "guide_count, school_count, university_count are all 0"}
    if not ensure_gemini_api_key():
        return {"ok": False, "error": "GEMINI_API_KEY 없음"}

    guide_slugs, guide_lines = _existing_guide_slugs(site_id, repo)
    school_keys, _school_lines = _existing_school_keys(site_id, repo)
    univ_keys, _univ_lines = _existing_univ_keys(site_id, repo)
    school_bank_lines = _bank_institution_lines(site_id, "language_schools")
    univ_bank_lines = _bank_institution_lines(site_id, "universities")
    _, school_gap_regions = _region_gap_block(site_id, "language_schools")
    _, univ_gap_regions = _region_gap_block(site_id, "universities")
    _, guide_gap_categories = _guide_gap_block(site_id)

    prompt = _build_krcampus_gap_prompt(
        g_n=g_n,
        s_n=s_n,
        u_n=u_n,
        guide_slugs=guide_slugs,
        guide_lines=guide_lines,
        school_keys=school_keys,
        school_bank_lines=school_bank_lines,
        univ_keys=univ_keys,
        univ_bank_lines=univ_bank_lines,
        school_gap_regions=school_gap_regions,
        univ_gap_regions=univ_gap_regions,
        guide_gap_categories=guide_gap_categories,
    )
    if logf:
        logf.write(f"KR Campus AI: 가이드 {g_n} · 어학원 {s_n} · 대학 {u_n}건 (갭 채우기)\n")
        if school_gap_regions:
            logf.write(f"  어학원 우선 지역: {', '.join(school_gap_regions[:6])}\n")
        if univ_gap_regions:
            logf.write(f"  대학 우선 지역: {', '.join(univ_gap_regions[:6])}\n")

    data = _gemini_json(prompt) or {}
    new_guides, new_schools, new_univs = _parse_krcampus_response(
        data,
        g_n=g_n,
        s_n=s_n,
        u_n=u_n,
        guide_slugs=guide_slugs,
        school_keys=school_keys,
        univ_keys=univ_keys,
    )

    need_s = s_n - len(new_schools)
    need_u = u_n - len(new_univs)
    need_g = g_n - len(new_guides)
    if (need_s > 0 or need_u > 0 or need_g > 0) and ensure_gemini_api_key():
        rejected: list[str] = []
        for item in data.get("language_schools") or []:
            if isinstance(item, dict) and (item.get("name_ko") or item.get("name_en")):
                rejected.append(str(item.get("name_ko") or item.get("name_en")))
        for item in data.get("universities") or []:
            if isinstance(item, dict) and (item.get("name_ko") or item.get("name_en")):
                rejected.append(str(item.get("name_ko") or item.get("name_en")))
        retry_note = (
            f"RETRY: Previous suggestions were duplicates or invalid: {', '.join(rejected[:12])}. "
            f"Still need {need_g} guides, {need_s} schools, {need_u} universities — "
            "pick completely different institutions from the priority regions."
        )
        if logf:
            logf.write(f"  갭 재시도: 가이드 {need_g} · 어학원 {need_s} · 대학 {need_u}\n")
        retry_prompt = _build_krcampus_gap_prompt(
            g_n=need_g,
            s_n=need_s,
            u_n=need_u,
            guide_slugs=guide_slugs | {r["slug"] for r in new_guides},
            guide_lines=guide_lines,
            school_keys=school_keys | {r["name_ko"] for r in new_schools} | {r["name_en"].lower() for r in new_schools},
            school_bank_lines=school_bank_lines,
            univ_keys=univ_keys | {r["name_ko"] for r in new_univs} | {r["name_en"].lower() for r in new_univs},
            univ_bank_lines=univ_bank_lines,
            school_gap_regions=school_gap_regions,
            univ_gap_regions=univ_gap_regions,
            guide_gap_categories=guide_gap_categories,
            retry_note=retry_note,
        )
        retry_data = _gemini_json(retry_prompt) or {}
        more_g, more_s, more_u = _parse_krcampus_response(
            retry_data,
            g_n=need_g,
            s_n=need_s,
            u_n=need_u,
            guide_slugs=guide_slugs | {r["slug"] for r in new_guides},
            school_keys=school_keys | {r["name_ko"] for r in new_schools} | {r["name_en"].lower() for r in new_schools},
            univ_keys=univ_keys | {r["name_ko"] for r in new_univs} | {r["name_en"].lower() for r in new_univs},
        )
        new_guides.extend(more_g)
        new_schools.extend(more_s)
        new_univs.extend(more_u)

    guide_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "guide_topics")
    school_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "language_schools")
    univ_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "universities")

    added_g = _append_bank_rows(site_id, guide_spec, new_guides) if g_n else 0
    added_s = _append_bank_rows(site_id, school_spec, new_schools) if s_n else 0
    added_u = _append_bank_rows(site_id, univ_spec, new_univs) if u_n else 0
    from topic_bank_pipeline import refresh_topic_state

    refresh_topic_state(site_id, repo)

    total = added_g + added_s + added_u
    if logf:
        logf.write(f"  → 가이드 {added_g} · 어학원 {added_s} · 대학 {added_u}건\n")

    messages = []
    if added_g:
        messages.append(f"가이드 +{added_g}")
    if added_s:
        messages.append(f"어학원 +{added_s}")
    if added_u:
        messages.append(f"대학 +{added_u}")
    if not total:
        messages.append("AI가 생성했지만 중복/검증 실패로 추가된 행 없음")

    return {
        "ok": True,
        "rows_added": total,
        "bank_rows_added": total,
        "bank_appended": {
            "guide_topics": added_g,
            "language_schools": added_s,
            "universities": added_u,
        },
        "expanded": total,
        "expanded_guides": added_g,
        "expanded_items": added_s + added_u,
        "messages": messages,
        "guide_count_requested": g_n,
        "school_count_requested": s_n,
        "university_count_requested": u_n,
    }
