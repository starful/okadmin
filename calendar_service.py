"""Unified calendar: ops_events + todos."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from config import (
    CALENDAR_VISIBLE_KINDS,
    CALENDAR_WINDOW_DAYS,
    COL_OPS_EVENTS,
    COL_TODOS,
    SITE_COLORS,
)
from jp_holidays import holidays_between

# 칩 글자: 작업 종류 (색은 사이트별만)
_WORK_TYPE_SHORT = {
    "gsc": "GSC",
    "content": "컨텐츠",
    "feature": "기능",
    "git": "git",
    "todo": "TODO",
    "deploy": "배포",
    "manual": "메모",
    "other": "기타",
}

_PHASE_LABEL = {"planned": "예정", "done": "실행", "skipped": "skip"}
# 예정: 사이트 색 없이 통일
PLANNED_BG = "#3a3a3a"
PLANNED_TEXT = "#bbbbbb"
_LOGGED_WORK_TYPES = frozenset(
    {"git", "gsc", "content", "feature", "deploy", "other", "git_push"}
)

_GSC_HINTS = re.compile(
    r"gsc|search\s*console|검색\s*콘솔|"
    r"고노출|저ctr|저\s*ctr|"
    r"\bctr\b|impressions?|clicks?|"
    r"serp|\bseo\b",
    re.I,
)
_FEATURE_HINTS = re.compile(
    r"feat(\(|:)|feature|기능(\s*추가|추가)|"
    r"implement|integration|gtm|container|snippet|"
    r"add\s+.+\s+support",
    re.I,
)
_CONTENT_HINTS = re.compile(
    r"content|contents|article|guide|editorial|"
    r"컨텐츠|콘텐츠|본문|"
    r"add\s+(page|post|guide|article)|new\s+page|"
    r"expand|populate|copy\b|markdown|"
    r"upload.*(image|photo|media)",
    re.I,
)
from firestore_db import doc_to_dict, get_db


def _parse_date_only(val: Any) -> str | None:
    if not val:
        return None
    s = str(val)
    if "T" in s:
        return s.split("T", 1)[0]
    return s[:10] if len(s) >= 10 else None


def _text_on_bg(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "#fff"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#111" if lum > 0.6 else "#fff"


def _clean_event_title(doc: dict) -> str:
    raw = (doc.get("title") or "").strip()
    raw = re.sub(r"^(git|GSC|TODO)\s*·\s*", "", raw, flags=re.I)
    raw = re.sub(r"^Auto Register\s*·\s*", "", raw, flags=re.I)
    if re.match(r"^[\d:\s\-–]+$", raw):
        return ""
    return raw[:120] if raw else "(no title)"


def _calendar_display_title(doc: dict) -> str:
    site = (doc.get("site_id") or "").strip()
    body = _clean_event_title(doc)
    wt = _work_type(doc)
    tag = _WORK_TYPE_SHORT.get(wt, wt)
    if doc.get("status") == "done":
        body = f"✓ {body}"
    return f"{site} · {tag} · {body}"


def _infer_work_type_from_text(doc: dict) -> str:
    combined = f"{doc.get('title') or ''}\n{doc.get('notes') or ''}\n{doc.get('body') or ''}"
    if _GSC_HINTS.search(combined):
        return "gsc"
    if _FEATURE_HINTS.search(combined):
        return "feature"
    if _CONTENT_HINTS.search(combined):
        return "content"
    return "git"


def _work_type(doc: dict) -> str:
    """표시용 작업 종류 (색과 무관)."""
    kind = doc.get("kind") or "manual"
    if kind == "gsc":
        return "gsc"
    if kind == "content":
        return "content"
    if kind in ("git_push", "other"):
        return _infer_work_type_from_text(doc)
    if kind == "todo":
        return "todo"
    if kind == "deploy":
        return "deploy"
    return kind


def _colors_for_doc(doc: dict, *, phase: str) -> tuple[str, str]:
    """(배경, 글자). 예정=회색 통일, 실행=사이트 색."""
    if phase == "planned":
        return PLANNED_BG, PLANNED_TEXT
    if phase == "skipped":
        return "#444444", "#999999"
    site = (doc.get("site_id") or "").strip()
    bg = SITE_COLORS[site] if site and site in SITE_COLORS else "#888780"
    return bg, _text_on_bg(bg)


_WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")


def _doc_event_date(doc: dict) -> str | None:
    return _parse_date_only(
        doc.get("start_at") or doc.get("due_at") or doc.get("created_at")
    )


def _parse_run_status(doc: dict) -> str | None:
    notes = doc.get("notes") or doc.get("body") or ""
    m = re.search(r"run=(\w+)", notes)
    return m.group(1) if m else None


def _execution_phase(doc: dict, event_date: str, *, today: date | None = None) -> str:
    """planned=예정, done=실행(완료), skipped."""
    today = today or date.today()
    ev_d = date.fromisoformat(event_date)
    work_type = _work_type(doc)
    title = doc.get("title") or ""
    run = doc.get("run_status") or _parse_run_status(doc)

    if run == "skipped" or "(skip)" in title:
        return "skipped"
    if doc.get("status") == "done":
        return "done"

    if work_type in _LOGGED_WORK_TYPES:
        return "done"

    if work_type == "todo":
        return "done" if doc.get("status") == "done" else "planned"

    if ev_d > today:
        return "planned"
    return "done"


def calendar_item_visible(doc: dict, *, source_collection: str = "ops_events") -> bool:
    if source_collection == "todos":
        return False
    kind = (doc.get("kind") or "manual").strip()
    return kind in CALENDAR_VISIBLE_KINDS


def _event_summary(doc: dict) -> str:
    kind = (doc.get("kind") or "").strip()
    title = (doc.get("title") or "").strip()
    failed = "실패" in title
    if kind == "content":
        return "콘텐츠 실패" if failed else "콘텐츠 완료"
    if kind == "gsc":
        pat_m = re.search(r"(저노출|저CTR)", title)
        pat = pat_m.group(1) if pat_m else "SEO"
        cnt_m = re.search(r"(\d+)\s*건", title)
        cnt = f" {cnt_m.group(1)}건" if cnt_m else ""
        status = "실패" if failed else "완료"
        return f"GSC {pat}{cnt} {status}"
    wt = _WORK_TYPE_SHORT.get(kind, kind)
    return f"{wt} 실패" if failed else wt


def _merge_day_items(items: list[dict]) -> list[dict]:
    """One chip per site+kind per day; stack run count when duplicated."""
    merged: dict[str, dict] = {}
    for item in items:
        key = f"{item['site_id']}:{item.get('kind') or item.get('work_type') or 'other'}"
        if key not in merged:
            merged[key] = {**item, "run_count": 1}
            continue
        row = merged[key]
        row["run_count"] = int(row.get("run_count") or 1) + 1
        if "실패" in (item.get("summary") or ""):
            row["summary"] = item.get("summary")
        prev = (row.get("notes") or "").strip()
        nxt = (item.get("notes") or "").strip()
        if nxt and nxt not in prev:
            row["notes"] = f"{prev}\n---\n{nxt}".strip()[:2000] if prev else nxt[:2000]
    out: list[dict] = []
    for row in merged.values():
        rc = int(row.pop("run_count", 1))
        summary = row.get("summary") or "작업"
        if rc > 1:
            base = summary.replace(" ×", "").split(" ×")[0]
            row["summary"] = f"{base} ×{rc}"
        out.append(row)
    return out


def doc_to_day_item(doc: dict, *, source_collection: str = "ops_events") -> dict | None:
    if not calendar_item_visible(doc, source_collection=source_collection):
        return None
    site = (doc.get("site_id") or "").strip()
    if not site:
        return None
    day = _doc_event_date(doc)
    if not day:
        return None
    work_type = "todo" if source_collection == "todos" else _work_type(doc)
    body = _clean_event_title(doc)
    phase = _execution_phase(doc, day)
    color, text_color = _colors_for_doc(doc, phase=phase)
    phase_label = _PHASE_LABEL[phase]
    type_label = _WORK_TYPE_SHORT.get(work_type, work_type)
    tag = f"{phase_label}·{type_label}"
    chip_title = body if body and body != "(no title)" else site
    summary = _event_summary(doc)
    record_id = doc["id"]
    cal_id = f"evt-{record_id}" if source_collection == "ops_events" else f"todo-{record_id}"
    return {
        "cal_id": cal_id,
        "date": day,
        "site_id": site,
        "kind": doc.get("kind") or work_type,
        "work_type": work_type,
        "label": body,
        "tag": tag,
        "phase": phase,
        "phase_label": phase_label,
        "chip_title": chip_title,
        "summary": summary,
        "color": color,
        "text_color": text_color,
        "seeded": bool(doc.get("seed_key")),
        "source_collection": source_collection,
        "record_id": record_id,
        "title": doc.get("title") or "",
        "notes": doc.get("notes") or doc.get("body") or "",
        "status": doc.get("status"),
        "all_day": True,
        "start_at": day,
        "end_at": doc.get("end_at") or "",
    }


def calendar_days_view(
    db, start: date, end: date, *, anchor: date | None = None
) -> dict[str, Any]:
    """Day-by-day work log for [start, end] with JP holidays."""
    holidays = holidays_between(start, end)
    by_day: dict[str, list[dict]] = {}

    for doc in db.collection(COL_OPS_EVENTS).stream():
        data = doc_to_dict(doc)
        item = doc_to_day_item(data, source_collection="ops_events")
        if not item:
            continue
        d = date.fromisoformat(item["date"])
        if start <= d <= end:
            by_day.setdefault(item["date"], []).append(item)

    for doc in db.collection(COL_TODOS).stream():
        data = doc_to_dict(doc)
        if not (data.get("site_id") or "").strip():
            continue
        enriched = {**data, "kind": "todo", "title": data.get("title") or "TODO"}
        item = doc_to_day_item(enriched, source_collection="todos")
        if not item:
            continue
        d = date.fromisoformat(item["date"])
        if start <= d <= end:
            by_day.setdefault(item["date"], []).append(item)

    today = date.today()
    days: list[dict] = []
    d = start
    while d <= end:
        key = d.isoformat()
        items = _merge_day_items(by_day.get(key, []))
        items = sorted(
            items,
            key=lambda x: (x["site_id"], x.get("work_type", x["kind"]), x["label"]),
        )
        days.append(
            {
                "date": key,
                "weekday": _WEEKDAY_KO[d.weekday()],
                "is_today": d == today,
                "is_weekend": d.weekday() >= 5,
                "holiday": holidays.get(key),
                "items": items,
            }
        )
        d += timedelta(days=1)

    anchor_d = anchor or today
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "anchor": anchor_d.isoformat(),
        "today": today.isoformat(),
        "window_days": CALENDAR_WINDOW_DAYS,
        "week_step": 7,
        "days": days,
    }


def default_calendar_range() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=CALENDAR_WINDOW_DAYS), today + timedelta(
        days=CALENDAR_WINDOW_DAYS
    )


def event_to_fullcalendar(doc: dict, *, source_collection: str = "ops_events") -> dict:
    if not calendar_item_visible(doc, source_collection=source_collection):
        return None  # type: ignore[return-value]
    site = (doc.get("site_id") or "").strip()
    if not site:
        return None  # type: ignore[return-value]

    work_type = _work_type(doc)
    body = _clean_event_title(doc)
    day = _doc_event_date(doc) or _parse_date_only(doc.get("start_at")) or ""
    phase = _execution_phase(doc, day) if day else "planned"
    color, text_color = _colors_for_doc(doc, phase=phase)
    phase_label = _PHASE_LABEL[phase]
    type_label = _WORK_TYPE_SHORT.get(work_type, work_type)
    tag = f"{phase_label}·{type_label}"
    chip_title = body if body and body != "(no title)" else site
    record_id = doc["id"]
    cal_id = f"evt-{record_id}" if source_collection == "ops_events" else f"todo-{record_id}"

    fc: dict[str, Any] = {
        "id": cal_id,
        "title": chip_title,
        "start": day or doc.get("start_at"),
        "allDay": True,
        "backgroundColor": color,
        "borderColor": color,
        "textColor": text_color,
        "classNames": [
            f"ev-work-{work_type}",
            f"ev-site-{site.replace('.', '_')}",
            f"ev-phase-{phase}",
        ],
        "extendedProps": {
            **doc,
            "cal_id": cal_id,
            "site_id": site,
            "work_type": work_type,
            "tag": tag,
            "chip_title": chip_title,
            "phase": phase,
            "phase_label": phase_label,
            "label": body,
            "color": color,
            "text_color": text_color,
            "date": day,
            "source_collection": source_collection,
            "record_id": record_id,
        },
    }
    if doc.get("seed_key"):
        fc["extendedProps"]["seeded"] = True
    return fc


def todo_to_fullcalendar(doc: dict) -> dict:
    start = doc.get("due_at") or ""
    all_day = True
    if start and "T" in str(start):
        all_day = False
    if not start:
        day = _parse_date_only(doc.get("created_at")) or date.today().isoformat()
        start = f"{day}T09:00:00"
        all_day = True

    title = doc.get("title") or "TODO"
    if doc.get("status") == "done":
        title = f"✓ {title}"

    enriched = {
        **doc,
        "kind": "todo",
        "start_at": start,
        "end_at": doc.get("end_at") or "",
        "all_day": all_day,
        "title": title,
    }
    fc = event_to_fullcalendar(enriched, source_collection="todos")
    if not fc:
        return None  # type: ignore[return-value]
    return fc


def all_calendar_events(db) -> list[dict]:
    events = []
    for doc in db.collection(COL_OPS_EVENTS).stream():
        data = doc_to_dict(doc)
        fc = event_to_fullcalendar(data, source_collection="ops_events")
        if fc:
            events.append(fc)
    return events


def delete_events_without_site(db) -> dict[str, int]:
    """Remove ops_events / todos with empty site_id."""
    removed_ops = removed_todos = 0
    for doc in db.collection(COL_OPS_EVENTS).stream():
        if not ((doc.to_dict() or {}).get("site_id") or "").strip():
            doc.reference.delete()
            removed_ops += 1
    for doc in db.collection(COL_TODOS).stream():
        if not ((doc.to_dict() or {}).get("site_id") or "").strip():
            doc.reference.delete()
            removed_todos += 1
    return {"ops_events": removed_ops, "todos": removed_todos}


def parse_calendar_id(cal_id: str) -> tuple[str, str]:
    if cal_id.startswith("todo-"):
        return "todos", cal_id[5:]
    if cal_id.startswith("evt-"):
        return "ops_events", cal_id[4:]
    return "ops_events", cal_id
