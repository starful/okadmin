"""Unified calendar: ops_events + todos + auto_register seed."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from config import (
    AUTO_REGISTER_SCHEDULE,
    CALENDAR_WINDOW_DAYS,
    COL_OPS_EVENTS,
    COL_TODOS,
    EVENT_COLORS,
    EVENT_KINDS,
    LOG_DIR,
    SITE_COLORS,
)
from jp_holidays import holidays_between

# 칩 글자: 작업 종류 (색은 사이트별만)
_WORK_TYPE_SHORT = {
    "gsc": "GSC",
    "content": "컨텐츠",
    "feature": "기능",
    "git": "git",
    "auto_register": "컨텐츠",
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

# Python weekday: Mon=0 … Sun=6 (auto_register.sh: 1=Mon … 7=Sun)
AUTO_REGISTER_BY_WEEKDAY: dict[int, tuple[str, str]] = {
    0: ("okramen", "okramen"),
    1: ("okonsen", "okonsen"),
    2: ("okcaddie", "okcaddie"),
    3: ("oksushi", "oksushi"),
    4: ("starful.biz", "starful.biz"),
    5: ("jpcampus", "jpcampus"),
    6: ("hatena", "hatena"),
}

DEFAULT_SEED_START = date(2026, 4, 27)
AUTO_REGISTER_HOUR = 9


def _parse_date_only(val: Any) -> str | None:
    if not val:
        return None
    s = str(val)
    if "T" in s:
        return s.split("T", 1)[0]
    return s[:10] if len(s) >= 10 else None


def _log_run_status(log_path) -> str:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if "Auto register finished" in text:
        return "completed"
    if "Auto register started" in text and "ERROR" not in text[-500:]:
        return "started"
    if "Skip:" in text:
        return "skipped"
    return "unknown"


def collect_log_status_by_date() -> dict[str, str]:
    out: dict[str, str] = {}
    if not LOG_DIR.is_dir():
        return out
    for path in LOG_DIR.glob("auto-register-*.log"):
        m = re.match(r"auto-register-(\d{4}-\d{2}-\d{2})\.log$", path.name)
        if not m:
            continue
        out[m.group(1)] = _log_run_status(path)
    return out


def existing_seed_keys(db) -> set[str]:
    keys: set[str] = set()
    for doc in db.collection(COL_OPS_EVENTS).stream():
        data = doc.to_dict() or {}
        if data.get("seed_key"):
            keys.add(data["seed_key"])
    return keys


def seed_auto_register_range(
    db,
    start: date,
    end: date,
    *,
    overwrite: bool = False,
) -> dict[str, int]:
    """Insert auto_register ops_events for each day in range (dedupe by seed_key)."""
    from firebase_admin import firestore as fs

    log_status = collect_log_status_by_date()
    existing = existing_seed_keys(db)
    created = 0
    skipped = 0

    d = start
    while d <= end:
        iso_day = d.isoformat()
        seed_key = f"auto_register:{iso_day}"
        if seed_key in existing and not overwrite:
            skipped += 1
            d += timedelta(days=1)
            continue

        if overwrite and seed_key in existing:
            for doc in db.collection(COL_OPS_EVENTS).stream():
                data = doc.to_dict() or {}
                if data.get("seed_key") == seed_key:
                    doc.reference.delete()

        site_id, _label = AUTO_REGISTER_BY_WEEKDAY[d.weekday()]
        run = log_status.get(iso_day, "planned")
        title = f"Auto Register · {site_id}"
        notes_parts = [f"weekday={d.strftime('%a')}", f"run={run}"]
        if run == "completed":
            title += " ✓"
        elif run == "skipped":
            title += " (skip)"
            notes_parts.append("log=skip")

        start_at = f"{iso_day}T{AUTO_REGISTER_HOUR:02d}:00:00"
        end_at = f"{iso_day}T{AUTO_REGISTER_HOUR + 1:02d}:00:00"

        db.collection(COL_OPS_EVENTS).add(
            {
                "title": title,
                "site_id": site_id,
                "kind": "auto_register",
                "start_at": start_at,
                "end_at": end_at,
                "all_day": False,
                "notes": " · ".join(notes_parts),
                "seed_key": seed_key,
                "run_status": run,
                "created_at": fs.SERVER_TIMESTAMP,
            }
        )
        existing.add(seed_key)
        created += 1
        d += timedelta(days=1)

    return {"created": created, "skipped": skipped, "from": start.isoformat(), "to": end.isoformat()}


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
    if kind == "auto_register":
        return "auto_register"
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

    if work_type == "auto_register":
        if run == "completed" or "✓" in title:
            return "done"
        return "planned"

    if work_type in _LOGGED_WORK_TYPES:
        return "done"

    if work_type == "todo":
        return "done" if doc.get("status") == "done" else "planned"

    if ev_d > today:
        return "planned"
    return "done"


def doc_to_day_item(doc: dict, *, source_collection: str = "ops_events") -> dict | None:
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
    chip_title = f"{site} · {tag}"
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
        items = sorted(
            by_day.get(key, []),
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
    chip_title = f"{site} · {tag}"
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
    for doc in db.collection(COL_TODOS).stream():
        data = doc_to_dict(doc)
        if not (data.get("site_id") or "").strip():
            continue
        fc = todo_to_fullcalendar(data)
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
