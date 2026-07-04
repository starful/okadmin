"""POI sites (okramen, okonsen, okcaddie): AI item/guide rows for topic bank (목록 추가)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config_gemini import ensure_gemini_api_key
from statfacts_topic_ai import _clamp_count, _gemini_json, _normalize_id
from topic_bank import _append_bank_rows, read_bank
from topic_bank_registry import banks_for_site

POI_AI_SITES: tuple[str, ...] = ("okramen", "okonsen", "okcaddie")

DEFAULT_ITEM_COUNT = 6
DEFAULT_GUIDE_COUNT = 3
MAX_ITEM_COUNT = 30
MAX_GUIDE_COUNT = 15

_SITE_META: dict[str, dict[str, Any]] = {
    "okramen": {
        "domain": "OK Ramen — ramen shops in Japan for travelers",
        "item_noun": "ramen shop",
        "guide_theme": "ramen dining and travel guides for Japan",
        "extra_item_fields": '"Thumbnail": "", "Agoda": ""',
        "features_hint": "tonkotsu, shoyu, tsukemen, miso, regional styles",
    },
    "okonsen": {
        "domain": "OK Onsen — hot springs and ryokan baths in Japan",
        "item_noun": "onsen or ryokan bath facility",
        "guide_theme": "onsen etiquette and travel guides for Japan",
        "extra_item_fields": '"Thumbnail": "", "Agoda": ""',
        "features_hint": "rotenburo, indoor bath, day-trip onsen, ryokan stay",
    },
    "okcaddie": {
        "domain": "OK Caddie — golf courses in Japan for golfers",
        "item_noun": "golf course",
        "guide_theme": "golf travel and booking guides for Japan",
        "extra_item_fields": '"Booking": ""',
        "features_hint": "public course, resort course, links, mountain course",
    },
}


def _existing_item_keys(site_id: str, repo: Path) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    lines: list[str] = []
    for row in read_bank(site_id, "items"):
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        key = name.lower()
        names.add(key)
        lat = (row.get("Lat") or "").strip()
        lng = (row.get("Lng") or "").strip()
        lines.append(f"{name} ({lat}, {lng})")
    content = repo / "app" / "content"
    if content.is_dir():
        for md in content.glob("*_en.md"):
            stem = md.stem.replace("_en", "")
            names.add(stem.replace("_", " ").lower())
    return names, lines


def _existing_guide_ids(site_id: str, repo: Path) -> set[str]:
    ids: set[str] = set()
    for row in read_bank(site_id, "guides"):
        gid = _normalize_id(row.get("id") or "")
        if gid:
            ids.add(gid)
    guides_dir = repo / "app" / "content" / "guides"
    if guides_dir.is_dir():
        for md in guides_dir.glob("*.md"):
            ids.add(md.stem.replace("_en", ""))
    return ids


def _existing_guide_topics(site_id: str) -> list[str]:
    lines: list[str] = []
    for row in read_bank(site_id, "guides"):
        gid = (row.get("id") or "").strip()
        if not gid:
            continue
        topic = (row.get("topic_en") or gid).strip()
        lines.append(f"{gid}: {topic}")
    return lines


def _parse_item_row(
    site_id: str,
    item: dict[str, Any],
    existing_names: set[str],
) -> dict[str, str] | None:
    name = str(item.get("Name") or "").strip()
    if not name or name.lower() in existing_names:
        return None
    lat = str(item.get("Lat") or "").strip()
    lng = str(item.get("Lng") or "").strip()
    if not lat or not lng:
        return None
    try:
        lat_f, lng_f = float(lat), float(lng)
    except ValueError:
        return None
    if not (20.0 <= lat_f <= 46.5 and 122.0 <= lng_f <= 154.5):
        return None
    address = str(item.get("Address") or "").strip()
    features = str(item.get("Features") or "").strip()
    if not address or not features:
        return None
    row: dict[str, str] = {
        "Name": name,
        "Lat": lat,
        "Lng": lng,
        "Address": address,
        "Features": features,
    }
    if site_id in ("okramen", "okonsen"):
        row["Thumbnail"] = str(item.get("Thumbnail") or "").strip()
        row["Agoda"] = str(item.get("Agoda") or "").strip()
    elif site_id == "okcaddie":
        row["Booking"] = str(item.get("Booking") or "").strip()
    existing_names.add(name.lower())
    return row


def _parse_guide_row(item: dict[str, Any], existing_ids: set[str]) -> dict[str, str] | None:
    gid = _normalize_id(str(item.get("id") or ""))
    if not gid or gid in existing_ids:
        return None
    row = {
        "id": gid,
        "topic_en": str(item.get("topic_en") or gid).strip(),
        "topic_ko": str(item.get("topic_ko") or "").strip(),
        "keywords": str(item.get("keywords") or "").strip(),
    }
    if not row["topic_en"]:
        return None
    existing_ids.add(gid)
    return row


def _generate_topics_batch(
    site_id: str,
    item_n: int,
    guide_n: int,
    existing_names: set[str],
    existing_item_lines: list[str],
    existing_guide_ids: set[str],
    existing_guide_topics: list[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    meta = _SITE_META.get(site_id)
    if not meta or (item_n <= 0 and guide_n <= 0):
        return [], []

    item_avoid = "\n".join(f"- {t}" for t in existing_item_lines[:60]) or "(none)"
    guide_avoid = "\n".join(f"- {t}" for t in existing_guide_topics[:50]) or "(none)"

    item_block = ""
    if item_n > 0:
        item_block = f"""
Generate exactly {item_n} NEW real {meta["item_noun"]} rows in Japan.
Use plausible coordinates (Lat/Lng) for the Address prefecture/city.
Do NOT duplicate these existing names or near-duplicates:
{", ".join(sorted(existing_names)[:80])}

Existing items (sample):
{item_avoid}

Features examples: {meta["features_hint"]}
"""

    guide_block = ""
    if guide_n > 0:
        guide_block = f"""
Generate exactly {guide_n} NEW travel GUIDE topics about {meta["guide_theme"]} (not single POI listings).
Include topic_ko in Korean. Do NOT duplicate guide ids or topics:
ids: {", ".join(sorted(existing_guide_ids)[:80])}

Existing guides:
{guide_avoid}
"""

    if site_id == "okcaddie":
        item_json = """{ "Name": "Course Name", "Lat": "35.0", "Lng": "135.0", "Address": "Prefecture, City", "Features": "public | 18 holes", "Booking": "" }"""
    else:
        item_json = """{ "Name": "Shop Name", "Lat": "35.0", "Lng": "135.0", "Address": "Prefecture, City", "Features": "style | notes", "Thumbnail": "", "Agoda": "" }"""

    prompt = f"""You are a travel content editor for {meta["domain"]}.
{item_block}
{guide_block}
Return ONLY valid JSON:
{{
  "items": [
    {item_json}
  ],
  "guides": [
    {{
      "id": "kebab-case-slug",
      "topic_en": "Guide title in English",
      "topic_ko": "한국어 제목",
      "keywords": "comma separated"
    }}
  ]
}}

Rules:
- item Name must be unique and specific (realistic venue names)
- guide id: lowercase kebab-case, 3-5 words
- omit empty arrays
"""

    data = _gemini_json(prompt)
    if not data:
        return [], []

    names = set(existing_names)
    guide_ids = set(existing_guide_ids)
    items: list[dict[str, str]] = []
    for item in data.get("items") or []:
        if not isinstance(item, dict) or len(items) >= item_n:
            break
        row = _parse_item_row(site_id, item, names)
        if row:
            items.append(row)

    guides: list[dict[str, str]] = []
    for item in data.get("guides") or []:
        if not isinstance(item, dict) or len(guides) >= guide_n:
            break
        row = _parse_guide_row(item, guide_ids)
        if row:
            guides.append(row)

    return items, guides


def append_poi_topics(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    item_count: int = DEFAULT_ITEM_COUNT,
    guide_count: int = DEFAULT_GUIDE_COUNT,
) -> dict[str, Any]:
    if site_id not in POI_AI_SITES:
        return {"ok": False, "error": f"unsupported site {site_id}"}

    item_n = _clamp_count(item_count, DEFAULT_ITEM_COUNT, MAX_ITEM_COUNT)
    guide_n = _clamp_count(guide_count, DEFAULT_GUIDE_COUNT, MAX_GUIDE_COUNT)
    if item_n == 0 and guide_n == 0:
        return {"ok": False, "error": "item_count and guide_count are both 0"}

    if not ensure_gemini_api_key():
        return {"ok": False, "error": "GEMINI_API_KEY 없음"}

    item_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "items")
    guide_spec = next(s for s in banks_for_site(site_id) if s.bank_id == "guides")

    existing_names, existing_item_lines = _existing_item_keys(site_id, repo)
    existing_guide_ids = _existing_guide_ids(site_id, repo)

    if logf:
        logf.write(f"POI AI ({site_id}): 아이템 {item_n}건 · 가이드 {guide_n}건 단일 요청\n")

    new_items, new_guides = _generate_topics_batch(
        site_id,
        item_n,
        guide_n,
        existing_names,
        existing_item_lines,
        existing_guide_ids,
        _existing_guide_topics(site_id),
    )

    if logf:
        logf.write(f"  → 아이템 {len(new_items)}건 · 가이드 {len(new_guides)}건\n")

    added_i = _append_bank_rows(site_id, item_spec, new_items)
    added_g = _append_bank_rows(site_id, guide_spec, new_guides)
    from topic_bank_pipeline import refresh_topic_state

    refresh_topic_state(site_id, repo)

    total = added_i + added_g
    messages: list[str] = []
    if added_i:
        messages.append(f"아이템 +{added_i}")
    if added_g:
        messages.append(f"가이드 +{added_g}")
    if not total:
        messages.append("AI가 생성했지만 중복/검증 실패로 추가된 행 없음")

    return {
        "ok": True,
        "rows_added": total,
        "bank_rows_added": total,
        "bank_appended": {"items": added_i, "guides": added_g},
        "expanded": total,
        "expanded_items": added_i,
        "expanded_guides": added_g,
        "messages": messages,
        "item_count_requested": item_n,
        "guide_count_requested": guide_n,
    }
