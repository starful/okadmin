"""Instagram card-news prompt queue (local JSON under data/)."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import OKADMIN_ROOT
from config_gemini import ensure_gemini_api_key
from instagram_seed_data import build_seed_items
from instagram_site_profiles import (
    INSTAGRAM_PROFILE,
    instagram_common_rules,
    strip_slide_copy,
)

QUEUE_DIR = OKADMIN_ROOT / "data" / "instagram_prompts"
QUEUE_PATH = QUEUE_DIR / "queue.json"  # single shared Instagram queue
DEFAULT_BATCH_SIZE = 50
MAX_BATCH_SIZE = 50
_CHUNK = 10

# cover + 5 points + outro
SLIDE_COUNT = 7
POINT_COUNT = 5

_lock = threading.Lock()

# Alias — always the shared food-focused rules.
COMMON_RULES = instagram_common_rules()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def queue_file(site_id: str | None = None) -> Path:
    """Single shared queue (site_id ignored — kept for call-site compatibility)."""
    return QUEUE_PATH


def _empty_queue(site_id: str | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "site_id": None,
        "updated_at": _utc_now(),
        "common_rules": instagram_common_rules(),
        "next_batch": 1,
        "items": [],
    }


def ensure_queue(site_id: str | None = None) -> dict[str, Any]:
    with _lock:
        return _ensure_queue_unlocked(site_id)


def _ensure_queue_unlocked(site_id: str | None = None) -> dict[str, Any]:
    path = queue_file()
    rules = instagram_common_rules()
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = _empty_queue()
        data["common_rules"] = rules  # always refresh shared prompt
        data.setdefault("items", [])
        data.setdefault("next_batch", 1)
        data.setdefault("version", 1)
        data["site_id"] = None
        return data
    # Bootstrap with seed topics (tests + first run)
    batch = 1
    items = build_seed_items(batch=batch)
    data = {
        "version": 1,
        "site_id": None,
        "updated_at": _utc_now(),
        "common_rules": rules,
        "next_batch": batch + 1,
        "items": items,
    }
    _save_unlocked(data)
    return data


def _save_unlocked(data: dict[str, Any], site_id: str | None = None) -> None:
    data["updated_at"] = _utc_now()
    data["common_rules"] = instagram_common_rules()
    data["site_id"] = None
    path = queue_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def save_queue(data: dict[str, Any], site_id: str | None = None) -> None:
    with _lock:
        _save_unlocked(data, site_id)


def queue_stats(data: dict[str, Any] | None = None, site_id: str | None = None) -> dict[str, int]:
    data = data or ensure_queue(site_id)
    items = data.get("items") or []
    todo = sum(1 for i in items if i.get("status") != "done")
    done = sum(1 for i in items if i.get("status") == "done")
    return {
        "total": len(items),
        "todo": todo,
        "done": done,
        "next_batch": int(data.get("next_batch") or 1),
    }


def list_items(
    *,
    site_id: str | None = None,
    status: str | None = None,
    batch: int | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    data = ensure_queue(site_id)
    items = list(data.get("items") or [])
    if status:
        if status == "todo":
            items = [i for i in items if i.get("status") != "done"]
        else:
            items = [i for i in items if i.get("status") == status]
    if batch is not None:
        items = [i for i in items if int(i.get("batch") or 0) == batch]
    if category:
        items = [i for i in items if (i.get("category") or "") == category]
    items.sort(key=lambda x: (int(x.get("batch") or 0), x.get("id") or ""))
    return items


def get_item(item_id: str, site_id: str | None = None) -> dict[str, Any] | None:
    for item in ensure_queue(site_id).get("items") or []:
        if item.get("id") == item_id:
            return item
    return None


def set_status(item_id: str, status: str, site_id: str | None = None) -> dict[str, Any] | None:
    if status not in ("todo", "done"):
        raise ValueError("status must be todo or done")
    with _lock:
        data = _ensure_queue_unlocked(site_id)
        for item in data.get("items") or []:
            if item.get("id") != item_id:
                continue
            item["status"] = status
            item["done_at"] = _utc_now() if status == "done" else None
            _save_unlocked(data, site_id)
            return item
    return None


def patch_item(item_id: str, fields: dict[str, Any], site_id: str | None = None) -> dict[str, Any] | None:
    """Merge fields into a queue item (render progress, cardnews path, etc.)."""
    with _lock:
        data = _ensure_queue_unlocked(site_id)
        for item in data.get("items") or []:
            if item.get("id") != item_id:
                continue
            for k, v in fields.items():
                if v is None and k in item:
                    # keep explicit None for errors
                    item[k] = None
                else:
                    item[k] = v
            _save_unlocked(data, site_id)
            return item
    return None


def format_gemini_prompt(
    item: dict[str, Any],
    common_rules: str | None = None,
    *,
    site_id: str | None = None,
) -> str:
    rules = (common_rules or instagram_common_rules()).strip()
    lines = [
        rules,
        "",
        "[로고] 이미지 생성 전에 「OK - JAPAN」원형 로고 파일을 채팅에 반드시 첨부할 것.",
        "로고는 매 장 상단(좌 또는 우)에 작게. 로고를 새로 그리지 말 것.",
        "",
        f"[주제] {item.get('topic') or ''}",
        "",
    ]
    for slide in item.get("slides") or []:
        kind = slide.get("kind") or "point"
        if kind == "cover":
            lines.append("[1장 표지]")
            lines.append(f"제목: {strip_slide_copy(slide.get('title') or '')}")
            lines.append(f"부제: {strip_slide_copy(slide.get('body') or '')}")
            lines.append(f"하단 일러스트: {slide.get('art') or ''}")
        elif kind == "outro":
            lines.append(f"[{SLIDE_COUNT}장 마무리]")
            lines.append(f"제목: {strip_slide_copy(slide.get('title') or '')}")
            lines.append(f"본문: {strip_slide_copy(slide.get('body') or '')}")
            lines.append("사이트 URL 넣지 말 것. 저장 유도만.")
            lines.append(f"하단 일러스트: {slide.get('art') or ''}")
        else:
            num = slide.get("num") or ""
            try:
                slide_no = int(num) + 1  # 01 → 2장 (표지 다음)
            except ValueError:
                slide_no = None
            lines.append(f"[{slide_no}장]" if slide_no else "[내용 장]")
            if num:
                lines.append(f"번호: {num}")
            lines.append(f"제목: {strip_slide_copy(slide.get('title') or '')}")
            lines.append(f"본문: {strip_slide_copy(slide.get('body') or '')}")
            lines.append(f"하단 일러스트: {slide.get('art') or ''}")
        lines.append("")
    lines.append(
        f"지금 1장부터 생성해. 총 {SLIDE_COUNT}장. 모든 장 Instagram 4:5 (1080×1350). "
        "확인 말고 이미지 출력. 마무리 장에 URL 넣지 말 것."
    )
    return "\n".join(lines).strip() + "\n"


def format_caption_block(item: dict[str, Any]) -> str:
    tags = item.get("hashtags") or []
    tag_line = " ".join(tags) if isinstance(tags, list) else str(tags)
    caption = (item.get("caption") or "").strip()
    if tag_line:
        return f"{caption}\n\n{tag_line}\n" if caption else f"{tag_line}\n"
    return caption + ("\n" if caption else "")


def used_topics(data: dict[str, Any] | None = None, site_id: str | None = None) -> list[str]:
    data = data or ensure_queue(site_id)
    out: list[str] = []
    for item in data.get("items") or []:
        t = (item.get("topic") or "").strip()
        if t:
            out.append(t)
    return out


def _gemini_json(prompt: str) -> dict[str, Any] | None:
    from llm_claude import claude_json, ensure_llm

    if not ensure_llm():
        return None
    return claude_json(prompt)


def _normalize_generated_item(
    raw: dict[str, Any],
    *,
    batch: int,
    seq: int,
    site_id: str | None = None,
) -> dict[str, Any] | None:
    topic = strip_slide_copy(raw.get("topic") or "")
    if not topic:
        return None
    category = (raw.get("category") or "general").strip().lower() or "general"
    slides_in = raw.get("slides") or []
    if not isinstance(slides_in, list) or len(slides_in) < SLIDE_COUNT:
        return None
    slides: list[dict[str, Any]] = []
    for idx, s in enumerate(slides_in[:SLIDE_COUNT]):
        if not isinstance(s, dict):
            return None
        if idx == 0:
            kind = "cover"
            num = None
        elif idx == SLIDE_COUNT - 1:
            kind = "outro"
            num = None
        else:
            kind = "point"
            num = f"{idx:02d}"
        slides.append(
            {
                "kind": kind,
                **({"num": num} if num else {}),
                "title": strip_slide_copy(s.get("title") or topic),
                "body": strip_slide_copy(s.get("body") or ""),
                "art": (s.get("art") or "주제 관련 큰 일러스트").strip(),
            }
        )
    profile = INSTAGRAM_PROFILE
    default_tags = profile.get("hashtags") or [
        "#일본여행",
        "#일본먹거리",
        "#여행카드뉴스",
    ]
    hashtags = raw.get("hashtags") or default_tags
    if isinstance(hashtags, str):
        hashtags = [h for h in hashtags.split() if h]
    caption = (raw.get("caption") or f"{topic}\n\n일본 먹거리 카드뉴스. 저장해두고 보세요.").strip()
    return {
        "id": f"ig-{batch:02d}-{seq:03d}",
        "batch": batch,
        "category": category,
        "topic": topic,
        "status": "todo",
        "done_at": None,
        "slides": slides,
        "caption": caption,
        "hashtags": hashtags,
        "site_url": None,
    }


def _generation_prompt(
    count: int,
    exclude_topics: list[str],
    categories_hint: str,
    *,
    site_id: str | None = None,
) -> str:
    exclude_block = "\n".join(f"- {t}" for t in exclude_topics[-200:]) or "(없음)"
    point_slides = ",\n        ".join(
        [f'{{"title": "포인트{i}", "body": "본문 1~2문장", "art": "..."}}' for i in range(1, POINT_COUNT + 1)]
    )
    profile = INSTAGRAM_PROFILE
    theme = profile["theme"]
    audience = profile["audience"]
    tags = ", ".join(profile.get("hashtags") or [])
    return f"""You generate Instagram card-news briefs for a Korean-language Japan food account.

Brand theme: {theme}
Audience: {audience}
Suggested hashtags: {tags}

Topic priority:
1) PRIMARY — food, meat/seafood cuts, menu words, how to order (yakiniku, yakitori, izakaya, ramen, sushi)
2) SECONDARY — dining manners, transport (only when useful for travelers)
Do NOT generate golf, onsen, study-abroad, hiring, or other non-food verticals.

Return JSON only:
{{
  "items": [
    {{
      "category": "one of: {categories_hint}",
      "topic": "한국어 주제 제목",
      "caption": "인스타 캡션 한국어 2~4문장",
      "hashtags": ["#태그1", "..."],
      "slides": [
        {{"title": "표지 제목", "body": "부제", "art": "하단 일러스트 설명"}},
        {point_slides},
        {{"title": "마무리 제목", "body": "저장 유도만 (URL 없음)", "art": "..."}}
      ]
    }}
  ]
}}

Rules:
- Exactly {count} items in "items".
- Each slides array must have exactly {SLIDE_COUNT} objects (cover, {POINT_COUNT} points, outro).
- Korean copy only for topic/titles/bodies/caption.
- No sentence-ending punctuation (. ? !) on topic, titles, or bodies — card slides only.
- Stay inside the food/menu/cuts theme; etiquette/transport only as supporting tips.
- Practical, friendly, mobile-readable tips.
- Each slide art field must describe a UNIQUE scene/background; no repeated illustration across the {SLIDE_COUNT} slides.
- Point bodies must be concrete. No generic filler alone.
- Image size for every slide when rendered: Instagram portrait 4:5 (1080x1350).
- The last slide (outro) must NOT include any website URL or domain. Save/share CTA only.
- Do NOT repeat any of these existing topics:
{exclude_block}
- Mix categories roughly like: {categories_hint} (favor food/cuts/menu/order).
- No duplicate topics within this response.
"""


def generate_next_batch(
    count: int = DEFAULT_BATCH_SIZE,
    *,
    site_id: str | None = None,
) -> dict[str, Any]:
    """Append a new batch via Gemini. Returns {ok, added, batch, error?}."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = DEFAULT_BATCH_SIZE
    count = max(1, min(count, MAX_BATCH_SIZE))

    if not ensure_gemini_api_key():
        return {"ok": False, "error": "Claude CLI 미로그인 — `claude` 후 /login", "added": 0}

    categories_hint = INSTAGRAM_PROFILE.get("categories") or (
        "food, cuts, menu, order, etiquette, transport"
    )

    with _lock:
        data = _ensure_queue_unlocked()
        data["common_rules"] = instagram_common_rules()
        batch = int(data.get("next_batch") or 1)
        existing = used_topics(data)
        existing_set = {t.lower() for t in existing}

        new_items: list[dict[str, Any]] = []
        seq = 1
        remaining = count
        exclude = list(existing)

        while remaining > 0:
            chunk = min(_CHUNK, remaining)
            prompt = _generation_prompt(chunk, exclude, categories_hint)
            parsed = _gemini_json(prompt)
            if not parsed:
                if new_items:
                    break
                return {
                    "ok": False,
                    "error": "Claude 응답 파싱 실패",
                    "added": 0,
                    "batch": batch,
                }
            raw_items = parsed.get("items") or []
            if not isinstance(raw_items, list) or not raw_items:
                if new_items:
                    break
                return {
                    "ok": False,
                    "error": "Claude가 items를 반환하지 않음",
                    "added": 0,
                    "batch": batch,
                }
            got = 0
            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                topic = (raw.get("topic") or "").strip()
                if not topic or topic.lower() in existing_set:
                    continue
                item = _normalize_generated_item(raw, batch=batch, seq=seq)
                if not item:
                    continue
                new_items.append(item)
                existing_set.add(topic.lower())
                exclude.append(topic)
                seq += 1
                got += 1
                if len(new_items) >= count:
                    break
            if got == 0:
                break
            remaining = count - len(new_items)

        if not new_items:
            return {
                "ok": False,
                "error": "생성 결과가 비어 있음 (중복 또는 형식 오류)",
                "added": 0,
                "batch": batch,
            }

        data.setdefault("items", []).extend(new_items)
        data["next_batch"] = batch + 1
        _save_unlocked(data)
        return {
            "ok": True,
            "added": len(new_items),
            "batch": batch,
            "ids": [i["id"] for i in new_items],
            "stats": queue_stats(data),
        }


def reset_to_seed(site_id: str | None = None) -> dict[str, Any]:
    """Replace shared queue with seed topics (site_id ignored)."""
    with _lock:
        items = build_seed_items(batch=1)
        data = {
            "version": 1,
            "site_id": None,
            "updated_at": _utc_now(),
            "common_rules": instagram_common_rules(),
            "next_batch": 2,
            "items": items,
        }
        _save_unlocked(data)
        return {"ok": True, "stats": queue_stats(data)}


def md_suggestions(site_id: str = "", *, limit: int = 12) -> dict[str, Any]:
    """MD suggestions disabled for shared Instagram queue."""
    return {"ok": True, "suggestions": [], "site_id": None}


def enqueue_md_suggestions(
    site_id: str = "",
    *,
    titles: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """MD enqueue disabled — Instagram is not tied to site markdown."""
    data = ensure_queue()
    return {"ok": True, "added": 0, "stats": queue_stats(data), "message": "MD enqueue disabled"}
