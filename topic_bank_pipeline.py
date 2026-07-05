"""Topic bank ↔ pipeline integration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config import get_service, repo_path
from topic_bank import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    append_expand_to_bank,
    ensure_bootstrapped,
    load_state,
    read_bank,
    release_site,
    row_key,
    sync_queues,
    sync_state_from_repo,
    _state_key,
)
from content_done import is_content_row_done, row_backlog_missing_files
from pipeline_specs import POI_SITES
from topic_bank_registry import banks_for_site


def refresh_topic_state(site_id: str, repo: Path) -> dict[str, Any]:
    ensure_bootstrapped(site_id, repo)
    return sync_state_from_repo(
        site_id,
        repo,
        is_done=lambda spec, row: is_content_row_done(site_id, repo, spec, row),
    )


def _bank_row_count(site_id: str, bank_id: str) -> int:
    spec = next((s for s in banks_for_site(site_id) if s.bank_id == bank_id), None)
    if not spec:
        return 0
    return sum(1 for row in read_bank(site_id, bank_id) if row_key(spec, row))


def prepare_topics_for_generation(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    content_limit: int,
    guide_limit: int,
) -> dict[str, Any]:
    """One-shot prep before generation: expand pool → bank, refresh MD state."""
    from topic_bank import append_expand_to_bank

    ensure_bootstrapped(site_id, repo)
    appended = append_expand_to_bank(
        site_id,
        content_limit=content_limit,
        guide_limit=guide_limit,
    )
    for bank_id, n in (appended.get("by_bank") or {}).items():
        if n and logf:
            logf.write(f"토픽뱅크 {bank_id}: 시드 +{n}행\n")
    refresh_topic_state(site_id, repo)
    by_bank = appended.get("by_bank") or {}
    expanded_items = sum(
        by_bank.get(spec.bank_id, 0)
        for spec in banks_for_site(site_id)
        if spec.limit_kind == "content"
    )
    expanded_guides = sum(
        by_bank.get(spec.bank_id, 0)
        for spec in banks_for_site(site_id)
        if spec.limit_kind == "guide"
    )
    added = int(appended.get("added") or 0)
    return {
        "rows_added": added,
        "bank_rows_added": added,
        "bank_appended": by_bank,
        "expanded": added,
        "expanded_items": expanded_items,
        "expanded_guides": expanded_guides,
        "messages": [],
    }


def topic_bank_release_and_sync(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    content_limit: int,
    guide_limit: int,
) -> dict[str, Any]:
    """Manual CSV expand: append expand seeds (same as generation prep)."""
    return prepare_topics_for_generation(
        site_id,
        repo,
        logf,
        content_limit=content_limit,
        guide_limit=guide_limit,
    )


def topic_bank_release_queues(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    content_limit: int,
    guide_limit: int,
    content_limit_each: bool = False,
    school_limit: int | None = None,
    university_limit: int | None = None,
) -> dict[str, Any]:
    """Refresh MD state, release up to N pending rows per bank, sync queue CSVs."""
    ensure_bootstrapped(site_id, repo)
    refresh_topic_state(site_id, repo)
    rel = release_site(
        site_id,
        content_limit=content_limit,
        guide_limit=guide_limit,
        content_limit_each=content_limit_each,
        school_limit=school_limit,
        university_limit=university_limit,
    )
    by_bank = rel.get("by_bank") or {}
    if logf and rel.get("released"):
        parts = [f"{bid} +{n}" for bid, n in by_bank.items() if n]
        logf.write(f"큐 release: {', '.join(parts) or '0'}\n")
    active_banks: set[str] | None = None
    bank_limits: dict[str, int] | None = None
    if school_limit is not None or university_limit is not None:
        active_banks = set()
        bank_limits = {
            "guide_topics": guide_limit,
            "guides": guide_limit,
            "language_schools": school_limit if school_limit is not None else 0,
            "universities": university_limit if university_limit is not None else 0,
        }
        if guide_limit > 0:
            active_banks.add("guide_topics")
            active_banks.add("guides")
        if school_limit is not None and school_limit > 0:
            active_banks.add("language_schools")
        if university_limit is not None and university_limit > 0:
            active_banks.add("universities")
    sync = sync_queues(site_id, logf, active_banks=active_banks, bank_limits=bank_limits)
    synced = sync.get("synced") or {}
    out: dict[str, Any] = {
        "messages": list(sync.get("messages") or []),
        "synced": synced,
        "released": rel.get("released") or 0,
        "released_by_bank": by_bank,
        "expanded_items": 0,
        "expanded_guides": 0,
    }
    for spec in banks_for_site(site_id):
        n = int(synced.get(spec.bank_id) or 0)
        if spec.limit_kind == "guide":
            out["expanded_guides"] = max(out.get("expanded_guides", 0), n)
            if spec.bank_id in ("guides", "guide_topics"):
                out["guide_rows"] = n
        else:
            out["expanded_items"] = max(out.get("expanded_items", 0), n)
    return out


def topic_bank_sync_only(site_id: str, repo: Path, logf: Any) -> dict[str, Any]:
    ensure_bootstrapped(site_id, repo)
    refresh_topic_state(site_id, repo)
    sync = sync_queues(site_id, logf)
    synced = sync.get("synced") or {}
    out: dict[str, Any] = {
        "messages": sync.get("messages") or [],
        "synced": synced,
        "expanded_items": 0,
        "expanded_guides": 0,
    }
    for spec in banks_for_site(site_id):
        n = int(synced.get(spec.bank_id) or 0)
        if spec.limit_kind == "guide":
            out["expanded_guides"] = max(out.get("expanded_guides", 0), n)
            if spec.bank_id in ("guides", "guide_topics"):
                out["guide_rows"] = n
        else:
            out["expanded_items"] = max(out.get("expanded_items", 0), n)
            if spec.bank_id in ("insights", "items", "positions"):
                out["item_rows"] = n
    return out


def topic_bank_expand_preview(site_id: str, repo: Path, *, content_limit: int, guide_limit: int) -> dict[str, int]:
    ensure_bootstrapped(site_id, repo)
    from topic_bank import preview_expand

    return preview_expand(
        site_id,
        {"content": content_limit, "guide": guide_limit},
    )


def _released_row_count(site_id: str, bank_id: str) -> int:
    state = load_state(site_id)
    rows_state: dict[str, str] = state.get("rows") or {}
    spec = next((s for s in banks_for_site(site_id) if s.bank_id == bank_id), None)
    if not spec:
        return 0
    n = 0
    for row in read_bank(site_id, bank_id):
        key = row_key(spec, row)
        if not key:
            continue
        st = rows_state.get(_state_key(spec, key), "")
        if st in (STATUS_QUEUED, STATUS_DONE, STATUS_FAILED):
            n += 1
    return n


def topic_bank_backlog(site_id: str, repo: Path) -> dict[str, Any]:
    """Backlog from topic bank state + MD on disk (no site repo CSV)."""
    ensure_bootstrapped(site_id, repo)
    refresh_topic_state(site_id, repo)
    state = load_state(site_id)
    rows_state: dict[str, str] = state.get("rows") or {}

    def _missing_md_for_bank(bank_id: str) -> tuple[int, int]:
        spec = next(s for s in banks_for_site(site_id) if s.bank_id == bank_id)
        topics = 0
        files = 0
        for row in read_bank(site_id, bank_id):
            key = row_key(spec, row)
            if not key:
                continue
            miss = row_backlog_missing_files(site_id, repo, spec, row)
            if miss:
                topics += 1
                files += miss
        return topics, files

    content_dir = repo / "app" / "content"
    images_dir = repo / "app" / "static" / "images"

    if site_id in POI_SITES:
        ip, iff = _missing_md_for_bank("items")
        gp, gf = _missing_md_for_bank("guides")
        images = 0
        if content_dir.is_dir():
            for md in content_dir.glob("*_en.md"):
                if md.name.startswith("guide"):
                    continue
                stem = md.stem.replace("_en", "")
                img = images_dir / f"{stem}.jpg"
                if not img.is_file() or img.stat().st_size < 50_000:
                    images += 1
        return {
            "items_pairs": ip,
            "items_files": iff,
            "guides_topics": gp,
            "guides_files": gf,
            "images": images,
            "csv_items": _bank_row_count(site_id, "items"),
            "csv_guides": _bank_row_count(site_id, "guides"),
        }

    if site_id == "okstats":
        ip, iff = _missing_md_for_bank("insights")
        gp, gf = _missing_md_for_bank("guides")
        images = 0
        if content_dir.is_dir():
            for md in content_dir.glob("*_en.md"):
                stem = md.stem.replace("_en", "")
                img = images_dir / f"{stem}.jpg"
                if not img.is_file() or img.stat().st_size < 50_000:
                    images += 1
        return {
            "items_pairs": ip,
            "items_files": iff,
            "guides_topics": gp,
            "guides_files": gf,
            "images": images,
            "csv_items": _bank_row_count(site_id, "insights"),
            "csv_guides": _bank_row_count(site_id, "guides"),
        }

    if site_id == "starful.biz":
        out_dir = repo / "app/contents"
        img_dir = repo / "app/static/img"
        pending, _ = _missing_md_for_bank("positions")
        images = 0
        if out_dir.is_dir():
            for md in out_dir.glob("*.md"):
                if not (img_dir / f"{md.stem}.png").is_file():
                    images += 1
        return {
            "guides_md": pending,
            "images": images,
            "csv_items": _bank_row_count(site_id, "positions"),
        }

    if site_id == "jpcampus":
        guides_pending, _ = _missing_md_for_bank("guide_topics")
        korean_pending = 0
        gspec = next(s for s in banks_for_site(site_id) if s.bank_id == "guide_topics")
        for row in read_bank(site_id, "guide_topics"):
            key = row_key(gspec, row)
            if not key:
                continue
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            en = content_dir / f"guide_{slug}.md"
            kr = content_dir / f"guide_{slug}_kr.md"
            if en.is_file() and not kr.is_file():
                korean_pending += 1

        univs_pending, _ = _missing_md_for_bank("universities")

        return {
            "guides_topics": guides_pending,
            "korean_files": korean_pending,
            "univs_pending": univs_pending,
            "items_pairs": univs_pending,
            "csv_guides": _bank_row_count(site_id, "guide_topics"),
            "csv_univs": _bank_row_count(site_id, "universities"),
        }

    if site_id == "krcampus":
        guides_pending, _ = _missing_md_for_bank("guide_topics")
        ja_pending = 0
        gspec = next(s for s in banks_for_site(site_id) if s.bank_id == "guide_topics")
        for row in read_bank(site_id, "guide_topics"):
            key = row_key(gspec, row)
            if not key:
                continue
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            en = content_dir / f"guide_{slug}.md"
            ja = content_dir / f"guide_{slug}_ja.md"
            if en.is_file() and not ja.is_file():
                ja_pending += 1

        schools_pending, _ = _missing_md_for_bank("language_schools")
        univs_pending, _ = _missing_md_for_bank("universities")

        return {
            "guides_topics": guides_pending,
            "korean_files": ja_pending,
            "schools_pending": schools_pending,
            "univs_pending": univs_pending,
            "items_pairs": schools_pending + univs_pending,
            "csv_guides": _bank_row_count(site_id, "guide_topics"),
            "csv_schools": _bank_row_count(site_id, "language_schools"),
            "csv_univs": _bank_row_count(site_id, "universities"),
        }

    return {}
