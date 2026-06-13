"""Dashboard due dates for recurring GSC / content work."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

GSC_INTERVAL_DAYS = 14
CONTENT_INTERVAL_DAYS = 7


def _parse_last_date(last_at: str | None) -> date | None:
    if not last_at:
        return None
    s = str(last_at).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:19]).date()
    except ValueError:
        return None


def work_due_schedule(
    last_at: str | None,
    *,
    interval_days: int,
    today: date | None = None,
) -> dict[str, Any]:
    """Next due date from last completion + fixed interval (calendar days)."""
    today = today or date.today()
    last_date = _parse_last_date(last_at)
    if last_date is None:
        next_due = today
        never_done = True
    else:
        next_due = last_date + timedelta(days=interval_days)
        never_done = False

    days_remaining = (next_due - today).days
    if never_done:
        status = "never"
    elif days_remaining < 0:
        status = "overdue"
    elif days_remaining == 0:
        status = "today"
    elif days_remaining <= 3:
        status = "soon"
    else:
        status = "ok"

    return {
        "interval_days": interval_days,
        "last_date": last_date.isoformat() if last_date else None,
        "next_due": next_due.isoformat(),
        "next_due_display": next_due.strftime("%Y-%m-%d"),
        "days_remaining": days_remaining,
        "status": status,
        "never_done": never_done,
    }


def format_due_label(schedule: dict[str, Any]) -> str:
    """Short Korean label for dashboard chips."""
    if schedule.get("never_done"):
        return "미실행 · 오늘까지"
    days = int(schedule.get("days_remaining", 0))
    due = schedule.get("next_due_display") or ""
    if days > 0:
        return f"D-{days} · {due}까지"
    if days == 0:
        return f"오늘까지 · {due}"
    overdue = abs(days)
    return f"{overdue}일 지남 · {due} 예정"
