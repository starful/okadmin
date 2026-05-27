"""Firestore ops calendar entries for hub actions."""
from __future__ import annotations

from datetime import date
from typing import Any

from config import COL_OPS_EVENTS
from firestore_db import doc_to_dict, get_db


def record_ops_calendar_event(
    *,
    site_id: str,
    kind: str,
    title: str,
    notes: str = "",
) -> dict[str, Any] | None:
    """Add an all-day event for today. Returns event dict or None if Firestore unavailable."""
    db = get_db()
    if db is None:
        return None
    from firebase_admin import firestore as fs

    payload = {
        "title": title.strip(),
        "site_id": site_id,
        "kind": kind,
        "start_at": date.today().isoformat(),
        "end_at": "",
        "all_day": True,
        "notes": notes or "",
        "created_at": fs.SERVER_TIMESTAMP,
    }
    ref = db.collection(COL_OPS_EVENTS).add(payload)[1]
    return doc_to_dict(ref.get())
