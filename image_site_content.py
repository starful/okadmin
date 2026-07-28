"""GCS tab: default placeholder upload & content MD delete (always removes GCS blob)."""
from __future__ import annotations

import io
import logging
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

from google.cloud import storage
from PIL import Image

from config import WORK_ROOT, gcs_sites, get_service, repo_path, work_root_available
from config import PROTECTED_IMAGES
from image_site_meta import (
    SITE_IMAGE_META,
    _meta_slug,
    _resolve_md_slug,
)
from git_ops import git_push_repo
from starful_assets import normalize_slug, normalize_upload, sibling_blob_names

logger = logging.getLogger(__name__)

BUILD_DATA_CMD: dict[str, list[str]] = {
    "krcampus": ["python3", "scripts/build_data.py"],
    "jpcampus": ["python3", "scripts/build_data.py"],
    "okonsen": ["python3", "script/build_data.py"],
    "okramen": ["python3", "script/build_data.py"],
    "okcaddie": ["python3", "script/build_data.py"],
    "statfacts": ["python3", "script/build_data.py"],
    "starful_biz": ["python3", "scripts/build_data.py"],
    "krcare": ["python3", "script/build_data.py"],
}

DEFAULT_CANDIDATES = ("default.png", "default.jpg")
KRCAMPUS_PIN = {
    "school": ("pin-school.png", "default-school.png", "default.png", "default.jpg"),
    "univ": ("pin-univ.png", "default-univ.png", "default.png", "default.jpg"),
}
KRCARE_DEFAULT_CANDIDATES = ("default.jpg", "tourapi_clinic.jpg", "default.png", "logo.png")


def _repo_for_site(site_key: str) -> Path | None:
    cfg = SITE_IMAGE_META.get(site_key) or {}
    svc = get_service(cfg.get("service_id", site_key))
    if not svc or not work_root_available():
        return None
    return repo_path(svc)


def _images_dir(site_key: str, repo: Path) -> Path:
    rel = SITE_IMAGE_META.get(site_key, {}).get("local_images_dir")
    if rel:
        return repo / rel
    if site_key == "starful_biz":
        return repo / "app/static/img"
    return repo / "app/static/images"


def _content_dir(site_key: str, repo: Path) -> Path:
    rel = SITE_IMAGE_META.get(site_key, {}).get("content_dir", "app/content")
    return repo / rel


def _default_candidate_names(site_key: str, slug: str = "") -> list[str]:
    candidates: list[str] = list(DEFAULT_CANDIDATES)
    if site_key == "krcampus":
        cat = "univ" if slug.startswith("univ_") else "school"
        candidates = list(KRCAMPUS_PIN.get(cat, DEFAULT_CANDIDATES))
    elif site_key == "jpcampus":
        candidates = ["default-stay.png", "logo.png", "default.png", "default.jpg"]
    elif site_key == "statfacts":
        candidates = [
            "default.jpg",
            "default.png",
            "default-annual-billing.jpg",
            "annual-billing-default.jpg",
            "favicon-32x32.png",
        ]
    elif site_key == "krcare":
        candidates = list(KRCARE_DEFAULT_CANDIDATES)
    return candidates


def _default_source_path(site_key: str, slug: str, repo: Path, *, source: str | None = None) -> Path | None:
    images_dir = _images_dir(site_key, repo)
    img_dir = repo / "app/static/img"
    if source:
        safe = Path(source).name
        for base in (images_dir, img_dir):
            path = base / safe
            if path.is_file():
                return path
        return None
    for name in _default_candidate_names(site_key, slug):
        for base in (images_dir, img_dir):
            path = base / name
            if path.is_file():
                return path
    return None


def list_default_image_options(site_key: str, slug: str = "") -> list[dict[str, str]]:
    """Selectable default/stock images from repo (modal picker)."""
    repo = _repo_for_site(site_key)
    if not repo or site_key not in SITE_IMAGE_META:
        return []
    images_dir = _images_dir(site_key, repo)
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    def add(name: str, label: str | None = None) -> None:
        if name in seen:
            return
        if not (images_dir / name).is_file():
            return
        seen.add(name)
        out.append({"name": name, "label": label or name})

    for name in _default_candidate_names(site_key, slug):
        add(name)
    if site_key == "krcare":
        for path in sorted(images_dir.glob("clinic_*.jpg")):
            label = path.stem.replace("clinic_", "").replace("_", " ")
            add(path.name, label)
    return out


def _optimize_default_payload(site_key: str, raw: bytes) -> tuple[bytes, str]:
    if site_key == "starful_biz":
        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        if img.width > 1200:
            ratio = 1200 / float(img.width)
            img = img.resize((1200, int(img.height * ratio)), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue(), "image/png"

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    if img.width > 1200:
        ratio = 1200 / float(img.width)
        img = img.resize((1200, int(img.height * ratio)), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), "image/jpeg"


def get_default_image_payload(
    site_key: str,
    slug: str,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    slug = _meta_slug(site_key, (slug or "").strip())
    if not slug or site_key not in SITE_IMAGE_META:
        return {"ok": False, "error": "invalid site or slug"}
    repo = _repo_for_site(site_key)
    if not repo:
        return {"ok": False, "error": "repo not found"}

    source_path = _default_source_path(site_key, slug, repo, source=source)
    if not source_path:
        err = f"default image not found: {source}" if source else "default image not found in repo"
        return {"ok": False, "error": err}

    try:
        payload, content_type = _optimize_default_payload(site_key, source_path.read_bytes())
    except Exception as exc:
        return {"ok": False, "error": f"image processing failed: {exc}"}

    ext = ".png" if site_key == "starful_biz" else ".jpg"
    _, filename = normalize_upload(site_key, slug, None)
    filename = filename or f"{slug}{ext}"
    return {
        "ok": True,
        "payload": payload,
        "content_type": content_type,
        "filename": filename,
        "source": str(source_path.relative_to(WORK_ROOT)),
        "source_name": source_path.name,
    }


def list_content_md_paths(site_key: str, slug: str) -> list[str]:
    slug = _meta_slug(site_key, (slug or "").strip())
    repo = _repo_for_site(site_key)
    if not repo or site_key not in SITE_IMAGE_META:
        return []
    cfg = SITE_IMAGE_META[site_key]
    content_dir = _content_dir(site_key, repo)
    if not content_dir.is_dir():
        return []
    md_slug = _resolve_md_slug(site_key, slug, content_dir)
    paths: list[Path] = []
    fmt = cfg.get("md_format")
    if fmt == "krcampus":
        for name in (f"{md_slug}.md", f"{md_slug}_ja.md"):
            p = content_dir / name
            if p.is_file():
                paths.append(p)
    elif fmt == "starful_json":
        p = content_dir / f"{md_slug}.md"
        if p.is_file():
            paths.append(p)
    elif fmt == "okpy_post":
        from image_site_meta import _okpy_post_resolve

        _, post_path = _okpy_post_resolve(content_dir, md_slug)
        if post_path:
            paths.append(post_path)
    else:
        for lang in cfg.get("md_langs") or ("en", "ko"):
            p = content_dir / f"{md_slug}_{lang}.md"
            if p.is_file():
                paths.append(p)
    return [str(p.relative_to(WORK_ROOT)) for p in paths]


def sync_local_image(site_key: str, slug: str, payload: bytes, filename: str) -> str | None:
    repo = _repo_for_site(site_key)
    if not repo:
        return None
    dest = _images_dir(site_key, repo) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return str(dest.relative_to(WORK_ROOT))


def _gcs_blob_names(site_key: str, slug: str, filename: str | None = None) -> list[str]:
    slug, filename = normalize_upload(site_key, slug, filename)
    ext = ".png" if site_key == "starful_biz" else ".jpg"
    primary = filename or f"{slug}{ext}"
    names = [primary]
    for alt in sibling_blob_names("", primary):
        if alt not in names:
            names.append(alt)
    return names


def _gcs_cfg(site_key: str) -> dict | None:
    return gcs_sites().get(site_key)


def delete_gcs_blobs(
    site_key: str,
    slug: str,
    *,
    client: storage.Client,
    filename: str | None = None,
) -> list[str]:
    gcs = _gcs_cfg(site_key)
    if not gcs:
        return []
    bucket = client.bucket(gcs["bucket"])
    prefix = gcs.get("prefix") or ""
    deleted: list[str] = []
    for name in _gcs_blob_names(site_key, slug, filename):
        blob_path = f"{prefix}{name}"
        blob = bucket.blob(blob_path)
        if blob.exists():
            blob.delete()
            deleted.append(blob_path)
            logger.info("deleted GCS blob %s", blob_path)
        if site_key == "okpy":
            legacy_path = f"{prefix}posts/{okpy_canonical_gcs_filename(name)}"
            if legacy_path != blob_path:
                legacy = bucket.blob(legacy_path)
                if legacy.exists():
                    legacy.delete()
                    deleted.append(legacy_path)
                    logger.info("deleted legacy okpy GCS blob %s", legacy_path)
    return deleted


def delete_local_image(site_key: str, slug: str, filename: str | None = None) -> list[str]:
    repo = _repo_for_site(site_key)
    if not repo:
        return []
    removed: list[str] = []
    images_dir = _images_dir(site_key, repo)
    for name in _gcs_blob_names(site_key, slug, filename):
        path = images_dir / name
        if path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(WORK_ROOT)))
    return removed


def rebuild_site_json(site_key: str) -> dict[str, Any]:
    repo = _repo_for_site(site_key)
    cmd = BUILD_DATA_CMD.get(site_key)
    if not repo or not cmd:
        return {"ok": False, "error": "build_data not configured"}
    script = repo / cmd[-1] if cmd else None
    if not script or not script.is_file():
        return {"ok": False, "error": f"build script missing: {cmd}"}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "build_data timeout"}
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "exit_code": proc.returncode,
        "error": "" if ok else (proc.stderr or proc.stdout or "build failed")[-500:],
    }


_SKIP_IMAGE_SLUGS = frozenset({"default", "logo", "og_image", "onsen_marker", "favicon"})


def iter_content_slugs(site_key: str, repo: Path) -> set[str]:
    """Unique content slugs from MD files (for GCS placeholder sync)."""
    cfg = SITE_IMAGE_META.get(site_key)
    if not cfg:
        return set()
    content_dir = _content_dir(site_key, repo)
    if not content_dir.is_dir():
        return set()
    slugs: set[str] = set()
    fmt = cfg.get("md_format")
    if fmt == "krcampus":
        for path in content_dir.glob("*.md"):
            stem = path.stem
            if stem.endswith("_ja"):
                slugs.add(stem[:-3])
            else:
                slugs.add(stem)
    elif fmt == "jpcampus_stay":
        for path in content_dir.glob("*.md"):
            stem = path.stem
            slugs.add(stem[:-3] if stem.endswith("_kr") else stem)
    elif fmt == "starful_json":
        for path in content_dir.glob("*.md"):
            if path.name.lower() not in ("readme.md", "index.md"):
                slugs.add(path.stem)
    elif fmt == "okpy_post":
        from image_site_meta import okpy_cover_stems_from_repo

        slugs.update(okpy_cover_stems_from_repo(repo))
    else:
        langs = tuple(cfg.get("md_langs") or ("en", "ko"))
        for path in content_dir.glob("*.md"):
            stem = path.stem
            for lang in langs:
                suf = f"_{lang}"
                if stem.endswith(suf):
                    slugs.add(stem[: -len(suf)])
                    break
    return {s for s in slugs if s and s not in _SKIP_IMAGE_SLUGS}


def _service_id(site_key: str) -> str:
    return SITE_IMAGE_META.get(site_key, {}).get("service_id", site_key)


def _gcs_slug_set(site_key: str, client: storage.Client) -> set[str]:
    gcs = _gcs_cfg(site_key)
    if not gcs:
        return set()
    prefix = gcs.get("prefix") or ""
    out: set[str] = set()
    for blob in client.list_blobs(gcs["bucket"], prefix=prefix):
        fname = blob.name[len(prefix) :] if prefix else blob.name
        if not fname or fname in PROTECTED_IMAGES or "_backup_" in fname:
            continue
        lower = fname.lower()
        if not any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            continue
        stem = Path(fname).stem
        if stem and stem not in _SKIP_IMAGE_SLUGS:
            out.add(_meta_slug(site_key, stem))
    return out


def _local_image_path(site_key: str, slug: str, repo: Path) -> Path | None:
    slug = _meta_slug(site_key, slug)
    images_dir = _images_dir(site_key, repo)
    for name in _gcs_blob_names(site_key, slug, None):
        path = images_dir / name
        if path.is_file() and path.stem not in _SKIP_IMAGE_SLUGS:
            return path
    return None


def _upload_payload_to_gcs(
    site_key: str,
    slug: str,
    payload: bytes,
    content_type: str,
    filename: str,
    client: storage.Client,
) -> dict[str, Any]:
    sid = _service_id(site_key)
    gcs = _gcs_cfg(site_key)
    if not gcs:
        return {"ok": False, "error": f"no GCS config for {site_key}"}
    bucket = client.bucket(gcs["bucket"])
    prefix = gcs.get("prefix") or ""
    try:
        blob = bucket.blob(f"{prefix}{filename}")
        blob.cache_control = "no-cache, max-age=0, must-revalidate"
        blob.upload_from_string(payload, content_type=content_type)
        try:
            from image_site_meta import bump_site_thumbnail_cache

            bump_site_thumbnail_cache(site_key, slug)
        except Exception:
            pass
        return {"ok": True, "filename": filename}
    except Exception as exc:
        logger.exception("GCS upload failed for %s/%s", site_key, slug)
        return {"ok": False, "error": str(exc)[:200]}


def _default_payload_fingerprint(site_key: str, slug: str, repo: Path) -> bytes | None:
    source = _default_source_path(site_key, slug, repo)
    if not source:
        return None
    cache_key = (site_key, str(source.resolve()))
    cached = getattr(_default_payload_fingerprint, "_cache", None)
    if cached is None:
        cached = {}
        setattr(_default_payload_fingerprint, "_cache", cached)
    if cache_key in cached:
        return cached[cache_key]
    try:
        payload, _ = _optimize_default_payload(site_key, source.read_bytes())
    except Exception:
        cached[cache_key] = None
        return None
    cached[cache_key] = payload
    return payload

def okpy_canonical_gcs_filename(fname: str) -> str:
    """GCS object name under okpy/ prefix — strip legacy posts/ subfolder."""
    name = (fname or "").replace("\\", "/").lstrip("/")
    if name.startswith("posts/"):
        name = name[len("posts/") :]
    return name


def _okpy_row_score(row: dict) -> tuple[float, int]:
    fn = (row.get("filename") or "").replace("\\", "/")
    at_root = 1 if not fn.startswith("posts/") else 0
    return float(row.get("updated_ts") or 0), at_root


def _normalize_okpy_gcs_row(row: dict, *, bucket_name: str, prefix: str) -> dict:
    raw_fn = (row.get("filename") or "").replace("\\", "/")
    canon = okpy_canonical_gcs_filename(raw_fn)
    stem = Path(canon).stem
    out = {
        **row,
        "slug": stem,
        "display_filename": canon,
    }
    if raw_fn.startswith("posts/"):
        out["filename"] = raw_fn
        out["url"] = row.get("url") or ""
    else:
        out["filename"] = canon
        if canon and bucket_name:
            out["url"] = f"https://storage.googleapis.com/{bucket_name}/{prefix}{canon}"
    return out


def _dedupe_gcs_image_rows(
    image_key: str,
    rows: list[dict],
    *,
    bucket_name: str = "",
    prefix: str = "",
) -> list[dict]:
    if image_key == "okpy":
        by_slug: dict[str, dict] = {}
        for row in rows:
            canon = okpy_canonical_gcs_filename(row.get("filename") or "")
            stem = Path(canon).stem
            if not stem:
                continue
            normalized = _normalize_okpy_gcs_row(
                row, bucket_name=bucket_name, prefix=prefix
            )
            prev = by_slug.get(stem)
            if not prev or _okpy_row_score(normalized) >= _okpy_row_score(prev):
                by_slug[stem] = normalized
        return list(by_slug.values())

    if image_key != "starful_biz":
        return rows
    by_slug: dict[str, dict] = {}

    def _score(row: dict) -> tuple[float, int]:
        ext = Path(row["filename"]).suffix.lower()
        pref = 2 if ext == ".png" else 1 if ext in (".jpg", ".jpeg") else 0
        return float(row.get("updated_ts") or 0), pref

    for row in rows:
        slug = row["slug"]
        prev = by_slug.get(slug)
        if not prev or _score(row) >= _score(prev):
            by_slug[slug] = row
    return list(by_slug.values())


def _gcs_rows_from_blobs(site_id: str, cfg: dict[str, Any], blobs) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    prefix = cfg["prefix"]
    bucket_name = cfg["bucket"]
    for blob in blobs:
        fname = blob.name.replace(prefix, "")
        if not fname or fname in PROTECTED_IMAGES or "_backup_" in fname:
            continue
        if not any(fname.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            continue
        updated_ts = blob.updated.timestamp() if blob.updated else 0
        mtime = (blob.updated + timedelta(hours=9)) if blob.updated else None
        canon_fname = okpy_canonical_gcs_filename(fname) if site_id == "okpy" else fname
        stem = Path(canon_fname).stem
        norm_slug = normalize_slug(stem) if site_id == "starful_biz" else stem
        display_name = (
            f"{norm_slug}.png"
            if site_id == "starful_biz"
            and not stem.startswith(("favicon", "apple-touch"))
            and stem not in {"default", "default_og", "logo"}
            else (canon_fname if site_id == "okpy" else fname)
        )
        result.append(
            {
                "filename": fname,
                "display_filename": display_name,
                "slug": norm_slug,
                "size_kb": round(blob.size / 1024),
                "date_str": mtime.strftime("%Y-%m-%d") if mtime else "unknown",
                "updated_ts": updated_ts,
                "url": f"https://storage.googleapis.com/{bucket_name}/{blob.name}",
            }
        )
    result = _dedupe_gcs_image_rows(
        site_id, result, bucket_name=bucket_name, prefix=prefix
    )
    if site_id == "starful_biz":
        for row in result:
            canon = row.get("display_filename") or row["filename"]
            if row["filename"] != canon:
                row["filename"] = canon
                row["url"] = f"https://storage.googleapis.com/{bucket_name}/{prefix}{canon}"
    return result


def _sort_image_list_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(key=lambda x: (x.get("slug") or "").lower())
    rows.sort(key=lambda x: x.get("updated_ts") or 0, reverse=True)
    rows.sort(key=lambda x: x.get("date_str") or "", reverse=True)
    return rows


def build_site_image_list(site_id: str, client: storage.Client, *, fast_list: bool = True) -> dict[str, Any]:
    """Build full image tab payload for one GCS site."""
    cfg = gcs_sites().get(site_id)
    if not cfg:
        return {"ok": False, "error": "invalid site_id"}
    blobs = client.list_blobs(cfg["bucket"], prefix=cfg["prefix"])
    result = _gcs_rows_from_blobs(site_id, cfg, blobs)
    result = _sort_image_list_rows(result)
    summary = {"content": 0, "missing": 0, "default": 0, "ok": 0, "gcs_only": 0}
    if site_id in SITE_IMAGE_META and work_root_available():
        try:
            result, summary = build_image_coverage(site_id, result, fast_list=fast_list)
        except Exception:
            logger.exception("image coverage merge failed for %s", site_id)
            if site_id in SITE_IMAGE_META:
                from image_site_meta import enrich_site_image_rows

                result = enrich_site_image_rows(site_id, result)
    elif site_id in SITE_IMAGE_META:
        from image_site_meta import enrich_site_image_rows

        result = enrich_site_image_rows(site_id, result)
    result = _sort_image_list_rows(result)
    result.sort(key=lambda x: 0 if x.get("image_status") == "missing" else 1)
    return {"ok": True, "images": result, "summary": summary}


def classify_image_status(site_key: str, slug: str, repo: Path | None, *, has_gcs: bool) -> str:
    """Return missing | default | ok for UI badges."""
    if not has_gcs:
        return "missing"
    if not repo:
        return "ok"
    local = _local_image_path(site_key, slug, repo)
    if not local:
        return "ok"
    fp = _default_payload_fingerprint(site_key, slug, repo)
    if not fp:
        return "ok"
    try:
        local_payload, _ = _optimize_default_payload(site_key, local.read_bytes())
    except Exception:
        return "ok"
    return "default" if local_payload == fp else "ok"


def build_image_coverage(
    site_key: str,
    gcs_rows: list[dict[str, Any]],
    *,
    fast_list: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Merge GCS rows with content MD slugs; tag image_status + summary counts."""
    from config import image_site_key as _isk

    key = _isk(site_key) if site_key == "starful.biz" else site_key
    # API already uses starful_biz / okramen keys matching SITE_IMAGE_META.
    if site_key in SITE_IMAGE_META:
        key = site_key

    repo = _repo_for_site(key) if key in SITE_IMAGE_META else None
    content_slugs = iter_content_slugs(key, repo) if repo else set()

    by_slug: dict[str, dict[str, Any]] = {}
    for row in gcs_rows:
        slug = (row.get("slug") or "").strip()
        if not slug or slug in _SKIP_IMAGE_SLUGS:
            row = {**row, "image_status": row.get("image_status") or "ok", "has_content": False}
            by_slug[slug or row.get("filename") or id(row)] = row
            continue
        has = slug in content_slugs
        if fast_list:
            status = "ok" if has_gcs else "missing"
        else:
            status = classify_image_status(key, slug, repo, has_gcs=True) if key in SITE_IMAGE_META else "ok"
        enriched = {
            **row,
            "image_status": status,
            "has_content": has,
        }
        # Prefer content-linked row if duplicate
        prev = by_slug.get(slug)
        if not prev or (has and not prev.get("has_content")):
            by_slug[slug] = enriched

    for slug in sorted(content_slugs):
        if slug in by_slug:
            by_slug[slug]["has_content"] = True
            continue
        by_slug[slug] = {
            "slug": slug,
            "filename": "",
            "display_filename": f"{slug} · 없음",
            "size_kb": 0,
            "date_str": "missing",
            "updated_ts": 0,
            "url": "",
            "name": "",
            "address": "",
            "features": "",
            "image_status": "missing",
            "has_content": True,
        }

    rows = list(by_slug.values())
    # Enrich names for meta sites (including missing placeholders).
    if key in SITE_IMAGE_META:
        from image_site_meta import enrich_site_image_rows

        rows = enrich_site_image_rows(key, rows)

    summary = {
        "content": len(content_slugs),
        "missing": 0,
        "default": 0,
        "ok": 0,
        "gcs_only": 0,
    }
    for row in rows:
        st = row.get("image_status") or "ok"
        if not row.get("has_content"):
            summary["gcs_only"] += 1
            continue
        if st == "missing":
            summary["missing"] += 1
        elif st == "default":
            summary["default"] += 1
        else:
            summary["ok"] += 1

    return rows, summary


def ensure_gcs_image_for_slug(
    site_key: str,
    slug: str,
    repo: Path,
    *,
    client: storage.Client,
    on_gcs: set[str],
) -> dict[str, Any]:
    """Upload local image or default placeholder when slug is missing on GCS."""
    slug = _meta_slug(site_key, (slug or "").strip())
    if not slug or slug in _SKIP_IMAGE_SLUGS:
        return {"ok": True, "action": "skip", "reason": "invalid slug"}
    if slug in on_gcs:
        return {"ok": True, "action": "skip", "reason": "already on GCS"}

    local = _local_image_path(site_key, slug, repo)
    if local:
        try:
            payload, content_type = _optimize_default_payload(site_key, local.read_bytes())
        except Exception as exc:
            return {"ok": False, "action": "failed", "error": str(exc)}
        _, filename = normalize_upload(site_key, slug, local.name)
        up = _upload_payload_to_gcs(site_key, slug, payload, content_type, filename, client)
        if not up.get("ok"):
            return {"ok": False, "action": "failed", "error": up.get("error")}
        on_gcs.add(slug)
        return {"ok": True, "action": "uploaded_local", "slug": slug, "filename": filename}

    prep = get_default_image_payload(site_key, slug)
    if not prep.get("ok"):
        return {"ok": False, "action": "failed", "error": prep.get("error")}
    up = _upload_payload_to_gcs(
        site_key,
        slug,
        prep["payload"],
        prep["content_type"],
        prep["filename"],
        client,
    )
    if not up.get("ok"):
        return {"ok": False, "action": "failed", "error": up.get("error")}
    sync_local_image(site_key, slug, prep["payload"], prep["filename"])
    on_gcs.add(slug)
    return {
        "ok": True,
        "action": "uploaded_default",
        "slug": slug,
        "filename": prep["filename"],
        "source": prep.get("source"),
    }


def upload_default_gcs_placeholders(site_id: str, repo: Path, logf) -> dict[str, Any]:
    """After content-only runs: ensure GCS has placeholder (or local) images for MD slugs."""
    from config import image_site_key

    site_key = image_site_key(site_id)
    if site_key not in SITE_IMAGE_META:
        return {"ok": True, "label": "default GCS", "skipped": True, "reason": "unsupported site"}
    if not gcs_sites().get(site_id):
        return {"ok": True, "label": "default GCS", "skipped": True, "reason": "no GCS bucket"}

    slugs = sorted(iter_content_slugs(site_key, repo))
    if not slugs:
        logf.write("[default_gcs] no content slugs\n")
        logf.flush()
        return {"ok": True, "label": "default GCS", "uploaded": 0, "skipped": 0}

    logf.write(f"\n{'=' * 50}\n[default_gcs] {site_id}: {len(slugs)} MD slugs\n")
    logf.flush()
    client = storage.Client()
    on_gcs = _gcs_slug_set(site_key, client)
    uploaded_default = uploaded_local = skipped = failed = 0
    errors: list[str] = []

    for slug in slugs:
        r = ensure_gcs_image_for_slug(site_key, slug, repo, client=client, on_gcs=on_gcs)
        action = r.get("action")
        if action == "skip":
            skipped += 1
            continue
        if action == "uploaded_default":
            uploaded_default += 1
            logf.write(f"  default → GCS: {slug}\n")
        elif action == "uploaded_local":
            uploaded_local += 1
            logf.write(f"  local → GCS: {slug}\n")
        else:
            failed += 1
            err = r.get("error") or "unknown"
            errors.append(f"{slug}: {err}")
            logf.write(f"  FAIL {slug}: {err}\n")
        logf.flush()

    uploaded = uploaded_default + uploaded_local
    summary = (
        f"[default_gcs] done: uploaded={uploaded} "
        f"(default={uploaded_default}, local={uploaded_local}) "
        f"skipped={skipped} failed={failed}\n"
    )
    logf.write(summary)
    logf.flush()
    return {
        "ok": failed == 0,
        "label": "default GCS",
        "uploaded": uploaded,
        "uploaded_default": uploaded_default,
        "uploaded_local": uploaded_local,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:20],
    }


def delete_site_content(site_key: str, slug: str, *, client: storage.Client) -> dict[str, Any]:
    slug = _meta_slug(site_key, (slug or "").strip())
    if not slug or site_key not in SITE_IMAGE_META:
        return {"ok": False, "error": "invalid site or slug"}
    repo = _repo_for_site(site_key)
    if not repo:
        return {"ok": False, "error": "repo not found"}

    md_paths = list_content_md_paths(site_key, slug)
    if not md_paths:
        return {"ok": False, "error": f"no MD files for slug: {slug}"}

    deleted_md: list[str] = []
    for rel in md_paths:
        path = WORK_ROOT / rel
        if path.is_file():
            path.unlink()
            deleted_md.append(rel)

    deleted_gcs = delete_gcs_blobs(site_key, slug, client=client)
    deleted_local = delete_local_image(site_key, slug)
    build = rebuild_site_json(site_key)

    if not deleted_md:
        return {"ok": False, "error": "MD delete failed"}

    git_id = SITE_IMAGE_META[site_key].get("service_id", site_key)
    push = git_push_repo(
        repo,
        site_id=git_id,
        message=f"chore: remove {slug} content",
    )

    out: dict[str, Any] = {
        "ok": True,
        "slug": slug,
        "deleted_md": deleted_md,
        "deleted_gcs": deleted_gcs,
        "deleted_local_images": deleted_local,
        "build_data": build,
        "git_push": push,
    }
    warnings: list[str] = []
    if not build.get("ok"):
        warnings.append(f"build_data failed: {build.get('error', '')}")
    if not push.get("ok"):
        warnings.append(f"git push failed: {push.get('error', '')}")
    if warnings:
        out["warning"] = "MD/GCS deleted but " + "; ".join(warnings)
    return out


def delete_gcs_image(
    site_key: str,
    slug: str,
    *,
    client: storage.Client,
    filename: str | None = None,
) -> dict[str, Any]:
    """Remove GCS blob (+ local copy) when there is no MD to delete."""
    slug = _meta_slug(site_key, (slug or "").strip())
    if not slug or site_key not in SITE_IMAGE_META:
        return {"ok": False, "error": "invalid site or slug"}
    if slug in _SKIP_IMAGE_SLUGS:
        return {"ok": False, "error": f"protected slug: {slug}"}

    md_paths = list_content_md_paths(site_key, slug)
    if md_paths:
        return {"ok": False, "error": "MD exists — use delete-content instead"}

    deleted_gcs = delete_gcs_blobs(site_key, slug, client=client, filename=filename)
    deleted_local = delete_local_image(site_key, slug, filename=filename)
    if not deleted_gcs and not deleted_local:
        return {"ok": False, "error": "nothing to delete on GCS or local"}

    return {
        "ok": True,
        "slug": slug,
        "deleted_gcs": deleted_gcs,
        "deleted_local_images": deleted_local,
    }
