"""Read/write site content CSV files under WORK_ROOT (okcafejp, hatena, …)."""
from __future__ import annotations

import csv
import io
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from config import CONTENT_CSV_FILES, get_service, repo_path, work_root_available

MAX_CSV_ROWS = 2000


def list_csv_files() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for site_id, files in CONTENT_CSV_FILES.items():
        svc = get_service(site_id)
        for spec in files:
            path = resolve_csv_path(site_id, spec["id"])
            exists = path.is_file() if path else False
            row_count = 0
            if exists and path:
                try:
                    row_count = len(read_csv_rows(path))
                except OSError:
                    row_count = 0
            out.append(
                {
                    "site_id": site_id,
                    "site_label": (svc or {}).get("label", site_id),
                    "file_id": spec["id"],
                    "label": spec.get("label", spec["id"]),
                    "rel_path": spec["rel_path"],
                    "exists": exists,
                    "row_count": row_count,
                    "available": bool(svc) and work_root_available(),
                }
            )
    return out


def get_csv_spec(site_id: str, file_id: str) -> dict[str, Any] | None:
    for spec in CONTENT_CSV_FILES.get(site_id) or []:
        if spec["id"] == file_id:
            return spec
    return None


def resolve_csv_path(site_id: str, file_id: str) -> Path | None:
    spec = get_csv_spec(site_id, file_id)
    svc = get_service(site_id)
    if not spec or not svc or not work_root_available():
        return None
    root = repo_path(svc)
    rel = spec["rel_path"].strip().lstrip("/")
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    rows: list[dict[str, str]] = []
    for row in reader:
        rows.append({k: (v if v is not None else "") for k, v in row.items()})
    return rows


def load_csv(site_id: str, file_id: str) -> dict[str, Any]:
    spec = get_csv_spec(site_id, file_id)
    if not spec:
        return {"error": "unknown csv file"}
    path = resolve_csv_path(site_id, file_id)
    if path is None:
        return {"error": "WORK_ROOT unavailable or invalid path"}

    headers: list[str] = list(spec.get("headers") or [])
    rows: list[dict[str, str]] = []
    exists = path.is_file()
    if exists:
        try:
            rows = read_csv_rows(path)
            if rows:
                headers = list(rows[0].keys())
            elif path.read_text(encoding="utf-8-sig").strip():
                with path.open(encoding="utf-8-sig") as f:
                    reader = csv.reader(f)
                    first = next(reader, None)
                    if first:
                        headers = first
        except OSError as e:
            return {"error": str(e)}

    if not headers:
        headers = list(spec.get("headers") or [])

    return {
        "site_id": site_id,
        "file_id": file_id,
        "label": spec.get("label", file_id),
        "rel_path": spec["rel_path"],
        "path": str(path),
        "exists": exists,
        "headers": headers,
        "rows": rows[:MAX_CSV_ROWS],
        "row_count": len(rows),
        "truncated": len(rows) > MAX_CSV_ROWS,
    }


def save_csv(
    site_id: str,
    file_id: str,
    rows: list[dict[str, Any]],
    *,
    headers: list[str] | None = None,
) -> dict[str, Any]:
    spec = get_csv_spec(site_id, file_id)
    if not spec:
        return {"error": "unknown csv file"}
    path = resolve_csv_path(site_id, file_id)
    if path is None:
        return {"error": "WORK_ROOT unavailable or invalid path"}

    hdrs = headers or list(spec.get("headers") or [])
    if not hdrs and rows:
        hdrs = list(rows[0].keys())
    if not hdrs:
        return {"error": "headers required"}

    if len(rows) > MAX_CSV_ROWS:
        return {"error": f"max {MAX_CSV_ROWS} rows"}

    normalized: list[dict[str, str]] = []
    for row in rows:
        normalized.append({h: str((row.get(h) if isinstance(row, dict) else "") or "") for h in hdrs})

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        bak = path.with_suffix(path.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        try:
            shutil.copy2(path, bak)
        except OSError:
            pass

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=hdrs, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(normalized)
    path.write_text(buf.getvalue(), encoding="utf-8-sig")

    return {
        "ok": True,
        "path": str(path),
        "row_count": len(normalized),
        "headers": hdrs,
    }
