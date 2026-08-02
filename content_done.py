"""Shared MD-on-disk checks for topic bank state and backlog."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from content_slugs import content_item_slug, poi_item_slug
from topic_bank_registry import BankSpec

# Bank key → existing MD stem when the same content was saved under another name.
# Only explicit same-topic pairs (do not fuzzy-match different shops/guides).
OKRAMEN_ITEM_SLUG_ALIASES: dict[str, str] = {
    # Bank "Mennoya Kyoto" → files mennoya_en.md / mennoya_ko.md (shop_name: Mennoya)
    "mennoya_kyoto": "mennoya",
}

OKRAMEN_GUIDE_ALIASES: dict[str, str] = {
    "ramen_queue_etiquette": "ramen_etiquette",
    "ramen_seasonal_limited": "seasonal_ramen",
    "ramen_inflation_prices": "ramen_prices",
    "instant_ramen_hacks": "best-instant-ramen-japan",
    "female_solo_ramen": "solo_traveler_ramen",
    "how-to-order-kaedama": "how_to_order",
    "tsukemen": "tsukemen_art",
}


def _content_dirs(repo: Path) -> tuple[Path, Path]:
    content_dir = repo / "app" / "content"
    return content_dir, content_dir / "guides"


def _item_slug_candidates(site_id: str, name: str) -> list[str]:
    slug = content_item_slug(site_id, name)
    out = [slug]
    if site_id == "okramen":
        alt = OKRAMEN_ITEM_SLUG_ALIASES.get(slug)
        if alt and alt not in out:
            out.append(alt)
    return out


def _guide_id_candidates(site_id: str, gid: str) -> list[str]:
    out = [gid]
    if site_id == "okramen":
        alt = OKRAMEN_GUIDE_ALIASES.get(gid)
        if alt and alt not in out:
            out.append(alt)
        # hyphen/underscore equivalent
        swapped = gid.replace("-", "_") if "-" in gid else gid.replace("_", "-")
        if swapped != gid and swapped not in out:
            out.append(swapped)
    return out


def _poi_pair_missing(content_dir: Path, slug: str) -> int:
    en = content_dir / f"{slug}_en.md"
    ko = content_dir / f"{slug}_ko.md"
    return int(not en.is_file()) + int(not ko.is_file())


def _poi_pair_done(content_dir: Path, slugs: list[str]) -> bool:
    return any(_poi_pair_missing(content_dir, s) == 0 for s in slugs)


def _poi_pair_missing_best(content_dir: Path, slugs: list[str]) -> int:
    return min((_poi_pair_missing(content_dir, s) for s in slugs), default=2)


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
        iid = (row.get("id") or "").strip().removesuffix("_en")
        if not iid or iid.startswith("#"):
            return False
        if site_id == "okpy":
            return (repo / "app" / "content" / "posts" / "data-analysis" / f"{iid}.md").is_file()
        return (content_dir / f"{iid}_en.md").is_file()

    if spec.bank_id == "guides":
        gid = (row.get("id") or "").strip()
        if not gid:
            return False
        if site_id == "okpy":
            return (repo / "app" / "content" / "posts" / "data-analysis" / f"{gid}.md").is_file()
        for cand in _guide_id_candidates(site_id, gid):
            if any((guides_dir / f"{cand}{suf}.md").is_file() for suf in ("", "_en")):
                return True
        return False

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
        return _poi_pair_done(content_dir, _item_slug_candidates(site_id, name))

    if spec.bank_id == "positions":
        from starful_assets import position_slug

        name = (row.get("position_name") or "").strip()
        if not name:
            return False
        slug = position_slug(name)
        out_dir = repo / "app" / "contents"
        return (out_dir / f"{slug}.md").is_file() if out_dir.is_dir() else False

    if spec.bank_id in ("python", "cloud", "terraform"):
        topic = (row.get("lib_name") or row.get("Topic") or "").strip()
        if not topic:
            return False
        cat = spec.bank_id
        posts = repo / "app" / "content" / "posts" / cat
        if not posts.is_dir():
            return False
        needle = "".join(ch for ch in topic.lower() if ch.isalnum())
        if not needle:
            return False
        for md in posts.glob("*.md"):
            stem = "".join(ch for ch in md.stem.lower() if ch.isalnum())
            if needle in stem or stem in needle:
                return True
        return False

    return False


def row_backlog_missing_files(site_id: str, repo: Path, spec: BankSpec, row: dict[str, str]) -> int:
    """Count missing MD files for backlog UI; 0 means row is fully done."""
    content_dir, guides_dir = _content_dirs(repo)

    if spec.bank_id == "insights":
        iid = (row.get("id") or "").strip().removesuffix("_en")
        if not iid or iid.startswith("#"):
            return 0
        if site_id == "okpy":
            return int(
                not (repo / "app" / "content" / "posts" / "data-analysis" / f"{iid}.md").is_file()
            )
        return int(not (content_dir / f"{iid}_en.md").is_file())

    if spec.bank_id == "guides":
        gid = (row.get("id") or "").strip()
        if not gid:
            return 0
        if site_id == "okpy":
            return int(
                not (repo / "app" / "content" / "posts" / "data-analysis" / f"{gid}.md").is_file()
            )
        cands = _guide_id_candidates(site_id, gid)
        if site_id in ("okramen", "okonsen", "okcaddie"):
            return _poi_pair_missing_best(guides_dir, cands)
        for cand in cands:
            if any((guides_dir / f"{cand}{suf}.md").is_file() for suf in ("", "_en")):
                return 0
        return 1

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
        return _poi_pair_missing_best(content_dir, _item_slug_candidates(site_id, name))

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

    if spec.bank_id in ("python", "cloud", "terraform"):
        return 0 if is_content_row_done(site_id, repo, spec, row) else 1

    return 0
