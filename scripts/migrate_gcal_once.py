#!/usr/bin/env python3
"""One-off: Google Calendar work/git/GSC events → Firestore work_hub_ops_events."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

OKADMIN_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = Path("/opt/work")
TOKEN_PATH = Path(
    os.environ.get("GCAL_TOKEN_PATH", OKADMIN_ROOT / "scripts/secrets/gcal-token.json")
)
FIREBASE_CRED = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS", str(OKADMIN_ROOT / "secrets/firebase-key.json")
)
DAYS_BACK = int(os.environ.get("GCAL_IMPORT_DAYS", "400"))

sys.path.insert(0, str(OKADMIN_ROOT))
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", FIREBASE_CRED)

import yaml
import firebase_admin
from firebase_admin import credentials, firestore
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

COL = "work_hub_ops_events"
WORK_ICAL_SUFFIX = "@work.calendar.local"
GSC_HINTS = re.compile(
    r"gsc|search\s*console|검색\s*콘솔|클릭|노출|ctr|impressions?|clicks?",
    re.I,
)
BRACKET_SITE = re.compile(r"^\[([^\]]+)\]\s*(.*)$", re.S)


def load_site_ids() -> list[str]:
    p = WORK_ROOT / "sites.yaml"
    if p.is_file():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return [s["id"] for s in data.get("services", []) if s.get("id")]
    return []


def init_firestore():
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(FIREBASE_CRED))
    return firestore.client()


def calendar_service():
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def list_target_calendars(svc) -> list[tuple[str, str]]:
    """(calendar_id, summary). Token may only have calendar.events → primary only."""
    map_path = OKADMIN_ROOT / "scripts/secrets/gcal-calendars_map.json"
    if map_path.is_file():
        import json

        mapping = json.loads(map_path.read_text(encoding="utf-8"))
        return [(cid, f"Work · {sid}") for sid, cid in mapping.items() if cid]

    try:
        out: list[tuple[str, str]] = []
        page_token = None
        while True:
            res = svc.calendarList().list(pageToken=page_token).execute()
            for item in res.get("items", []):
                cid = item["id"]
                title = item.get("summary", "")
                if cid == "primary" or title.startswith("Work ·") or title.startswith("Work -"):
                    out.append((cid, title))
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        if out:
            seen: set[str] = set()
            unique = []
            for cid, title in out:
                if cid not in seen:
                    seen.add(cid)
                    unique.append((cid, title))
            return unique
    except Exception as e:
        print(f"calendarList unavailable ({e}); using primary only")

    return [("primary", "primary")]


def parse_event_times(ev: dict) -> tuple[str, str, bool]:
    start = ev.get("start", {})
    end = ev.get("end", {})
    if "dateTime" in start:
        return start["dateTime"], end.get("dateTime", ""), False
    if "date" in start:
        d = start["date"]
        return f"{d}T00:00:00", end.get("date", d) + "T23:59:59" if end.get("date") else "", True
    return "", "", False


def classify_event(ev: dict, site_ids: list[str]) -> tuple[str, str, str]:
    """kind, site_id, title (clean)."""
    summary = (ev.get("summary") or "").strip()
    desc = (ev.get("description") or "").strip()
    ical = ev.get("iCalUID") or ""

    site_id = ""
    title = summary

    if WORK_ICAL_SUFFIX in ical:
        prefix = ical.split(WORK_ICAL_SUFFIX)[0]
        if "-" in prefix:
            site_id = prefix.rsplit("-", 1)[0]
        else:
            site_id = prefix
        m = BRACKET_SITE.match(summary)
        title = m.group(2).strip() if m else summary
        if site_id in site_ids:
            return "git_push", site_id, title or "(commit)"

    m = BRACKET_SITE.match(summary)
    if m:
        cand = m.group(1).strip()
        if cand in site_ids:
            return "git_push", cand, m.group(2).strip() or "(commit)"

    combined = f"{summary}\n{desc}"
    if GSC_HINTS.search(combined):
        for sid in site_ids:
            if sid in combined or sid.replace(".", "") in combined.lower():
                site_id = sid
                break
        return "gsc", site_id, summary

    for sid in site_ids:
        if summary.lower().startswith(sid.lower()):
            site_id = sid
            break

    return "other", site_id, summary


def existing_gcal_keys(db) -> set[str]:
    keys = set()
    for doc in db.collection(COL).stream():
        data = doc.to_dict() or {}
        if data.get("seed_key", "").startswith("gcal:"):
            keys.add(data["seed_key"])
    return keys


def fetch_all_events(cal_svc, calendar_id: str, time_min: str, time_max: str) -> list[dict]:
    items = []
    page_token = None
    while True:
        res = (
            cal_svc.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )
        items.extend(res.get("items", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return items


def main():
    if not TOKEN_PATH.is_file():
        print(f"Missing token: {TOKEN_PATH}", file=sys.stderr)
        sys.exit(1)
    if not Path(FIREBASE_CRED).is_file():
        print(f"Missing firebase cred: {FIREBASE_CRED}", file=sys.stderr)
        sys.exit(1)

    site_ids = load_site_ids()
    db = init_firestore()
    cal_svc = calendar_service()
    existing = existing_gcal_keys(db)

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=DAYS_BACK)).isoformat().replace("+00:00", "Z")
    time_max = (now + timedelta(days=30)).isoformat().replace("+00:00", "Z")

    calendars = list_target_calendars(cal_svc)
    print(f"Calendars: {len(calendars)}")
    for cid, title in calendars:
        print(f"  · {title} ({cid})")

    created = skipped = ignored = 0
    for cal_id, cal_title in calendars:
        events = fetch_all_events(cal_svc, cal_id, time_min, time_max)
        print(f"\n{cal_title}: {len(events)} events")
        for ev in events:
            if ev.get("status") == "cancelled":
                ignored += 1
                continue
            gid = ev.get("id") or ""
            seed_key = f"gcal:{gid}"
            if not gid or seed_key in existing:
                skipped += 1
                continue

            start_at, end_at, all_day = parse_event_times(ev)
            if not start_at:
                ignored += 1
                continue

            kind, site_id, title = classify_event(ev, site_ids)
            desc = (ev.get("description") or "")[:2000]
            notes = f"imported from Google Calendar ({cal_title})\n{desc}".strip()

            db.collection(COL).add(
                {
                    "title": title[:500],
                    "site_id": site_id,
                    "kind": kind,
                    "start_at": start_at,
                    "end_at": end_at,
                    "all_day": all_day,
                    "notes": notes,
                    "seed_key": seed_key,
                    "gcal_id": gid,
                    "created_at": firestore.SERVER_TIMESTAMP,
                }
            )
            existing.add(seed_key)
            created += 1

    print(f"\nDone: created={created}, skipped={skipped}, ignored={ignored}")


if __name__ == "__main__":
    main()
