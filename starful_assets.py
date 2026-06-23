"""Starful GCS asset naming (must match starful.biz/scripts/slug_utils.py)."""
from __future__ import annotations

import re
from pathlib import Path

PROTECTED_ASSET_PREFIXES = ("favicon", "apple-touch")
PROTECTED_ASSET_NAMES = frozenset({"default", "default_og", "logo", "brand_biz_mark"})


def is_protected_asset(stem: str) -> bool:
    s = (stem or "").lower()
    if s in PROTECTED_ASSET_NAMES:
        return True
    return any(s.startswith(p) for p in PROTECTED_ASSET_PREFIXES)


def normalize_slug(slug: str) -> str:
    s = (slug or "").strip().lower().replace("-", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def position_slug(name: str) -> str:
    s = (name or "").strip().lower()
    for src, dst in (
        ("/", "_"),
        (" ", "_"),
        ("-", "_"),
        ("(", ""),
        (")", ""),
        (",", ""),
        ('"', ""),
    ):
        s = s.replace(src, dst)
    return normalize_slug(s)


def normalize_image_filename(filename: str) -> str:
    if not filename or "." not in filename:
        stem = normalize_slug(filename)
        return f"{stem}.png" if stem else filename
    stem, ext = filename.rsplit(".", 1)
    if is_protected_asset(stem):
        return filename
    norm = normalize_slug(stem)
    return f"{norm}.{ext.lower()}" if norm else filename


def legacy_hyphen_filename(filename: str) -> str | None:
    if not filename or "." not in filename:
        return None
    stem, ext = filename.rsplit(".", 1)
    if is_protected_asset(stem) or "-" in stem or "_" not in stem:
        return None
    return f"{stem.replace('_', '-')}.{ext.lower()}"


def canonical_starful_filename(slug: str) -> str:
    return f"{normalize_slug(slug)}.png"


def normalize_upload(image_key: str, slug: str, filename: str | None) -> tuple[str, str | None]:
    if image_key != "starful_biz":
        return slug, filename
    norm_slug = normalize_slug(slug or (Path(filename).stem if filename else ""))
    if not norm_slug:
        return slug, filename
    if filename:
        stem = Path(filename).stem
        if is_protected_asset(stem):
            return norm_slug, normalize_image_filename(filename)
    return norm_slug, canonical_starful_filename(norm_slug)


def legacy_blob_names(prefix: str, canonical_filename: str) -> list[str]:
    legacy = legacy_hyphen_filename(canonical_filename)
    if not legacy or legacy == canonical_filename:
        return []
    return [f"{prefix}{legacy}"]


def sibling_blob_names(prefix: str, canonical_filename: str) -> list[str]:
    """Same slug, other extensions + legacy hyphen names (to delete on replace)."""
    if not canonical_filename or "." not in canonical_filename:
        return []
    stem, _ = canonical_filename.rsplit(".", 1)
    if is_protected_asset(stem):
        return []
    out: list[str] = []
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        name = f"{stem}{ext}"
        if name != canonical_filename:
            out.append(f"{prefix}{name}")
    out.extend(legacy_blob_names(prefix, canonical_filename))
    return out
