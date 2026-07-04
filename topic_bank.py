"""Central topic banks (okadmin CSV) with per-row state in topic_state/*.json."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from config import OKADMIN_ROOT
from topic_bank_registry import BankSpec, banks_for_site

BANKS_ROOT = OKADMIN_ROOT / "data" / "topic_banks"
STATE_ROOT = OKADMIN_ROOT / "data" / "topic_state"
QUEUES_ROOT = OKADMIN_ROOT / "data" / "pipeline_queues"

STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_RELEASED_STATUSES = frozenset({STATUS_QUEUED, STATUS_DONE, STATUS_FAILED})
_QUEUE_SYNC_STATUSES = frozenset({STATUS_QUEUED, STATUS_FAILED})


def _bank_path(site_id: str, bank_id: str) -> Path:
    return BANKS_ROOT / site_id / f"{bank_id}.csv"


def bank_csv_path(site_id: str, bank_id: str) -> Path:
    """Master topic bank CSV (okadmin)."""
    return _bank_path(site_id, bank_id)


def _state_path(site_id: str) -> Path:
    return STATE_ROOT / f"{site_id}.json"


def queue_path(site_id: str, bank_id: str) -> Path:
    return QUEUES_ROOT / site_id / f"{bank_id}.csv"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    rows: list[dict[str, str]] = []
    for raw in csv.DictReader(io.StringIO(text)):
        rows.append({k: (v if v is not None else "") for k, v in raw.items()})
    return rows


def _write_csv_rows(path: Path, headers: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(headers), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({h: (row.get(h) or "") for h in headers})
    path.write_text(buf.getvalue(), encoding="utf-8-sig")


def row_key(spec: BankSpec, row: dict[str, str]) -> str | None:
    if spec.key_kind == "coord":
        lat = (row.get("Lat") or row.get("lat") or "").strip()
        lng = (row.get("Lng") or row.get("lng") or "").strip()
        if lat and lng:
            try:
                return f"{float(lat):.4f},{float(lng):.4f}"
            except ValueError:
                pass
        val = (row.get(spec.key_col) or "").strip()
        return val.lower() if val else None
    val = (row.get(spec.key_col) or "").strip()
    if not val or val.startswith("#"):
        return None
    return val.lower()


def _state_key(spec: BankSpec, key: str) -> str:
    return f"{spec.bank_id}:{key}"


def load_state(site_id: str) -> dict[str, Any]:
    path = _state_path(site_id)
    if not path.is_file():
        return {"version": 1, "rows": {}, "updated_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "rows": {}, "updated_at": None}
    if not isinstance(data.get("rows"), dict):
        data["rows"] = {}
    data.setdefault("version", 1)
    return data


def save_state(site_id: str, data: dict[str, Any]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["version"] = 1
    data["updated_at"] = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    _state_path(site_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_bank(site_id: str, bank_id: str) -> list[dict[str, str]]:
    return _read_csv_rows(_bank_path(site_id, bank_id))


def write_bank(site_id: str, spec: BankSpec, rows: list[dict[str, str]]) -> None:
    _write_csv_rows(_bank_path(site_id, spec.bank_id), spec.headers, rows)


def _merge_rows(
    existing: list[dict[str, str]],
    new_rows: list[dict[str, str]],
    spec: BankSpec,
) -> list[dict[str, str]]:
    by_key: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for row in existing + new_rows:
        key = row_key(spec, row)
        if not key:
            continue
        if key not in by_key:
            order.append(key)
        by_key[key] = {h: (row.get(h) or by_key.get(key, {}).get(h) or "") for h in spec.headers}
    return [by_key[k] for k in order]


def _append_bank_rows(site_id: str, spec: BankSpec, new_rows: list[dict[str, str]]) -> int:
    if not new_rows:
        return 0
    path = _bank_path(site_id, spec.bank_id)
    before = {row_key(spec, r) for r in _read_csv_rows(path) if row_key(spec, r)}
    merged = _merge_rows(_read_csv_rows(path), new_rows, spec)
    after = {row_key(spec, r) for r in merged if row_key(spec, r)}
    write_bank(site_id, spec, merged)
    return len(after - before)


def _bank_keys(site_id: str, spec: BankSpec) -> set[str]:
    return {k for r in read_bank(site_id, spec.bank_id) if (k := row_key(spec, r))}


def _append_bank_rows_limited(
    site_id: str,
    spec: BankSpec,
    new_rows: list[dict[str, str]],
    *,
    max_add: int,
) -> int:
    if max_add <= 0 or not new_rows:
        return 0
    keys = _bank_keys(site_id, spec)
    to_add: list[dict[str, str]] = []
    for row in new_rows:
        if len(to_add) >= max_add:
            break
        key = row_key(spec, row)
        if not key or key in keys:
            continue
        to_add.append({h: (row.get(h) or "") for h in spec.headers})
        keys.add(key)
    return _append_bank_rows(site_id, spec, to_add)


def append_expand_to_bank(
    site_id: str,
    *,
    content_limit: int,
    guide_limit: int,
) -> dict[str, Any]:
    """Append expand-pool rows to topic banks (new rows start as pending)."""
    from topic_bank_seeds import expand_pool_for_site

    pool = expand_pool_for_site(site_id)
    added_by_bank: dict[str, int] = {}
    content_left = content_limit
    guide_left = guide_limit
    for spec in banks_for_site(site_id):
        rows = pool.get(spec.bank_id) or []
        if not rows:
            continue
        if spec.limit_kind == "guide":
            cap = guide_left
        else:
            cap = content_left
        n = _append_bank_rows_limited(site_id, spec, rows, max_add=cap)
        added_by_bank[spec.bank_id] = n
        if spec.limit_kind == "guide":
            guide_left -= n
        else:
            content_left -= n
    total = sum(added_by_bank.values())
    return {"added": total, "by_bank": added_by_bank}


def _pool_expandable_count(site_id: str, bank_id: str, pool_rows: list[dict[str, str]]) -> int:
    spec = next((s for s in banks_for_site(site_id) if s.bank_id == bank_id), None)
    if not spec or not pool_rows:
        return 0
    keys = _bank_keys(site_id, spec)
    n = 0
    for row in pool_rows:
        if not isinstance(row, dict):
            continue
        key = row_key(spec, row)
        if key and key not in keys:
            n += 1
    return n


def count_expandable(site_id: str, limits: dict[str, int]) -> dict[str, int]:
    """How many rows CSV 추가 could append+release per bank (capped by limits)."""
    from topic_bank_seeds import expand_pool_for_site

    pending = count_pending(site_id)
    pool = expand_pool_for_site(site_id)
    out: dict[str, int] = {}
    content_cap = limits.get("content", 0)
    guide_cap = limits.get("guide", 0)
    content_used = 0
    guide_used = 0
    for spec in banks_for_site(site_id):
        p = pending.get(spec.bank_id, 0)
        pool_n = _pool_expandable_count(site_id, spec.bank_id, pool.get(spec.bank_id) or [])
        total = p + pool_n
        if spec.limit_kind == "guide":
            avail = min(total, max(0, guide_cap - guide_used))
            guide_used += avail
        else:
            avail = min(total, max(0, content_cap - content_used))
            content_used += avail
        out[spec.bank_id] = avail
    return out


def count_pending(site_id: str, bank_id: str | None = None) -> dict[str, int]:
    state = load_state(site_id)
    rows_state: dict[str, str] = state.get("rows") or {}
    out: dict[str, int] = {}
    for spec in banks_for_site(site_id):
        if bank_id and spec.bank_id != bank_id:
            continue
        pending = 0
        for row in read_bank(site_id, spec.bank_id):
            key = row_key(spec, row)
            if not key:
                continue
            sk = _state_key(spec, key)
            if rows_state.get(sk, STATUS_PENDING) == STATUS_PENDING:
                pending += 1
        out[spec.bank_id] = pending
    return out


def preview_expand(site_id: str, limits: dict[str, int]) -> dict[str, int]:
    """Totals for backlog UI (items_expandable / guides_expandable)."""
    by_bank = count_expandable(site_id, limits)
    items = 0
    guides = 0
    for spec in banks_for_site(site_id):
        n = by_bank.get(spec.bank_id, 0)
        if spec.limit_kind == "guide":
            guides += n
        else:
            items += n
    return {"items_expandable": items, "guides_expandable": guides}


def release_rows(
    site_id: str,
    spec: BankSpec,
    *,
    limit: int,
    state: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if limit <= 0:
        return [], state or load_state(site_id)
    state = dict(state or load_state(site_id))
    rows_state: dict[str, str] = dict(state.get("rows") or {})
    released: list[dict[str, str]] = []
    for row in read_bank(site_id, spec.bank_id):
        if len(released) >= limit:
            break
        key = row_key(spec, row)
        if not key:
            continue
        sk = _state_key(spec, key)
        if rows_state.get(sk, STATUS_PENDING) != STATUS_PENDING:
            continue
        rows_state[sk] = STATUS_QUEUED
        released.append(row)
    state["rows"] = rows_state
    return released, state


def release_site(
    site_id: str,
    *,
    content_limit: int,
    guide_limit: int,
    content_limit_each: bool = False,
    school_limit: int | None = None,
    university_limit: int | None = None,
) -> dict[str, Any]:
    """Move pending bank rows to queued (cap per guide bank; content banks share or per-bank)."""
    state = load_state(site_id)
    released_by_bank: dict[str, int] = {}
    content_left = content_limit
    guide_left = guide_limit
    school_left = school_limit if school_limit is not None else content_left
    university_left = university_limit if university_limit is not None else content_left
    for spec in banks_for_site(site_id):
        if spec.limit_kind == "guide":
            cap = guide_left
        elif spec.bank_id == "language_schools" and school_limit is not None:
            cap = school_left
        elif spec.bank_id == "universities" and university_limit is not None:
            cap = university_left
        elif content_limit_each:
            cap = content_limit
        else:
            cap = content_left
        rows, state = release_rows(site_id, spec, limit=cap, state=state)
        released_by_bank[spec.bank_id] = len(rows)
        if spec.limit_kind == "guide":
            guide_left -= len(rows)
        elif spec.bank_id == "language_schools" and school_limit is not None:
            school_left -= len(rows)
        elif spec.bank_id == "universities" and university_limit is not None:
            university_left -= len(rows)
        elif not content_limit_each:
            content_left -= len(rows)
    save_state(site_id, state)
    total = sum(released_by_bank.values())
    return {"released": total, "by_bank": released_by_bank, "state": state}


def _rows_for_queue(site_id: str, spec: BankSpec, state: dict[str, Any]) -> list[dict[str, str]]:
    """Rows that still need generation (queued or failed)."""
    rows_state: dict[str, str] = state.get("rows") or {}
    out: list[dict[str, str]] = []
    for row in read_bank(site_id, spec.bank_id):
        key = row_key(spec, row)
        if not key:
            continue
        sk = _state_key(spec, key)
        if rows_state.get(sk, STATUS_PENDING) in _QUEUE_SYNC_STATUSES:
            out.append({h: (row.get(h) or "") for h in spec.headers})
    return out


def sync_queues(
    site_id: str,
    logf: Any | None = None,
    *,
    active_banks: set[str] | None = None,
    bank_limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Write queued/failed rows to okadmin pipeline queue CSVs (no site repo)."""
    state = load_state(site_id)
    out: dict[str, Any] = {"synced": {}, "messages": []}
    for spec in banks_for_site(site_id):
        if active_banks is not None and spec.bank_id not in active_banks:
            rows: list[dict[str, str]] = []
        else:
            rows = _rows_for_queue(site_id, spec, state)
            cap = (bank_limits or {}).get(spec.bank_id)
            if cap is not None:
                rows = rows[: max(0, cap)]
        dest = queue_path(site_id, spec.bank_id)
        _write_csv_rows(dest, spec.headers, rows)
        out["synced"][spec.bank_id] = len(rows)
        rel = dest.relative_to(OKADMIN_ROOT)
        msg = f"{rel}: 큐 {len(rows)}행"
        out["messages"].append(msg)
        if logf:
            logf.write(msg + "\n")
    return out


def sync_to_repo(site_id: str, repo: Path, logf: Any | None = None) -> dict[str, Any]:
    """Deprecated mirror — pipeline uses sync_queues only."""
    return sync_queues(site_id, logf)


def sync_state_from_repo(
    site_id: str,
    repo: Path,
    *,
    is_done: Callable[[BankSpec, dict[str, str]], bool] | None = None,
) -> dict[str, Any]:
    """Refresh row status from MD on disk (topic bank is source of truth)."""
    state = load_state(site_id)
    rows_state: dict[str, str] = dict(state.get("rows") or {})
    updated = 0
    for spec in banks_for_site(site_id):
        site_path = repo / spec.site_rel
        legacy_keys: set[str] = set()
        if site_path.is_file():
            for row in _read_csv_rows(site_path):
                key = row_key(spec, row)
                if key:
                    legacy_keys.add(key)

        for row in read_bank(site_id, spec.bank_id):
            key = row_key(spec, row)
            if not key:
                continue
            sk = _state_key(spec, key)
            cur = rows_state.get(sk)
            if is_done and is_done(spec, row):
                if cur != STATUS_DONE:
                    rows_state[sk] = STATUS_DONE
                    updated += 1
            elif cur == STATUS_DONE:
                continue
            elif cur in (STATUS_QUEUED, STATUS_FAILED):
                continue
            elif key in legacy_keys:
                if cur != STATUS_QUEUED:
                    rows_state[sk] = STATUS_QUEUED
                    updated += 1
            elif cur is None:
                rows_state[sk] = STATUS_PENDING
                updated += 1
    state["rows"] = rows_state
    save_state(site_id, state)
    return {"updated": updated}


def bank_stats(site_id: str) -> dict[str, Any]:
    state = load_state(site_id)
    rows_state: dict[str, str] = state.get("rows") or {}
    banks: dict[str, Any] = {}
    for spec in banks_for_site(site_id):
        counts = {STATUS_PENDING: 0, STATUS_QUEUED: 0, STATUS_DONE: 0, STATUS_FAILED: 0}
        total = 0
        for row in read_bank(site_id, spec.bank_id):
            key = row_key(spec, row)
            if not key:
                continue
            total += 1
            st = rows_state.get(_state_key(spec, key), STATUS_PENDING)
            counts[st] = counts.get(st, 0) + 1
        banks[spec.bank_id] = {"total": total, **counts}
    return {"site_id": site_id, "banks": banks, "updated_at": state.get("updated_at")}


def bootstrap_site(site_id: str, repo: Path | None, seed_rows: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    """Ensure bank CSVs exist; merge seeds + repo rows; initialize state."""
    added: dict[str, int] = {}
    for spec in banks_for_site(site_id):
        seeds = seed_rows.get(spec.bank_id) or []
        repo_rows: list[dict[str, str]] = []
        if repo is not None:
            site_path = repo / spec.site_rel
            if site_path.is_file():
                repo_rows = _read_csv_rows(site_path)
        n = _append_bank_rows(site_id, spec, seeds + repo_rows)
        added[spec.bank_id] = n

    if repo is not None:
        sync_state_from_repo(site_id, repo)
    else:
        state = load_state(site_id)
        rows_state: dict[str, str] = dict(state.get("rows") or {})
        for spec in banks_for_site(site_id):
            for row in read_bank(site_id, spec.bank_id):
                key = row_key(spec, row)
                if not key:
                    continue
                sk = _state_key(spec, key)
                rows_state.setdefault(sk, STATUS_PENDING)
        state["rows"] = rows_state
        save_state(site_id, state)

    return {"site_id": site_id, "bank_rows_added": added}


def ensure_bootstrapped(site_id: str, repo: Path | None) -> None:
    from topic_bank_seeds import bootstrap_seeds_for_site

    specs = banks_for_site(site_id)
    if not specs:
        return
    missing = any(not _bank_path(site_id, s.bank_id).is_file() for s in specs)
    state_missing = not _state_path(site_id).is_file()
    if missing or state_missing:
        bootstrap_site(site_id, repo, bootstrap_seeds_for_site(site_id))
