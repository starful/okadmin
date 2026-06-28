"""GCS image tab: per-site slug metadata (CSV/MD, Places, prompt)."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import WORK_ROOT, get_service, repo_path, work_root_available
from gsc_seo_worker import _parse_frontmatter, _write_frontmatter

OKONSEN_CSV_REL = "script/csv/onsens.csv"

# Sites with full meta panel + MD image_prompt editing in GCS tab
SITE_META_KEYS = frozenset({"okonsen", "okramen", "okcaddie", "okstats", "krcampus", "starful_biz"})


def okonsen_safe_name(name: str) -> str:
    return name.lower().replace(" ", "_").replace("'", "").replace(",", "")


def caddie_safe_name(name: str) -> str:
    return (
        name.lower()
        .replace(" ", "_")
        .replace("'", "")
        .replace(",", "")
        .replace("&", "and")
        .replace(".", "")
    )


def _csv_safe_name(site_key: str, name: str) -> str:
    if site_key == "okcaddie":
        return caddie_safe_name(name)
    return okonsen_safe_name(name)


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


def _load_csv_index(site_key: str, csv_rel: str, *, id_field: str = "Name") -> dict[str, dict[str, str]]:
    cfg = SITE_IMAGE_META[site_key]
    svc = get_service(cfg["service_id"])
    if not svc or not work_root_available():
        return {}
    csv_path = repo_path(svc) / csv_rel
    if not csv_path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    with csv_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if id_field == "Name":
                name = (row.get("Name") or "").strip()
                if not name:
                    continue
                key = _csv_safe_name(site_key, name)
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


@lru_cache(maxsize=8)
def _cached_csv_index(site_key: str) -> dict[str, dict[str, str]]:
    cfg = SITE_IMAGE_META.get(site_key) or {}
    csv_rel = cfg.get("csv_rel")
    if not csv_rel:
        return {}
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


def _build_page_urls(site_key: str, slug: str, content_dir: Path | None, base: str) -> dict[str, str]:
    if not content_dir:
        return {}
    if site_key == "starful_biz":
        if (content_dir / f"{slug}.md").is_file():
            return {"ja": f"{base}/career/{slug}"}
        return {}
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
    path_prefix = {
        "okonsen": "onsen",
        "okramen": "ramen",
        "okstats": "insight",
    }.get(site_key, "")
    if not path_prefix:
        return {}
    out = {}
    for lang in ("en", "ko"):
        if (content_dir / f"{slug}_{lang}.md").is_file():
            out[lang] = f"{base}/{path_prefix}/{slug}_{lang}"
    return out


def _places_query(site_key: str, name: str, address: str) -> str:
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
    if cfg.get("csv_rel"):
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

    places_query = _places_query(site_key, name, address) if cfg.get("uses_places", True) else ""
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
        "maps_url": maps_url,
        "places_query": places_query,
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


def enrich_site_image_rows(site_key: str, rows: list[dict]) -> list[dict]:
    if site_key not in SITE_IMAGE_META:
        return rows
    index = _cached_csv_index(site_key)
    cfg = SITE_IMAGE_META[site_key]
    svc_id = cfg["service_id"]
    content_dir = _content_dir(svc_id, cfg.get("content_dir", "app/content"))

    for row in rows:
        slug = row.get("slug") or ""
        meta_slug = _meta_slug(site_key, slug)
        csv_row = index.get(meta_slug) or index.get(slug) or {}
        row["name"] = csv_row.get("name") or ""
        row["address"] = csv_row.get("address") or ""
        row["features"] = csv_row.get("features") or ""
        if not row["name"] and content_dir and site_key == "starful_biz":
            p = content_dir / f"{meta_slug}.md"
            if p.is_file():
                parsed = _parse_starful_md_file(p)
                if parsed:
                    row["name"] = str(parsed[0].get("title") or meta_slug)
        if content_dir and site_key == "krcampus":
            md_meta, _ = _read_krcampus_md_bundle(content_dir, meta_slug)
            if md_meta:
                kr = _krcampus_fields(md_meta, meta_slug)
                row["name"] = row["name"] or kr["name"]
                row["address"] = row["address"] or kr["address"]
                row["features"] = row["features"] or kr["features"]
    return rows


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
        "csv_rel": "script/csv/onsens.csv",
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
        "csv_rel": "script/csv/ramens.csv",
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
        "csv_rel": "script/csv/courses.csv",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "name_label": "ゴルフ場",
        "places_suffix": "golf course",
        "places_suffix_alt": "ゴルフ",
        "production_default": "https://okcaddie.net",
        "uses_places": True,
        "prompt_editable": True,
    },
    "okstats": {
        "service_id": "okstats",
        "csv_rel": "script/csv/insights.csv",
        "csv_id_field": "id",
        "content_dir": "app/content",
        "md_langs": ("en", "ko"),
        "name_label": "Insight",
        "production_default": "https://statfacts.net",
        "uses_places": False,
        "prompt_editable": True,
    },
    "starful_biz": {
        "service_id": "starful.biz",
        "content_dir": "app/contents",
        "md_format": "starful_json",
        "name_label": "職種",
        "places_suffix": "office workplace",
        "production_default": "https://starful.biz",
        "uses_places": True,
        "prompt_editable": False,
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
}


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
    if oid.endswith(("_en", "_ko")):
        return oid.rsplit("_", 1)[0]
    return oid


def _json_row_matches_slug(row: dict[str, Any], slug: str, *, match: str) -> bool:
    rid = str(row.get("id") or "")
    thumb = str(row.get("thumbnail") or "")
    if match == "localized":
        base = _localized_base_id(rid)
        return base == slug or f"/{slug}.jpg" in thumb or f"/{slug}.png" in thumb
    if match == "exact":
        return rid == slug or f"/{slug}.jpg" in thumb or f"/{slug}.png" in thumb
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
    "okstats": {
        "service_id": "okstats",
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
