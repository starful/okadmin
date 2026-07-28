"""GCS image tab: per-site slug metadata (CSV/MD, Places, prompt)."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import WORK_ROOT, gcs_sites, get_service, repo_path, work_root_available
from content_slugs import caddie_safe_name, csv_safe_name, okonsen_safe_name
from gsc_seo_worker import _parse_frontmatter, _write_frontmatter

# Sites with full meta panel + MD image_prompt editing in GCS tab
SITE_META_KEYS = frozenset({"okonsen", "okramen", "okcaddie", "statfacts", "krcampus", "jpcampus", "starful_biz", "krcare", "okpy"})


def _meta_slug(site_key: str, slug: str) -> str:
    """Normalize upload slug for MD/meta lookup (starful hero → base career)."""
    s = (slug or "").strip()
    if site_key == "starful_biz" and s.endswith("_hero"):
        return s[: -len("_hero")]
    return s


def _production_base(service_id: str, default: str) -> str:
    svc = get_service(service_id)
    if not svc:
        return default
    prod = (svc.get("links") or {}).get("production") or default
    return str(prod).rstrip("/")


def _gsc_url(service_id: str) -> str:
    svc = get_service(service_id) or {}
    return str((svc.get("links") or {}).get("gsc") or "")


def _content_dir(service_id: str, subdir: str = "app/content") -> Path | None:
    if not work_root_available():
        return None
    svc = get_service(service_id)
    if not svc:
        return None
    d = repo_path(svc) / subdir
    return d if d.is_dir() else None


def _read_yaml_md_bundle(content_dir: Path, slug: str, langs: tuple[str, ...]) -> tuple[dict[str, Any], list[Path]]:
    paths: list[Path] = []
    merged: dict[str, Any] = {}
    for lang in langs:
        p = content_dir / f"{slug}_{lang}.md"
        if not p.is_file():
            continue
        paths.append(p)
        meta, _, _, _ = _parse_frontmatter(p)
        if isinstance(meta, dict):
            for k, v in meta.items():
                if k not in merged or (v and not merged.get(k)):
                    merged[k] = v
    return merged, paths


def _read_krcampus_md_bundle(content_dir: Path, slug: str) -> tuple[dict[str, Any], list[Path]]:
    """KR Campus: `{slug}.md` (en) + `{slug}_ja.md`."""
    paths: list[Path] = []
    merged: dict[str, Any] = {}
    for p in (content_dir / f"{slug}.md", content_dir / f"{slug}_ja.md"):
        if not p.is_file():
            continue
        paths.append(p)
        meta, _, _, _ = _parse_frontmatter(p)
        if isinstance(meta, dict):
            for k, v in meta.items():
                if k not in merged or (v and not merged.get(k)):
                    merged[k] = v
    return merged, paths


def _read_jpcampus_stay_md_bundle(content_dir: Path, slug: str) -> tuple[dict[str, Any], list[Path]]:
    """JP Campus stays: `{slug}.md` (en) + `{slug}_kr.md`."""
    paths: list[Path] = []
    merged: dict[str, Any] = {}
    for p in (content_dir / f"{slug}.md", content_dir / f"{slug}_kr.md"):
        if not p.is_file():
            continue
        paths.append(p)
        meta, _, _, _ = _parse_frontmatter(p)
        if isinstance(meta, dict):
            for k, v in meta.items():
                if k not in merged or (v and not merged.get(k)):
                    merged[k] = v
    return merged, paths


def _krcampus_fields(md_meta: dict[str, Any], md_slug: str) -> dict[str, str]:
    basic = md_meta.get("basic_info") or {}
    if not isinstance(basic, dict):
        basic = {}
    loc = md_meta.get("location") or {}
    if not isinstance(loc, dict):
        loc = {}
    title = str(md_meta.get("title") or "").strip()
    name = (
        str(basic.get("name_en") or "").strip()
        or str(basic.get("name_ko") or "").strip()
        or title
        or md_slug
    )
    address = str(basic.get("address") or "").strip()
    lat = loc.get("lat")
    lng = loc.get("lng")
    feats = md_meta.get("features")
    if isinstance(feats, list):
        features = ", ".join(str(x) for x in feats if x)
    else:
        features = str(feats or "").strip()
    return {
        "name": name,
        "address": address,
        "lat": str(lat) if lat is not None and lat != "" else "",
        "lng": str(lng) if lng is not None and lng != "" else "",
        "features": features,
    }


def _jpcampus_stay_fields(md_meta: dict[str, Any], md_slug: str) -> dict[str, str]:
    basic = md_meta.get("basic_info") or {}
    if not isinstance(basic, dict):
        basic = {}
    loc = md_meta.get("location") or {}
    if not isinstance(loc, dict):
        loc = {}
    title = str(md_meta.get("title") or "").strip()
    name = (
        str(basic.get("name_en") or "").strip()
        or str(basic.get("name_ja") or "").strip()
        or title
        or md_slug
    )
    address = str(basic.get("address") or "").strip()
    lat = loc.get("lat")
    lng = loc.get("lng")
    operator = str(basic.get("operator") or "").strip()
    return {
        "name": name,
        "address": address,
        "lat": str(lat) if lat is not None and lat != "" else "",
        "lng": str(lng) if lng is not None and lng != "" else "",
        "features": operator,
    }


_STARFUL_JSON_BLOCK = re.compile(r"---json\s*(\{.*?\})\s*---(.*)", re.DOTALL)


def _parse_starful_md_file(path: Path) -> tuple[dict[str, Any], str] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _STARFUL_JSON_BLOCK.match(raw)
    if not match:
        return None
    try:
        meta = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None
    return meta, match.group(2)


def _write_starful_md_file(path: Path, meta: dict[str, Any], body: str) -> None:
    front = f"---json\n{json.dumps(meta, ensure_ascii=False, indent=2)}\n---\n"
    path.write_text(front + body.lstrip("\n"), encoding="utf-8")


def _load_csv_index_from_path(
    csv_path: Path,
    site_key: str,
    *,
    id_field: str = "Name",
) -> dict[str, dict[str, str]]:
    if not csv_path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    with csv_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if id_field == "Name":
                name = (row.get("Name") or "").strip()
                if not name:
                    continue
                key = csv_safe_name(site_key, name)
                out[key] = {
                    "name": name,
                    "lat": (row.get("Lat") or "").strip(),
                    "lng": (row.get("Lng") or "").strip(),
                    "address": (row.get("Address") or "").strip(),
                    "features": (row.get("Features") or "").strip(),
                    "thumbnail": (row.get("Thumbnail") or "").strip(),
                }
            else:
                rid = (row.get(id_field) or "").strip()
                if not rid or rid.startswith("#"):
                    continue
                topic = (row.get("topic") or "").strip()
                intervention = (row.get("intervention") or "").strip()
                out[rid] = {
                    "name": topic or intervention or rid,
                    "features": intervention,
                    "address": "",
                    "lat": "",
                    "lng": "",
                }
    return out


def _topic_bank_csv_path(site_key: str) -> Path | None:
    cfg = SITE_IMAGE_META.get(site_key) or {}
    bank_id = cfg.get("topic_bank_id")
    if not bank_id:
        return None
    service_id = cfg["service_id"]
    if not work_root_available():
        return None
    svc = get_service(service_id)
    if not svc:
        return None
    from topic_bank import bank_csv_path, ensure_bootstrapped

    repo = repo_path(svc)
    ensure_bootstrapped(service_id, repo)
    path = bank_csv_path(service_id, bank_id)
    return path if path.is_file() else None


def _load_csv_index(site_key: str, csv_rel: str, *, id_field: str = "Name") -> dict[str, dict[str, str]]:
    bank_path = _topic_bank_csv_path(site_key)
    if bank_path is not None:
        return _load_csv_index_from_path(bank_path, site_key, id_field=id_field)
    cfg = SITE_IMAGE_META[site_key]
    svc = get_service(cfg["service_id"])
    if not svc or not work_root_available():
        return {}
    csv_path = repo_path(svc) / csv_rel
    return _load_csv_index_from_path(csv_path, site_key, id_field=id_field)


@lru_cache(maxsize=8)
def _cached_csv_index(site_key: str) -> dict[str, dict[str, str]]:
    cfg = SITE_IMAGE_META.get(site_key) or {}
    if not cfg.get("topic_bank_id") and not cfg.get("csv_rel"):
        return {}
    csv_rel = cfg.get("csv_rel") or ""
    return _load_csv_index(site_key, csv_rel, id_field=cfg.get("csv_id_field", "Name"))


def _clear_csv_cache(site_key: str) -> None:
    _cached_csv_index.cache_clear()


def _resolve_md_slug(site_key: str, slug: str, content_dir: Path) -> str:
    """Find MD stem when blob slug uses underscores but files use hyphens."""
    if (content_dir / f"{slug}_en.md").is_file() or (content_dir / f"{slug}.md").is_file():
        return slug
    alt = slug.replace("_", "-")
    if alt != slug and (
        (content_dir / f"{alt}_en.md").is_file() or (content_dir / f"{alt}.md").is_file()
    ):
        return alt
    alt2 = slug.replace("-", "_")
    if alt2 != slug and (
        (content_dir / f"{alt2}_en.md").is_file() or (content_dir / f"{alt2}.md").is_file()
    ):
        return alt2
    return slug


def _cover_blob_stem(cover_url: str) -> str:
    path = (cover_url or "").split("?", 1)[0].strip()
    if not path:
        return ""
    return Path(path).name.rsplit(".", 1)[0]


def okpy_cover_stems_from_repo(repo: Path) -> set[str]:
    content_dir = repo / "app" / "content" / "posts"
    if not content_dir.is_dir():
        return set()
    stems: set[str] = set()
    for path in content_dir.rglob("*.md"):
        meta, _, _, _ = _parse_frontmatter(path)
        if not isinstance(meta, dict):
            continue
        stem = _cover_blob_stem(str(meta.get("cover") or ""))
        if stem:
            stems.add(stem)
    return stems


def okpy_posts_by_cover_stem(content_dir: Path) -> dict[str, dict[str, Any]]:
    """One-pass index: GCS cover basename → post frontmatter."""
    if not content_dir.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in content_dir.rglob("*.md"):
        meta, _, _, _ = _parse_frontmatter(path)
        if not isinstance(meta, dict):
            continue
        stem = _cover_blob_stem(str(meta.get("cover") or ""))
        if stem:
            out[stem] = meta
    return out


def okpy_post_lookup_index(content_dir: Path) -> dict[str, tuple[dict[str, Any], Path]]:
    """Keys: GCS cover stem, article slug, or MD path stem → (meta, path)."""
    out: dict[str, tuple[dict[str, Any], Path]] = {}
    if not content_dir.is_dir():
        return out
    for path in content_dir.rglob("*.md"):
        meta, _, _, _ = _parse_frontmatter(path)
        if not isinstance(meta, dict):
            continue
        entry = (meta, path)
        cover_stem = _cover_blob_stem(str(meta.get("cover") or ""))
        if cover_stem:
            out[cover_stem] = entry
        article_slug = str(meta.get("slug") or path.stem).strip()
        if article_slug:
            out[article_slug] = entry
        out[path.stem] = entry
    return out


def _okpy_post_resolve(content_dir: Path, slug: str) -> tuple[dict[str, Any], Path | None]:
    slug = (slug or "").strip()
    if not slug or not content_dir.is_dir():
        return {}, None
    entry = okpy_post_lookup_index(content_dir).get(slug)
    if entry:
        return entry
    alt = slug.replace("_", "-")
    if alt != slug:
        entry = okpy_post_lookup_index(content_dir).get(alt)
        if entry:
            return entry
    return {}, None


def _okpy_post_by_cover_stem(content_dir: Path, cover_stem: str) -> tuple[dict[str, Any], Path | None]:
    return _okpy_post_resolve(content_dir, cover_stem)


_COVER_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")


def okpy_canonical_cover_url(cover_url: str) -> str:
    """Normalize okpy GCS cover URL — never use legacy okpy/posts/ path."""
    clean = (cover_url or "").split("?", 1)[0].strip()
    if "/okpy/posts/" in clean:
        clean = clean.replace("/okpy/posts/", "/okpy/")
    return clean


def okpy_sync_cover_md(post_path: Path, cover_url: str) -> bool:
    """Sync okpy post frontmatter cover and the first inline cover image."""
    clean = okpy_canonical_cover_url(cover_url)
    if not clean or not post_path.is_file():
        return False
    meta, _raw, body, fmt = _parse_frontmatter(post_path)
    if not isinstance(meta, dict):
        return False
    meta["cover"] = clean
    body_text = body
    if _COVER_IMG_RE.search(body_text):
        body_text = _COVER_IMG_RE.sub(f"![cover]({clean})", body_text, count=1)
    elif "![" not in body_text.lstrip()[:500]:
        body_text = f"![cover]({clean})\n\n{body_text.lstrip(chr(10))}"
    _write_frontmatter(post_path, meta, body_text, fmt=fmt)
    return True


def _starful_title_index(content_dir: Path) -> dict[str, str]:
    if not content_dir.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in content_dir.glob("*.md"):
        if path.name.lower() in ("readme.md", "index.md"):
            continue
        parsed = _parse_starful_md_file(path)
        if parsed:
            out[path.stem] = str(parsed[0].get("title") or path.stem)
    return out


def _krcampus_enrich_index(content_dir: Path) -> dict[str, dict[str, str]]:
    if not content_dir.is_dir():
        return {}
    merged_by_slug: dict[str, dict[str, Any]] = {}
    for path in content_dir.glob("*.md"):
        stem = path.stem
        slug = stem[:-3] if stem.endswith("_ja") else stem
        meta, _, _, _ = _parse_frontmatter(path)
        if not isinstance(meta, dict):
            continue
        bucket = merged_by_slug.setdefault(slug, {})
        for k, v in meta.items():
            if k not in bucket or (v and not bucket.get(k)):
                bucket[k] = v
    return {slug: _krcampus_fields(meta, slug) for slug, meta in merged_by_slug.items()}


def _jpcampus_enrich_index(content_dir: Path) -> dict[str, dict[str, str]]:
    if not content_dir.is_dir():
        return {}
    merged_by_slug: dict[str, dict[str, Any]] = {}
    for path in content_dir.glob("*.md"):
        stem = path.stem
        slug = stem[:-3] if stem.endswith("_kr") else stem
        meta, _, _, _ = _parse_frontmatter(path)
        if not isinstance(meta, dict):
            continue
        bucket = merged_by_slug.setdefault(slug, {})
        for k, v in meta.items():
            if k not in bucket or (v and not bucket.get(k)):
                bucket[k] = v
    return {slug: _jpcampus_stay_fields(meta, slug) for slug, meta in merged_by_slug.items()}


def _krcare_enrich_index(content_dir: Path, langs: tuple[str, ...]) -> dict[str, dict[str, str]]:
    if not content_dir.is_dir():
        return {}
    slugs: set[str] = set()
    for path in content_dir.glob("*.md"):
        stem = path.stem
        for lang in langs:
            suf = f"_{lang}"
            if stem.endswith(suf):
                slugs.add(stem[: -len(suf)])
                break
    out: dict[str, dict[str, str]] = {}
    for slug in slugs:
        md_meta, _ = _read_yaml_md_bundle(content_dir, slug, langs)
        if not md_meta:
            continue
        title = str(md_meta.get("title") or "").strip()
        out[slug] = {
            "name": title or slug,
            "address": str(md_meta.get("address") or ""),
            "features": "",
        }
    return out


def _build_enrich_index(site_key: str, content_dir: Path | None, cfg: dict[str, Any]) -> dict[str, Any]:
    if not content_dir or not content_dir.is_dir():
        return {}
    if site_key == "okpy":
        return {"okpy_by_cover": okpy_posts_by_cover_stem(content_dir)}
    if site_key == "starful_biz":
        return {"starful_titles": _starful_title_index(content_dir)}
    if site_key == "krcampus":
        return {"krcampus": _krcampus_enrich_index(content_dir)}
    if site_key == "jpcampus":
        return {"jpcampus": _jpcampus_enrich_index(content_dir)}
    if site_key == "krcare":
        langs = tuple(cfg.get("md_langs") or ("en", "ja", "zh_tw", "zh"))
        return {"krcare": _krcare_enrich_index(content_dir, langs)}
    return {}


def enrich_site_image_rows(site_key: str, rows: list[dict]) -> list[dict]:
    if site_key not in SITE_IMAGE_META:
        return rows
    index = _cached_csv_index(site_key)
    cfg = SITE_IMAGE_META[site_key]
    svc_id = cfg["service_id"]
    content_dir = _content_dir(svc_id, cfg.get("content_dir", "app/content"))
    enrich_idx = _build_enrich_index(site_key, content_dir, cfg)

    for row in rows:
        slug = row.get("slug") or ""
        meta_slug = _meta_slug(site_key, slug)
        csv_row = index.get(meta_slug) or index.get(slug) or {}
        row["name"] = csv_row.get("name") or ""
        row["address"] = csv_row.get("address") or ""
        row["features"] = csv_row.get("features") or ""
        if not row["name"] and site_key == "starful_biz":
            row["name"] = enrich_idx.get("starful_titles", {}).get(meta_slug) or ""
        if site_key == "krcampus":
            kr = enrich_idx.get("krcampus", {}).get(meta_slug) or enrich_idx.get("krcampus", {}).get(slug)
            if kr:
                row["name"] = row["name"] or kr["name"]
                row["address"] = row["address"] or kr["address"]
                row["features"] = row["features"] or kr["features"]
        if site_key == "jpcampus":
            jp = enrich_idx.get("jpcampus", {}).get(meta_slug) or enrich_idx.get("jpcampus", {}).get(slug)
            if jp:
                row["name"] = row["name"] or jp["name"]
                row["address"] = row["address"] or jp["address"]
                row["features"] = row["features"] or jp["features"]
        if site_key == "okpy":
            post_meta = enrich_idx.get("okpy_by_cover", {}).get(meta_slug) or enrich_idx.get("okpy_by_cover", {}).get(slug)
            if post_meta:
                title = str(post_meta.get("title") or "").strip()
                row["name"] = row["name"] or title or meta_slug
        if site_key == "krcare":
            kr = enrich_idx.get("krcare", {}).get(meta_slug) or enrich_idx.get("krcare", {}).get(slug)
            if kr:
                row["name"] = row["name"] or kr["name"]
                row["address"] = row["address"] or kr["address"]
    return rows


def _build_page_urls(site_key: str, slug: str, content_dir: Path | None, base: str) -> dict[str, str]:
    if not content_dir:
        return {}
    if site_key == "starful_biz":
        if (content_dir / f"{slug}.md").is_file():
            return {"ja": f"{base}/career/{slug}"}
        return {}
    if site_key == "okpy":
        return {"ja": f"{base}/blog/{slug}"}
    if site_key == "okcaddie":
        out: dict[str, str] = {}
        if (content_dir / f"{slug}_en.md").is_file():
            out["en"] = f"{base}/course/{slug}"
        if (content_dir / f"{slug}_ko.md").is_file():
            out["ko"] = f"{base}/course/{slug}?lang=ko"
        return out
    if site_key == "krcampus":
        out: dict[str, str] = {}
        if (content_dir / f"{slug}.md").is_file():
            out["en"] = f"{base}/school/{slug}"
        if (content_dir / f"{slug}_ja.md").is_file():
            out["ja"] = f"{base}/school/{slug}?lang=ja"
        return out
    if site_key == "krcare":
        out: dict[str, str] = {}
        for lang in ("en", "ja", "zh_tw", "zh"):
            if (content_dir / f"{slug}_{lang}.md").is_file():
                out[lang] = f"{base}/item/{slug}_{lang}"
        return out
    if site_key == "jpcampus":
        # stay_*/guide_*/school_*|univ_* each have different public URL shapes.
        out: dict[str, str] = {}
        if slug.startswith("stay_"):
            stay_id = slug[5:]
            if (content_dir / f"{slug}.md").is_file():
                out["en"] = f"{base}/stay/{stay_id}?lang=en"
            if (content_dir / f"{slug}_kr.md").is_file():
                out["kr"] = f"{base}/stay/{stay_id}?lang=kr"
            return out
        if slug.startswith("guide_"):
            guide_id = slug[6:]
            if (content_dir / f"{slug}.md").is_file():
                out["en"] = f"{base}/guide/{guide_id}"
            if (content_dir / f"{slug}_kr.md").is_file():
                out["kr"] = f"{base}/guide/{guide_id}?lang=kr"
            return out
        # school_ / univ_ (and any other campus listing slug)
        if (content_dir / f"{slug}.md").is_file():
            out["en"] = f"{base}/school/{slug}"
        if (content_dir / f"{slug}_kr.md").is_file():
            out["kr"] = f"{base}/school/{slug}?lang=kr"
        return out
    path_prefix = {
        "okonsen": "onsen",
        "okramen": "ramen",
        "statfacts": "insight",
    }.get(site_key, "")
    if not path_prefix:
        return {}
    out = {}
    for lang in ("en", "ko"):
        if (content_dir / f"{slug}_{lang}.md").is_file():
            out[lang] = f"{base}/{path_prefix}/{slug}_{lang}"
    return out


def _korean_name_from_title(title: str) -> str:
    """Last top-level (…한글…) group in a clinic title."""
    groups: list[str] = []
    depth = 0
    start: int | None = None
    for i, ch in enumerate(title or ""):
        if ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                groups.append(title[start:i])
                start = None
    korean = [g.strip() for g in groups if re.search(r"[\uac00-\ud7a3]", g)]
    return korean[-1] if korean else ""


def _krcare_places_queries(title: str, address: str) -> list[str]:
    title = (title or "").strip()
    address = (address or "").strip()
    ko = _korean_name_from_title(title)
    plain = re.sub(r"\s*\([^)]*\)\s*", " ", title).strip()
    queries: list[str] = []
    if ko:
        queries.extend([ko, f"{ko} 병원", f"{ko} 의원"])
    if plain:
        queries.append(plain)
    if title and title not in queries:
        queries.append(title)
    if ko and address:
        queries.append(f"{ko} {address}")
    if address and not ko:
        queries.append(address)
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def _places_query(site_key: str, name: str, address: str, *, title: str = "") -> str:
    if site_key == "krcare":
        queries = _krcare_places_queries(title or name, address)
        return queries[0] if queries else (name or "").strip()
    cfg = SITE_IMAGE_META.get(site_key) or {}
    if cfg.get("places_query_style") == "name_country":
        suffix = str(cfg.get("places_suffix") or "").strip()
        q = name.strip()
        if suffix and suffix.lower() not in q.lower():
            return f"{q} {suffix}".strip()
        return q

    q = name
    if address:
        q = f"{name} {address}"
    suffix = cfg.get("places_suffix")
    alt = cfg.get("places_suffix_alt")
    if suffix and suffix.lower() not in q.lower():
        if alt and alt not in q:
            return f"{q} {suffix}".strip()
        return f"{q} {suffix}".strip()
    return q.strip()


def places_search_opts(site_key: str) -> dict[str, Any]:
    """Per-site Places API (New) searchText / searchNearby options."""
    cfg = SITE_IMAGE_META.get(site_key) or {}
    return {
        "language_code": str(cfg.get("places_language") or "ja"),
        "region_code": str(cfg.get("places_region") or "").strip().upper(),
        "bias_radius_m": float(cfg.get("places_bias_m") or 1500),
        "nearby_fallback": cfg.get("places_nearby_fallback", True),
    }


def site_image_meta(site_key: str, slug: str) -> dict[str, Any]:
    slug = _meta_slug(site_key, (slug or "").strip())
    if not slug or site_key not in SITE_IMAGE_META:
        return {"ok": False, "error": "invalid site or slug"}

    cfg = SITE_IMAGE_META[site_key]
    svc_id = cfg["service_id"]
    content_dir = _content_dir(svc_id, cfg.get("content_dir", "app/content"))
    md_slug = _resolve_md_slug(site_key, slug, content_dir) if content_dir else slug

    csv_row: dict[str, str] = {}
    if cfg.get("topic_bank_id") or cfg.get("csv_rel"):
        csv_row = dict(_cached_csv_index(site_key).get(md_slug) or _cached_csv_index(site_key).get(slug) or {})

    md_meta: dict[str, Any] = {}
    md_paths: list[Path] = []
    if content_dir and cfg.get("md_format") == "starful_json":
        p = content_dir / f"{md_slug}.md"
        if p.is_file():
            md_paths = [p]
            parsed = _parse_starful_md_file(p)
            if parsed:
                md_meta = parsed[0]
    elif content_dir and cfg.get("md_format") == "krcampus":
        md_meta, md_paths = _read_krcampus_md_bundle(content_dir, md_slug)
    elif content_dir and cfg.get("md_format") == "jpcampus_stay":
        md_meta, md_paths = _read_jpcampus_stay_md_bundle(content_dir, md_slug)
    elif content_dir and cfg.get("md_format") == "okpy_post":
        post_meta, post_path = _okpy_post_resolve(content_dir, slug)
        if post_path:
            md_paths = [post_path]
            md_meta = post_meta
            md_slug = str(post_meta.get("slug") or post_path.stem).strip() or md_slug
    elif content_dir:
        langs = cfg.get("md_langs") or ("en", "ko")
        md_meta, md_paths = _read_yaml_md_bundle(content_dir, md_slug, langs)

    title = str(md_meta.get("title") or "").strip()
    if cfg.get("md_format") == "krcampus":
        kr = _krcampus_fields(md_meta, md_slug)
        name = csv_row.get("name") or kr["name"]
        address = csv_row.get("address") or kr["address"]
        lat = csv_row.get("lat") or kr["lat"]
        lng = csv_row.get("lng") or kr["lng"]
        features = csv_row.get("features") or kr["features"]
    elif cfg.get("md_format") == "jpcampus_stay":
        jp = _jpcampus_stay_fields(md_meta, md_slug)
        name = csv_row.get("name") or jp["name"]
        address = csv_row.get("address") or jp["address"]
        lat = csv_row.get("lat") or jp["lat"]
        lng = csv_row.get("lng") or jp["lng"]
        features = csv_row.get("features") or jp["features"]
    else:
        name = csv_row.get("name") or title.split(":")[0].strip() or title or md_slug
        address = csv_row.get("address") or str(md_meta.get("address") or "")
        lat = csv_row.get("lat") or str(md_meta.get("lat") or "")
        lng = csv_row.get("lng") or str(md_meta.get("lng") or "")
        features = csv_row.get("features") or ""
    image_prompt = str(md_meta.get("image_prompt") or "").strip()

    maps_url = ""
    if lat and lng:
        try:
            maps_url = f"https://www.google.com/maps?q={float(lat)},{float(lng)}"
        except ValueError:
            pass

    places_query = _places_query(site_key, name, address, title=title) if cfg.get("uses_places", True) else ""
    places_queries = _krcare_places_queries(title or name, address) if site_key == "krcare" else []
    base = _production_base(svc_id, cfg.get("production_default", ""))

    date_raw = md_meta.get("date") or md_meta.get("published") or md_meta.get("published_at")

    return {
        "ok": True,
        "site": site_key,
        "slug": md_slug,
        "upload_slug": slug,
        "name": name,
        "name_label": cfg.get("name_label", "이름"),
        "address": address,
        "lat": lat,
        "lng": lng,
        "features": features,
        "image_prompt": image_prompt,
        "prompt_editable": cfg.get("prompt_editable", True),
        "imagen_enabled": bool(cfg.get("imagen_enabled")),
        "maps_url": maps_url,
        "places_query": places_query,
        "places_queries": places_queries,
        "content_id": str(md_meta.get("content_id") or "").strip(),
        "uses_places": cfg.get("uses_places", True),
        "page_urls": _build_page_urls(site_key, md_slug, content_dir, base),
        "production_base": base,
        "gsc_url": _gsc_url(svc_id),
        "md_files": [str(p.relative_to(WORK_ROOT)) for p in md_paths],
        "csv_match": bool(csv_row),
        "thumbnail_cache_v": _thumbnail_cache_v(date_raw),
    }


def site_save_image_prompt(site_key: str, slug: str, prompt: str) -> dict[str, Any]:
    slug = _meta_slug(site_key, (slug or "").strip())
    prompt = (prompt or "").strip()
    if not slug:
        return {"ok": False, "error": "slug required"}
    cfg = SITE_IMAGE_META.get(site_key)
    if not cfg or not cfg.get("prompt_editable", True):
        return {"ok": False, "error": f"prompt save not supported for {site_key}"}

    svc_id = cfg["service_id"]
    content_dir = _content_dir(svc_id, cfg.get("content_dir", "app/content"))
    if not content_dir:
        return {"ok": False, "error": "content dir not found"}

    md_slug = _resolve_md_slug(site_key, slug, content_dir)
    updated: list[str] = []

    if cfg.get("md_format") == "starful_json":
        p = content_dir / f"{md_slug}.md"
        if p.is_file():
            parsed = _parse_starful_md_file(p)
            if parsed:
                meta, body = parsed
                meta["image_prompt"] = prompt
                _write_starful_md_file(p, meta, body)
                updated.append(str(p.relative_to(WORK_ROOT)))
    else:
        for lang in cfg.get("md_langs") or ("en", "ko"):
            p = content_dir / f"{md_slug}_{lang}.md"
            if not p.is_file():
                continue
            meta, _, body, fmt = _parse_frontmatter(p)
            if not isinstance(meta, dict):
                meta = {}
            meta["image_prompt"] = prompt
            _write_frontmatter(p, meta, body, fmt=fmt)
            updated.append(str(p.relative_to(WORK_ROOT)))

    if not updated:
        return {"ok": False, "error": f"no MD for slug: {md_slug}"}
    _clear_csv_cache(site_key)
    return {"ok": True, "updated": updated, "image_prompt": prompt}


# --- okonsen aliases (backward compat) ---

def okonsen_row_for_slug(slug: str) -> dict[str, str]:
    return dict(_cached_csv_index("okonsen").get(slug) or {})


def okonsen_meta(slug: str) -> dict[str, Any]:
    return site_image_meta("okonsen", slug)


def okonsen_save_image_prompt(slug: str, prompt: str) -> dict[str, Any]:
    return site_save_image_prompt("okonsen", slug, prompt)


def enrich_okonsen_image_rows(rows: list[dict]) -> list[dict]:
    return enrich_site_image_rows("okonsen", rows)


SITE_IMAGE_META: dict[str, dict[str, Any]] = {
    "okonsen": {
        "service_id": "okonsen",
        "topic_bank_id": "items",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "name_label": "온천·료칸",
        "places_suffix": "onsen",
        "places_suffix_alt": "温泉",
        "production_default": "https://okonsen.net",
        "uses_places": True,
        "prompt_editable": True,
    },
    "okramen": {
        "service_id": "okramen",
        "topic_bank_id": "items",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "name_label": "라멘店",
        "places_suffix": "ramen",
        "places_suffix_alt": "ラーメン",
        "production_default": "https://okramen.net",
        "uses_places": True,
        "prompt_editable": True,
    },
    "okcaddie": {
        "service_id": "okcaddie",
        "topic_bank_id": "items",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "name_label": "ゴルフ場",
        "places_suffix": "golf course",
        "places_suffix_alt": "ゴルフ",
        "production_default": "https://okcaddie.net",
        "uses_places": True,
        "prompt_editable": True,
    },
    "statfacts": {
        "service_id": "statfacts",
        "topic_bank_id": "insights",
        "csv_id_field": "id",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "name_label": "Insight",
        "production_default": "https://statfacts.net",
        "uses_places": False,
        "prompt_editable": False,
        "imagen_enabled": True,
        "imagen_aspect_ratio": "16:9",
        "imagen_prompt_suffix": (
            "Editorial infographic illustration, clean modern style, "
            "high quality, no text, no watermark, no logos."
        ),
    },
    "starful_biz": {
        "service_id": "starful.biz",
        "content_dir": "app/contents",
        "md_format": "starful_json",
        "name_label": "職種",
        "production_default": "https://starful.biz",
        "uses_places": False,
        "prompt_editable": False,
        "imagen_enabled": True,
        "imagen_aspect_ratio": "4:3",
        "imagen_output_mime": "image/png",
    },
    "okpy": {
        "service_id": "okpy",
        "content_dir": "app/content/posts",
        "local_images_dir": "app/static/images/posts",
        "md_format": "okpy_post",
        "name_label": "기사",
        "production_default": "https://okpy.net",
        "uses_places": False,
        "prompt_editable": False,
        "imagen_enabled": True,
        "imagen_aspect_ratio": "16:9",
    },
    "krcampus": {
        "service_id": "krcampus",
        "content_dir": "app/content",
        "md_format": "krcampus",
        "name_label": "語学堂·大学",
        "places_suffix": "South Korea",
        "places_query_style": "name_country",
        "places_language": "en",
        "places_region": "KR",
        "places_bias_m": 3000,
        "places_nearby_fallback": False,
        "production_default": "https://krcampus.net",
        "uses_places": True,
        "prompt_editable": False,
    },
    "jpcampus": {
        "service_id": "jpcampus",
        "content_dir": "app/content",
        "md_format": "jpcampus_stay",
        "name_label": "学生宿舎",
        "places_suffix": "Tokyo Japan",
        "places_query_style": "name_country",
        "places_language": "ja",
        "places_region": "JP",
        "places_bias_m": 800,
        "places_nearby_fallback": True,
        "production_default": "https://jpcampus.net",
        "uses_places": True,
        "prompt_editable": False,
    },
    "krcare": {
        "service_id": "krcare",
        "content_dir": "app/content",
        # One thumbnail per clinic base_id (mdcl_NNNN.jpg); MD is per-lang.
        "md_langs": ("en", "ja", "zh_tw", "zh"),
        "local_images_dir": "app/static/images",
        "name_label": "Clinic",
        "places_language": "ko",
        "places_region": "KR",
        "places_bias_m": 2000,
        "places_nearby_fallback": True,
        "production_default": "https://krcare.net",
        "uses_places": True,
        "prompt_editable": False,
    },
}


IMAGEN_SITE_KEYS = frozenset(k for k, v in SITE_IMAGE_META.items() if v.get("imagen_enabled"))


def imagen_site_config(site_key: str) -> dict[str, Any]:
    cfg = SITE_IMAGE_META.get(site_key) or {}
    return {
        "aspect_ratio": cfg.get("imagen_aspect_ratio", "16:9"),
        "output_mime_type": cfg.get("imagen_output_mime", "image/jpeg"),
        "prompt_suffix": str(cfg.get("imagen_prompt_suffix") or ""),
        "person_generation": cfg.get("imagen_person_generation", "allow_adult"),
    }


def resolve_imagen_prompt(site_key: str, slug: str, meta: dict[str, Any] | None = None) -> str:
    if meta is None:
        meta = site_image_meta(site_key, slug)
    gcs_cfg = gcs_sites().get(site_key) or {}
    tpl = str(gcs_cfg.get("prompt_template") or "").strip()
    if tpl:
        prompt_slug = str(meta.get("slug") or slug).strip()
        return tpl.replace("[{slug}]", prompt_slug)
    return str(meta.get("image_prompt") or "").strip()


def _thumbnail_cache_v(raw: Any) -> str:
    v = str(raw or "").strip()[:10]
    return v if len(v) >= 8 else ""


def thumbnail_with_v(url: str, cache_v: str | None = None) -> str:
    if not url:
        return url
    v = _thumbnail_cache_v(cache_v)
    base = url.split("?", 1)[0]
    return f"{base}?v={v}" if v else base


def _localized_base_id(record_id: str) -> str:
    oid = str(record_id or "")
    for suf in ("_zh_tw", "_en", "_ja", "_zh", "_ko"):
        if oid.endswith(suf):
            return oid[: -len(suf)]
    return oid


def _json_row_matches_slug(row: dict[str, Any], slug: str, *, match: str) -> bool:
    rid = str(row.get("id") or "")
    thumb = str(row.get("thumbnail") or "")
    if match == "localized":
        base = _localized_base_id(rid)
        return base == slug or f"/{slug}.jpg" in thumb or f"/{slug}.png" in thumb
    if match == "exact":
        return rid == slug or f"/{slug}.jpg" in thumb or f"/{slug}.png" in thumb
    if match == "jpcampus_stay":
        base_id = slug[5:] if slug.startswith("stay_") else slug
        return rid == base_id or f"/{slug}.jpg" in thumb or f"/{base_id}.jpg" in thumb
    return rid == slug


SITE_THUMBNAIL_CACHE: dict[str, dict[str, Any]] = {
    "okonsen": {
        "service_id": "okonsen",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "md_date_field": "date",
        "json_path": "app/static/json/onsen_data.json",
        "json_key": "onsens",
        "json_match": "localized",
    },
    "okramen": {
        "service_id": "okramen",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "md_date_field": "date",
        "json_path": "app/static/json/ramen_data.json",
        "json_key": "ramens",
        "json_match": "localized",
    },
    "okcaddie": {
        "service_id": "okcaddie",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "md_date_field": "date",
        "json_path": "app/static/json/courses_data.json",
        "json_key": "courses",
        "json_match": "localized",
    },
    "statfacts": {
        "service_id": "statfacts",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "md_date_field": "date",
        "json_path": "app/static/json/insights_data.json",
        "json_key": "insights",
        "json_match": "localized",
    },
    "starful_biz": {
        "service_id": "starful.biz",
        "content_dir": "app/contents",
        "md_langs": (),
        "md_date_field": "published_at",
        "json_path": "app/static/json/job_data.json",
        "json_key": "jobs",
        "json_match": "exact",
        "md_format": "starful_json",
    },
    "krcampus": {
        "service_id": "krcampus",
        "content_dir": "app/content",
        "md_date_field": "date",
        "json_paths": [
            "app/static/json/schools_data.json",
            "app/static/json/schools_data_ja.json",
        ],
        "json_key": "schools",
        "json_match": "exact",
        "md_format": "krcampus",
    },
    "jpcampus": {
        "service_id": "jpcampus",
        "content_dir": "app/content",
        "md_date_field": "date",
        "json_paths": [
            "app/static/json/stays_data.json",
            "app/static/json/stays_data_kr.json",
        ],
        "json_key": "stays",
        "json_match": "jpcampus_stay",
        "md_format": "jpcampus_stay",
    },
    "krcare": {
        "service_id": "krcare",
        "content_dir": "app/content",
        "md_langs": ("en", "ja", "zh_tw", "zh"),
        "md_date_field": "date",
        "json_path": "app/static/json/items_data.json",
        "json_key": "items",
        "json_match": "localized",
    },
    "okpy": {
        "service_id": "okpy",
        "content_dir": "app/content/posts",
        "md_format": "okpy_post",
        "md_date_field": "date",
    },
}


def _career_slug_from_upload(slug: str) -> str:
    stem = (slug or "").strip()
    if stem.endswith("_hero"):
        return stem[: -len("_hero")]
    return stem


def bump_site_thumbnail_cache(site_key: str, slug: str) -> dict[str, Any]:
    """After GCS image replace: bump MD date + site JSON published for stable ?v=."""
    slug = _career_slug_from_upload((slug or "").strip())
    cfg = SITE_THUMBNAIL_CACHE.get(site_key)
    if not cfg:
        return {"ok": False, "error": f"unsupported site: {site_key}"}
    if not slug:
        return {"ok": False, "error": "slug required"}

    svc = get_service(cfg["service_id"])
    if not svc or not work_root_available():
        return {"ok": False, "error": f"{cfg['service_id']} repo not found"}

    repo = repo_path(svc)
    content_dir = repo / cfg["content_dir"]
    bump_date = date.today().isoformat()
    updated_md: list[str] = []
    date_field = cfg["md_date_field"]
    is_starful = cfg.get("md_format") == "starful_json"
    md_slug = _resolve_md_slug(site_key, slug, content_dir) if content_dir.is_dir() else slug

    if is_starful:
        md_path = content_dir / f"{md_slug}.md"
        if md_path.is_file():
            parsed = _parse_starful_md_file(md_path)
            if parsed:
                meta, body = parsed
                meta[date_field] = bump_date
                _write_starful_md_file(md_path, meta, body)
                updated_md.append(str(md_path.relative_to(WORK_ROOT)))
    elif cfg.get("md_format") == "krcampus":
        for md_path in (content_dir / f"{md_slug}.md", content_dir / f"{md_slug}_ja.md"):
            if not md_path.is_file():
                continue
            meta, _, body, fmt = _parse_frontmatter(md_path)
            if not isinstance(meta, dict):
                meta = {}
            meta[date_field] = bump_date
            _write_frontmatter(md_path, meta, body, fmt=fmt)
            updated_md.append(str(md_path.relative_to(WORK_ROOT)))
    elif cfg.get("md_format") == "jpcampus_stay":
        for md_path in (content_dir / f"{md_slug}.md", content_dir / f"{md_slug}_kr.md"):
            if not md_path.is_file():
                continue
            meta, _, body, fmt = _parse_frontmatter(md_path)
            if not isinstance(meta, dict):
                meta = {}
            meta[date_field] = bump_date
            _write_frontmatter(md_path, meta, body, fmt=fmt)
            updated_md.append(str(md_path.relative_to(WORK_ROOT)))
    else:
        for lang in cfg.get("md_langs") or ():
            md_path = content_dir / f"{md_slug}_{lang}.md"
            if not md_path.is_file():
                continue
            meta, _, body, fmt = _parse_frontmatter(md_path)
            if not isinstance(meta, dict):
                meta = {}
            meta[date_field] = bump_date
            _write_frontmatter(md_path, meta, body, fmt=fmt)
            updated_md.append(str(md_path.relative_to(WORK_ROOT)))

    json_count = 0
    json_targets = cfg.get("json_paths") or ([cfg["json_path"]] if cfg.get("json_path") else [])
    for json_rel in json_targets:
        json_path = repo / json_rel
        if not json_path.is_file():
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            touched = 0
            for row in data.get(cfg["json_key"], []):
                if _json_row_matches_slug(row, md_slug, match=cfg["json_match"]):
                    row["published"] = bump_date
                    touched += 1
            if touched:
                data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
                json_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                json_count += touched
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            return {
                "ok": False,
                "error": f"{json_path.name} patch failed: {exc}",
                "updated_md": updated_md,
            }

    if not updated_md and json_count == 0:
        return {"ok": False, "error": f"no MD/JSON rows for slug: {md_slug}"}

    _clear_csv_cache(site_key)
    return {
        "ok": True,
        "site": site_key,
        "slug": md_slug,
        "date": bump_date,
        "thumbnail_cache_v": bump_date,
        "updated_md": updated_md,
        "updated_json": json_count,
    }


def okonsen_bump_thumbnail_cache(slug: str) -> dict[str, Any]:
    return bump_site_thumbnail_cache("okonsen", slug)
