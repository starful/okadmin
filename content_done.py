"""Shared MD-on-disk checks for topic bank state and backlog."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from content_slugs import content_item_slug, poi_item_slug
from topic_bank_registry import BankSpec


def _content_dirs(repo: Path) -> tuple[Path, Path]:
    content_dir = repo / "app" / "content"
    return content_dir, content_dir / "guides"


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
def univ_name_index(content_dir_str: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
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


def is_univ_row_done(repo: Path, row: dict[str, str]) -> bool:
    content_dir = repo / "app" / "content"
    name_ja = (row.get("name_ja") or "").strip()
    name_ko = (row.get("name_ko") or "").strip()
    name_en = (row.get("name_en") or "").strip().lower()
    if not name_ja and not name_ko and not name_en:
        return False
    ja_set, ko_set, en_set = univ_name_index(str(content_dir))
    if name_ja and name_ja in ja_set:
        return True
    if name_ko and name_ko in ko_set:
        return True
    if name_en and name_en in en_set:
        return True
    if name_ko:
        slug = poi_item_slug(name_ko)
        if (content_dir / f"univ_{slug}.md").is_file():
            return True
    return False


def is_content_row_done(site_id: str, repo: Path, spec: BankSpec, row: dict[str, str]) -> bool:
    """Row is complete for queue state (no further generation needed)."""
    content_dir, guides_dir = _content_dirs(repo)

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
        slug = poi_item_slug(ko)
        return (content_dir / f"school_{slug}.md").is_file() or any(
            content_dir.glob(f"school_*{slug}*.md")
        )

    if spec.bank_id == "universities":
        return is_univ_row_done(repo, row)

    if spec.bank_id in ("items",) or spec.key_kind == "coord":
        name = (row.get("Name") or row.get("name") or "").strip()
        if not name:
            return False
        slug = content_item_slug(site_id, name)
        en = content_dir / f"{slug}_en.md"
        ko = content_dir / f"{slug}_ko.md"
        return en.is_file() and ko.is_file()

    if spec.bank_id == "positions":
        from starful_assets import position_slug

        name = (row.get("position_name") or "").strip()
        if not name:
            return False
        slug = position_slug(name)
        out_dir = repo / "app" / "contents"
        return (out_dir / f"{slug}.md").is_file() if out_dir.is_dir() else False

    if spec.bank_id == "python":
        lib = (row.get("lib_name") or "").strip().lower()
        posts = repo / "posts"
        return any(posts.glob(f"*{lib}*.md")) if lib and posts.is_dir() else False

    if spec.bank_id == "cloud":
        return False

    return False


def row_backlog_missing_files(site_id: str, repo: Path, spec: BankSpec, row: dict[str, str]) -> int:
    """Count missing MD files for backlog UI; 0 means row is fully done."""
    content_dir, guides_dir = _content_dirs(repo)

    if spec.bank_id == "insights":
        iid = (row.get("id") or "").strip()
        if not iid or iid.startswith("#"):
            return 0
        return int(not (content_dir / f"{iid}_en.md").is_file())

    if spec.bank_id == "guides":
        gid = (row.get("id") or "").strip()
        if not gid:
            return 0
        if site_id in ("okramen", "okonsen", "okcaddie"):
            en = guides_dir / f"{gid}_en.md"
            ko = guides_dir / f"{gid}_ko.md"
            return int(not en.is_file()) + int(not ko.is_file())
        return int(
            not any((guides_dir / f"{gid}{suf}.md").is_file() for suf in ("", "_en"))
        )

    if spec.bank_id == "guide_topics":
        slug = (row.get("slug") or "").strip()
        if not slug:
            return 0
        for base in (repo / "app" / "content", repo / "data" / "guides", content_dir):
            if (base / f"guide_{slug}.md").is_file():
                return 0
        return 1

    if spec.bank_id == "language_schools":
        ko = (row.get("name_ko") or "").strip()
        if not ko:
            return 0
        slug = poi_item_slug(ko)
        if (content_dir / f"school_{slug}.md").is_file() or any(
            content_dir.glob(f"school_*{slug}*.md")
        ):
            return 0
        return 1

    if spec.bank_id == "universities":
        return 0 if is_univ_row_done(repo, row) else 1

    if spec.bank_id in ("items",) or spec.key_kind == "coord":
        name = (row.get("Name") or row.get("name") or "").strip()
        if not name:
            return 0
        slug = content_item_slug(site_id, name)
        en = content_dir / f"{slug}_en.md"
        ko = content_dir / f"{slug}_ko.md"
        return int(not en.is_file()) + int(not ko.is_file())

    if spec.bank_id == "positions":
        from starful_assets import position_slug

        name = (row.get("position_name") or "").strip()
        if not name:
            return 0
        slug = position_slug(name)
        out_dir = repo / "app" / "contents"
        if out_dir.is_dir() and (out_dir / f"{slug}.md").is_file():
            return 0
        return 1

    if spec.bank_id == "python":
        lib = (row.get("lib_name") or "").strip().lower()
        posts = repo / "posts"
        if lib and posts.is_dir() and any(posts.glob(f"*{lib}*.md")):
            return 0
        return 1 if lib else 0

    if spec.bank_id == "cloud":
        return 1

    return 0
