"""GCS tab: default placeholder upload & content MD delete (always removes GCS blob)."""
from __future__ import annotations

import io
import logging
import subprocess
from pathlib import Path
from typing import Any

from google.cloud import storage
from PIL import Image

from config import WORK_ROOT, gcs_sites, get_service, repo_path, work_root_available
from image_site_meta import (
    SITE_IMAGE_META,
    _meta_slug,
    _resolve_md_slug,
)
from git_ops import git_push_repo
from starful_assets import normalize_upload, sibling_blob_names

logger = logging.getLogger(__name__)

BUILD_DATA_CMD: dict[str, list[str]] = {
    "krcampus": ["python3", "scripts/build_data.py"],
    "jpcampus": ["python3", "scripts/build_data.py"],
    "okonsen": ["python3", "script/build_data.py"],
    "okramen": ["python3", "script/build_data.py"],
    "okcaddie": ["python3", "script/build_data.py"],
    "okstats": ["python3", "script/build_data.py"],
    "starful_biz": ["python3", "scripts/build_data.py"],
}

DEFAULT_CANDIDATES = ("default.png", "default.jpg")
KRCAMPUS_PIN = {
    "school": ("pin-school.png", "default-school.png", "default.png", "default.jpg"),
    "univ": ("pin-univ.png", "default-univ.png", "default.png", "default.jpg"),
}


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


def _default_source_path(site_key: str, slug: str, repo: Path) -> Path | None:
    images_dir = _images_dir(site_key, repo)
    img_dir = repo / "app/static/img"
    candidates: list[str] = list(DEFAULT_CANDIDATES)
    if site_key == "krcampus":
        cat = "univ" if slug.startswith("univ_") else "school"
        candidates = list(KRCAMPUS_PIN.get(cat, DEFAULT_CANDIDATES))
    if site_key == "jpcampus":
        candidates = ["default-stay.png", "logo.png", "default.png", "default.jpg"]
    for name in candidates:
        for base in (images_dir, img_dir):
            path = base / name
            if path.is_file():
                return path
    return None


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


def get_default_image_payload(site_key: str, slug: str) -> dict[str, Any]:
    slug = _meta_slug(site_key, (slug or "").strip())
    if not slug or site_key not in SITE_IMAGE_META:
        return {"ok": False, "error": "invalid site or slug"}
    repo = _repo_for_site(site_key)
    if not repo:
        return {"ok": False, "error": "repo not found"}

    source = _default_source_path(site_key, slug, repo)
    if not source:
        return {"ok": False, "error": "default image not found in repo"}

    try:
        payload, content_type = _optimize_default_payload(site_key, source.read_bytes())
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
        "source": str(source.relative_to(WORK_ROOT)),
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


def delete_gcs_blobs(
    site_key: str,
    slug: str,
    *,
    client: storage.Client,
    filename: str | None = None,
) -> list[str]:
    gcs = gcs_sites().get(site_key)
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
