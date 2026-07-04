"""Topic bank ↔ pipeline integration."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

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
from topic_bank_registry import BankSpec, banks_for_site

_ITEM_SLUG_RE = re.compile(r"[^a-z0-9_]")


def _item_slug(name: str) -> str:
    return _ITEM_SLUG_RE.sub("", name.lower().replace(" ", "_").replace("'", ""))


def _read_univ_md_names(md_path: Path) -> tuple[str, str, str]:
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return "", "", ""
    if not text.startswith("---"):
        return "", "", ""
    end = text.find("---", 3)
    if end < 0:
        return "", "", ""
    raw = text[3:end].strip()
    basic: dict[str, Any] = {}
    try:
        if raw.startswith("{"):
            data = json.loads(raw)
            basic = data.get("basic_info") or {}
        else:
            data = yaml.safe_load(raw) or {}
            if isinstance(data, dict):
                bi = data.get("basic_info")
                basic = bi if isinstance(bi, dict) else {}
    except (json.JSONDecodeError, yaml.YAMLError):
        return "", "", ""
    ja = (basic.get("name_ja") or "").strip()
    ko = (basic.get("name_ko") or "").strip()
    en = (basic.get("name_en") or "").strip().lower()
    return ja, ko, en


@lru_cache(maxsize=8)
def _univ_name_index(content_dir_str: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    content_dir = Path(content_dir_str)
    ja: set[str] = set()
    ko: set[str] = set()
    en: set[str] = set()
    if not content_dir.is_dir():
        return frozenset(), frozenset(), frozenset()
    for md in content_dir.glob("univ_*.md"):
        if md.stem.endswith(("_kr", "_ja")):
            continue
        mja, mko, men = _read_univ_md_names(md)
        if mja:
            ja.add(mja)
        if mko:
            ko.add(mko)
        if men:
            en.add(men)
    return frozenset(ja), frozenset(ko), frozenset(en)


def _univ_row_done(repo: Path, row: dict[str, str]) -> bool:
    content_dir = repo / "app" / "content"
    name_ja = (row.get("name_ja") or "").strip()
    name_ko = (row.get("name_ko") or "").strip()
    name_en = (row.get("name_en") or "").strip().lower()
    if not name_ja and not name_ko and not name_en:
        return False
    ja_set, ko_set, en_set = _univ_name_index(str(content_dir))
    if name_ja and name_ja in ja_set:
        return True
    if name_ko and name_ko in ko_set:
        return True
    if name_en and name_en in en_set:
        return True
    if name_ko:
        slug = _item_slug(name_ko)
        if (content_dir / f"univ_{slug}.md").is_file():
            return True
    return False


def _is_row_done(site_id: str, repo: Path, spec: BankSpec, row: dict[str, str]) -> bool:
    content_dir = repo / "app" / "content"
    guides_dir = content_dir / "guides"

    if spec.bank_id == "insights":
        iid = (row.get("id") or "").strip()
        if not iid or iid.startswith("#"):
            return False
        return (content_dir / f"{iid}_en.md").is_file()

    if spec.bank_id == "guides":
        gid = (row.get("id") or "").strip()
        if not gid:
            return False
        return any((guides_dir / f"{gid}{suf}.md").is_file() for suf in ("", "_en"))

    if spec.bank_id == "guide_topics":
        slug = (row.get("slug") or "").strip()
        if not slug:
            return False
        for base in (repo / "app" / "content", repo / "data" / "guides", content_dir):
            if (base / f"guide_{slug}.md").is_file():
                return True
        return False

    if spec.bank_id == "language_schools":
        ko = (row.get("name_ko") or "").strip()
        if not ko:
            return False
        slug = _item_slug(ko)
        return (content_dir / f"school_{slug}.md").is_file() or any(
            content_dir.glob(f"school_*{slug}*.md")
        )

    if spec.bank_id == "universities":
        return _univ_row_done(repo, row)

    if spec.bank_id in ("items",) or spec.key_kind == "coord":
        name = (row.get("Name") or row.get("name") or "").strip()
        if not name:
            return False
        slug = _item_slug(name)
        en = content_dir / f"{slug}_en.md"
        ko = content_dir / f"{slug}_ko.md"
        return en.is_file() and ko.is_file()

    if spec.bank_id == "positions":
        from starful_assets import position_slug

        name = (row.get("position_name") or "").strip()
        if not name:
            return False
        slug = position_slug(name)
        guides = repo / "app" / "content" / "guides"
        return (guides / f"{slug}.md").is_file() if guides.is_dir() else False

    if spec.bank_id == "python":
        lib = (row.get("lib_name") or "").strip().lower()
        posts = repo / "posts"
        return any(posts.glob(f"*{lib}*.md")) if lib and posts.is_dir() else False

    if spec.bank_id == "cloud":
        return False

    return False


def refresh_topic_state(site_id: str, repo: Path) -> dict[str, Any]:
    ensure_bootstrapped(site_id, repo)
    return sync_state_from_repo(
        site_id,
        repo,
        is_done=lambda spec, row: _is_row_done(site_id, repo, spec, row),
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

    def _missing_md_for_bank(bank_id: str, *, need_md: Any) -> tuple[int, int]:
        spec = next(s for s in banks_for_site(site_id) if s.bank_id == bank_id)
        topics = 0
        files = 0
        for row in read_bank(site_id, bank_id):
            key = row_key(spec, row)
            if not key:
                continue
            miss = int(need_md(spec, row))
            if miss:
                topics += 1
                files += miss
        return topics, files

    content_dir = repo / "app" / "content"
    guides_dir = content_dir / "guides"
    images_dir = repo / "app" / "static" / "images"

    if site_id in ("okramen", "okonsen", "okcaddie"):

        def item_miss(spec: BankSpec, row: dict[str, str]) -> bool:
            name = (row.get("Name") or "").strip()
            if not name:
                return False
            slug = _item_slug(name)
            en = content_dir / f"{slug}_en.md"
            ko = content_dir / f"{slug}_ko.md"
            return int(not en.is_file()) + int(not ko.is_file())

        def guide_miss(spec: BankSpec, row: dict[str, str]) -> bool:
            gid = (row.get("id") or "").strip()
            if not gid:
                return False
            en = guides_dir / f"{gid}_en.md"
            ko = guides_dir / f"{gid}_ko.md"
            return int(not en.is_file()) + int(not ko.is_file())

        ip, iff = _missing_md_for_bank("items", need_md=item_miss)
        gp, gf = _missing_md_for_bank("guides", need_md=guide_miss)
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

        def insight_miss(spec: BankSpec, row: dict[str, str]) -> bool:
            iid = (row.get("id") or "").strip()
            if not iid or iid.startswith("#"):
                return False
            return not (content_dir / f"{iid}_en.md").is_file()

        def guide_miss(spec: BankSpec, row: dict[str, str]) -> bool:
            gid = (row.get("id") or "").strip()
            if not gid:
                return False
            return not any((guides_dir / f"{gid}{suf}.md").is_file() for suf in ("", "_en"))

        ip, iff = _missing_md_for_bank("insights", need_md=insight_miss)
        gp, gf = _missing_md_for_bank("guides", need_md=guide_miss)
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
        from starful_assets import position_slug

        out_dir = repo / "app/contents"
        img_dir = repo / "app/static/img"
        pending = 0
        spec = next(s for s in banks_for_site(site_id) if s.bank_id == "positions")
        for row in read_bank(site_id, "positions"):
            key = row_key(spec, row)
            if not key:
                continue
            pos = (row.get("position_name") or "").strip()
            if not pos:
                continue
            slug = position_slug(pos)
            if not (out_dir / f"{slug}.md").is_file():
                pending += 1
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
        guides_pending = 0
        korean_pending = 0
        spec = next(s for s in banks_for_site(site_id) if s.bank_id == "guide_topics")
        for row in read_bank(site_id, "guide_topics"):
            key = row_key(spec, row)
            if not key:
                continue
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            en = content_dir / f"guide_{slug}.md"
            if not en.is_file():
                guides_pending += 1
            kr = content_dir / f"guide_{slug}_kr.md"
            if en.is_file() and not kr.is_file():
                korean_pending += 1

        univ_ja, _, univ_en = _univ_name_index(str(content_dir))

        univs_pending = 0
        uspec = next(s for s in banks_for_site(site_id) if s.bank_id == "universities")
        for row in read_bank(site_id, "universities"):
            key = row_key(uspec, row)
            if not key:
                continue
            name_ja = (row.get("name_ja") or "").strip()
            name_en = (row.get("name_en") or "").strip()
            if not name_ja and not name_en:
                continue
            if name_ja in univ_ja:
                continue
            if name_en and name_en.lower() in univ_en:
                continue
            univs_pending += 1

        return {
            "guides_topics": guides_pending,
            "korean_files": korean_pending,
            "univs_pending": univs_pending,
            "items_pairs": univs_pending,
            "csv_guides": _bank_row_count(site_id, "guide_topics"),
            "csv_univs": _bank_row_count(site_id, "universities"),
        }

    if site_id == "krcampus":

        def _read_basic_names(md_path: Path) -> tuple[str, str]:
            try:
                text = md_path.read_text(encoding="utf-8")
            except OSError:
                return "", ""
            if not text.startswith("---"):
                return "", ""
            end = text.find("---", 3)
            if end < 0:
                return "", ""
            try:
                data = json.loads(text[3:end].strip())
            except json.JSONDecodeError:
                return "", ""
            basic = data.get("basic_info") or {}
            return (basic.get("name_ko") or "").strip(), (basic.get("name_en") or "").strip()

        def _name_index(prefix: str) -> tuple[set[str], set[str]]:
            ko: set[str] = set()
            en: set[str] = set()
            if not content_dir.is_dir():
                return ko, en
            for md in content_dir.glob(f"{prefix}_*.md"):
                if md.stem.endswith("_ja"):
                    continue
                name_ko, name_en = _read_basic_names(md)
                if name_ko:
                    ko.add(name_ko)
                if name_en:
                    en.add(name_en.lower())
            return ko, en

        guides_pending = 0
        ja_pending = 0
        spec = next(s for s in banks_for_site(site_id) if s.bank_id == "guide_topics")
        for row in read_bank(site_id, "guide_topics"):
            key = row_key(spec, row)
            if not key:
                continue
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            en = content_dir / f"guide_{slug}.md"
            if not en.is_file():
                guides_pending += 1
            ja = content_dir / f"guide_{slug}_ja.md"
            if en.is_file() and not ja.is_file():
                ja_pending += 1

        school_ko, school_en = _name_index("school")
        univ_ko, univ_en = _name_index("univ")

        def _bank_pending(bank_id: str, known_ko: set[str], known_en: set[str]) -> int:
            bspec = next(s for s in banks_for_site(site_id) if s.bank_id == bank_id)
            n = 0
            for row in read_bank(site_id, bank_id):
                key = row_key(bspec, row)
                if not key:
                    continue
                name_ko = (row.get("name_ko") or "").strip()
                name_en = (row.get("name_en") or "").strip()
                if not name_ko and not name_en:
                    continue
                if name_ko in known_ko:
                    continue
                if name_en and name_en.lower() in known_en:
                    continue
                n += 1
            return n

        schools_pending = _bank_pending("language_schools", school_ko, school_en)
        univs_pending = _bank_pending("universities", univ_ko, univ_en)

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
