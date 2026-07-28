"""JP Campus stay catalog listing + selective publish (okadmin)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from config import get_service, repo_path


def _jpcampus_repo() -> Path:
    svc = get_service("jpcampus")
    if not svc:
        raise FileNotFoundError("jpcampus service not configured")
    root = repo_path(svc)
    if not root.exists():
        raise FileNotFoundError(f"jpcampus repo not found: {root}")
    return root


def _run_publish_cli(args: list[str], *, timeout: int = 600) -> dict[str, Any]:
    repo = _jpcampus_repo()
    cmd = [sys.executable, str(repo / "scripts" / "publish_stays.py"), *args]
    proc = subprocess.run(
        cmd,
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-2000:],
        "cmd": cmd,
    }


def catalog_summary() -> dict[str, Any]:
    """Load stay_listings + published status without importing jpcampus package."""
    repo = _jpcampus_repo()
    listings_path = repo / "data" / "stay_listings.json"
    content_dir = repo / "app" / "content"
    rows = json.loads(listings_path.read_text(encoding="utf-8"))

    published: set[str] = set()
    if content_dir.exists():
        for path in content_dir.glob("stay_*.md"):
            if path.name.endswith("_kr.md"):
                continue
            published.add(path.name[len("stay_") : -len(".md")])

    regions: dict[str, dict[str, int]] = {}
    for row in rows:
        reg = row.get("region") or "other"
        bucket = regions.setdefault(reg, {"total": 0, "published": 0, "unpublished": 0})
        bucket["total"] += 1
        if row["id"] in published:
            bucket["published"] += 1
        else:
            bucket["unpublished"] += 1

    return {
        "total": len(rows),
        "published": len(published),
        "unpublished": sum(1 for r in rows if r["id"] not in published),
        "regions": dict(sorted(regions.items(), key=lambda x: (-x[1]["total"], x[0]))),
    }


def list_catalog(
    *,
    region: str | None = None,
    unpublished_only: bool = True,
    limit: int = 100,
    q: str | None = None,
) -> dict[str, Any]:
    repo = _jpcampus_repo()
    listings_path = repo / "data" / "stay_listings.json"
    content_dir = repo / "app" / "content"
    rows = json.loads(listings_path.read_text(encoding="utf-8"))

    published: set[str] = set()
    if content_dir.exists():
        for path in content_dir.glob("stay_*.md"):
            if path.name.endswith("_kr.md"):
                continue
            published.add(path.name[len("stay_") : -len(".md")])

    items = []
    q_norm = (q or "").strip().lower()
    for row in rows:
        is_pub = row["id"] in published
        if unpublished_only and is_pub:
            continue
        if region and (row.get("region") or "other") != region:
            continue
        if q_norm:
            blob = " ".join(
                str(row.get(k) or "")
                for k in ("id", "name_en", "name_kr", "operator", "address_en", "address_kr")
            ).lower()
            if q_norm not in blob:
                continue
        items.append(
            {
                "id": row["id"],
                "operator": row.get("operator"),
                "region": row.get("region") or "other",
                "name_en": row.get("name_en"),
                "name_kr": row.get("name_kr"),
                "address_en": row.get("address_en"),
                "address_kr": row.get("address_kr"),
                "published": is_pub,
                "lat": row.get("lat"),
                "lng": row.get("lng"),
                "url_en": row.get("url_en"),
                "url_kr": row.get("url_kr"),
            }
        )
        if len(items) >= limit:
            break

    return {
        "items": items,
        "returned": len(items),
        "summary": catalog_summary(),
    }


def publish_ids(ids: list[str], *, build: bool = True, force: bool = False) -> dict[str, Any]:
    ids = [i.strip() for i in ids if i and str(i).strip()]
    if not ids:
        return {"ok": False, "error": "ids required"}
    if len(ids) > 50:
        return {"ok": False, "error": "max 50 ids per publish"}

    args = ["--ids", ",".join(ids)]
    if build:
        args.append("--build")
    if force:
        args.append("--force")
    result = _run_publish_cli(args)
    result["ids"] = ids
    result["summary"] = catalog_summary() if result.get("ok") else None
    return result


def publish_sample(*, per_region: int = 8, build: bool = True) -> dict[str, Any]:
    per_region = max(1, min(int(per_region), 15))
    args = ["--sample", "--per-region", str(per_region)]
    if build:
        args.append("--build")
    result = _run_publish_cli(args, timeout=900)
    result["per_region"] = per_region
    result["summary"] = catalog_summary() if result.get("ok") else None
    return result
