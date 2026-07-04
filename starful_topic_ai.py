"""Starful Biz: AI position rows for topic bank (목록 추가)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config_gemini import ensure_gemini_api_key
from starful_assets import position_slug
from statfacts_topic_ai import _clamp_count, _gemini_json
from topic_bank import _append_bank_rows, read_bank
from topic_bank_registry import banks_for_site

DEFAULT_POSITION_COUNT = 6
MAX_POSITION_COUNT = 30


def _existing_positions(site_id: str, repo: Path) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    lines: list[str] = []
    for row in read_bank(site_id, "positions"):
        pos = (row.get("position_name") or "").strip()
        if not pos:
            continue
        names.add(pos.lower())
        lines.append(pos)
    out_dir = repo / "app/contents"
    if out_dir.is_dir():
        for md in out_dir.glob("*.md"):
            names.add(md.stem.replace("_", " ").lower())
    return names, lines


def _generate_positions(
    count: int,
    existing_names: set[str],
    existing_lines: list[str],
) -> list[dict[str, str]]:
    if count <= 0:
        return []
    avoid = "\n".join(f"- {t}" for t in existing_lines[:60]) or "(none)"
    prompt = f"""You are a tech career editor for Starful Biz (interview prep / job guides).
Generate exactly {count} NEW job position names for career guide content.

Focus on modern tech roles (engineering, product, data, design, security, etc.).
Do NOT duplicate these existing positions:
{", ".join(sorted(existing_names)[:80])}

Existing positions (sample):
{avoid}

Return ONLY valid JSON:
{{
  "positions": [
    {{ "position_name": "Site Reliability Engineer" }}
  ]
}}

Rules:
- position_name: clear English job title, 2-5 words
- no duplicates or near-duplicates
"""
    data = _gemini_json(prompt)
    if not data:
        return []
    names = set(existing_names)
    rows: list[dict[str, str]] = []
    for item in data.get("positions") or []:
        if not isinstance(item, dict) or len(rows) >= count:
            break
        pos = str(item.get("position_name") or "").strip()
        if not pos or pos.lower() in names:
            continue
        slug = position_slug(pos)
        if not slug:
            continue
        rows.append({"position_name": pos})
        names.add(pos.lower())
    return rows


def append_starful_positions(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    position_count: int = DEFAULT_POSITION_COUNT,
) -> dict[str, Any]:
    if site_id != "starful.biz":
        return {"ok": False, "error": f"unsupported site {site_id}"}

    n = _clamp_count(position_count, DEFAULT_POSITION_COUNT, MAX_POSITION_COUNT)
    if n == 0:
        return {"ok": False, "error": "position_count is 0"}

    if not ensure_gemini_api_key():
        return {"ok": False, "error": "GEMINI_API_KEY 없음"}

    spec = next(s for s in banks_for_site(site_id) if s.bank_id == "positions")
    existing_names, existing_lines = _existing_positions(site_id, repo)

    if logf:
        logf.write(f"Starful AI: 포지션 {n}건 단일 요청\n")

    new_rows = _generate_positions(n, existing_names, existing_lines)
    if logf:
        logf.write(f"  → {len(new_rows)}건\n")

    added = _append_bank_rows(site_id, spec, new_rows)
    from topic_bank_pipeline import refresh_topic_state

    refresh_topic_state(site_id, repo)

    messages = [f"포지션 +{added}"] if added else ["AI가 생성했지만 중복/검증 실패로 추가된 행 없음"]
    return {
        "ok": True,
        "rows_added": added,
        "bank_rows_added": added,
        "bank_appended": {"positions": added},
        "expanded": added,
        "expanded_items": added,
        "messages": messages,
        "position_count_requested": n,
    }
