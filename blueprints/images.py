"""GCS image admin (legacy okadmin)."""
from __future__ import annotations

import io
import logging
import os
from datetime import timedelta
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request
from google.cloud import storage
from PIL import Image

from auth import requires_auth
from config import PLACES_TIMEOUT, PROTECTED_IMAGES, gcs_sites, get_service, repo_path
from starful_assets import normalize_upload, normalize_slug, sibling_blob_names

images_bp = Blueprint("images", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)

storage_client = storage.Client()
PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")


def get_site_cfg(site_id: str):
    return gcs_sites().get(site_id)


def _image_ext(image_key: str) -> str:
    return ".png" if image_key == "starful_biz" else ".jpg"


def _image_blob_name(image_key: str, slug: str, prefix: str, filename: str | None = None) -> str:
    if filename:
        return f"{prefix}{filename}"
    return f"{prefix}{slug}{_image_ext(image_key)}"


def _dedupe_image_rows(image_key: str, rows: list[dict]) -> list[dict]:
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


def _optimize_image_bytes(image_bytes: bytes, image_key: str) -> tuple[bytes, str] | tuple[None, None]:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if image_key == "starful_biz":
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            if img.width > 1200:
                ratio = 1200 / float(img.width)
                img = img.resize((1200, int(img.height * ratio)), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            img.save(output, format="PNG", optimize=True)
            return output.getvalue(), "image/png"

        img = img.convert("RGB")
        if img.width > 1200:
            ratio = 1200 / float(img.width)
            img = img.resize((1200, int(img.height * ratio)), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue(), "image/jpeg"
    except Exception:
        logger.exception("image optimize failed for %s", image_key)
        return None, None


def _purge_sibling_blobs(bucket, prefix: str, canonical_filename: str) -> None:
    for blob_name in sibling_blob_names(prefix, canonical_filename):
        blob = bucket.blob(blob_name)
        if blob.exists():
            blob.delete()
            logger.info("removed sibling GCS blob %s", blob_name)


def _write_local_starful_image(primary_name: str, payload: bytes) -> None:
    """Keep repo img/ in sync so pipeline rsync does not restore stale files."""
    svc = get_service("starful.biz")
    if not svc:
        return
    img_dir = repo_path(svc) / "app/static/img"
    img_dir.mkdir(parents=True, exist_ok=True)
    target = img_dir / primary_name
    target.write_bytes(payload)
    stem = Path(primary_name).stem
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        alt = img_dir / f"{stem}{ext}"
        if alt != target and alt.is_file():
            alt.unlink()
    legacy = stem.replace("_", "-")
    if legacy != stem:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            alt = img_dir / f"{legacy}{ext}"
            if alt.is_file():
                alt.unlink()


def _upload_image_blob(
    image_key: str,
    bucket,
    slug: str,
    prefix: str,
    image_bytes: bytes,
    *,
    filename: str | None = None,
) -> dict:
    payload, content_type = _optimize_image_bytes(image_bytes, image_key)
    if not payload:
        return {"ok": False, "error": "image processing failed"}

    targets = [normalize_upload(image_key, slug, filename)[1] or f"{slug}{_image_ext(image_key)}"]
    primary_name = targets[0]
    slug, _ = normalize_upload(image_key, slug, filename)

    try:
        for name in targets:
            blob = bucket.blob(f"{prefix}{name}")
            blob.cache_control = "no-cache, max-age=0, must-revalidate"
            blob.upload_from_string(payload, content_type=content_type)

        _purge_sibling_blobs(bucket, prefix, primary_name)
        if image_key == "starful_biz":
            _write_local_starful_image(primary_name, payload)
    except Exception as exc:
        logger.exception("GCS upload failed for %s/%s", image_key, slug)
        return {"ok": False, "error": str(exc)[:200]}

    return {"ok": True, "filename": primary_name, "url": f"https://storage.googleapis.com/{bucket.name}/{prefix}{primary_name}"}


@images_bp.route("/images/<site_id>")
@requires_auth
def api_images(site_id):
    cfg = get_site_cfg(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": "invalid site_id"}), 400
    blobs = storage_client.list_blobs(cfg["bucket"], prefix=cfg["prefix"])
    result = []
    for blob in blobs:
        fname = blob.name.replace(cfg["prefix"], "")
        if not fname or fname in PROTECTED_IMAGES or "_backup_" in fname:
            continue
        if any(fname.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            mtime = blob.updated + timedelta(hours=9)
            updated_ts = blob.updated.timestamp() if blob.updated else 0
            stem = Path(fname).stem
            norm_slug = normalize_slug(stem) if site_id == "starful_biz" else stem
            display_name = (
                f"{norm_slug}.png"
                if site_id == "starful_biz" and not stem.startswith(("favicon", "apple-touch"))
                and stem not in {"default", "default_og", "logo"}
                else fname
            )
            result.append(
                {
                    "filename": fname,
                    "display_filename": display_name,
                    "slug": norm_slug,
                    "size_kb": round(blob.size / 1024),
                    "date_str": mtime.strftime("%Y-%m-%d"),
                    "updated_ts": updated_ts,
                    "url": f"https://storage.googleapis.com/{cfg['bucket']}/{blob.name}",
                }
            )
    result = _dedupe_image_rows(site_id, result)
    if site_id == "starful_biz":
        bucket_name = cfg["bucket"]
        prefix = cfg["prefix"]
        for row in result:
            canon = row.get("display_filename") or row["filename"]
            if row["filename"] != canon:
                row["filename"] = canon
                row["url"] = f"https://storage.googleapis.com/{bucket_name}/{prefix}{canon}"
    result.sort(key=lambda x: x["slug"].lower())
    result.sort(key=lambda x: x.get("updated_ts") or 0, reverse=True)
    return jsonify(result)


@images_bp.route("/search/<site_id>/<slug>")
@requires_auth
def api_search(site_id, slug):
    cfg = get_site_cfg(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": "invalid site_id"}), 400
    if not PLACES_API_KEY:
        return jsonify({"ok": False, "error": "missing GOOGLE_PLACES_API_KEY"}), 500
    headers = {"X-Goog-Api-Key": PLACES_API_KEY, "X-Goog-FieldMask": "places.displayName,places.photos"}
    body = {
        "includedTypes": cfg["search_type"],
        "locationRestriction": {
            "circle": {
                "center": {"latitude": 35.6812, "longitude": 139.7671},
                "radius": 5000.0,
            }
        },
        "maxResultCount": 10,
        "languageCode": "ja",
    }
    try:
        res = requests.post(
            "https://places.googleapis.com/v1/places:searchNearby",
            headers=headers,
            json=body,
            timeout=PLACES_TIMEOUT,
        )
        res.raise_for_status()
    except requests.RequestException:
        return jsonify({"ok": False, "error": "places api request failed"}), 502
    places = res.json().get("places", [])
    return jsonify(
        [
            {
                "name": p.get("displayName", {}).get("text", ""),
                "photos": [ph.get("name") for ph in p.get("photos", [])[:5]],
            }
            for p in places
        ]
    )


@images_bp.route("/replace/places", methods=["POST"])
@requires_auth
def api_replace_places():
    data = request.get_json(silent=True) or {}
    site_id = data.get("site_id")
    slug = data.get("slug")
    photo_name = data.get("photo_name")
    filename = data.get("filename")
    if not site_id or not slug or not photo_name:
        return jsonify({"ok": False, "error": "missing fields"}), 400
    slug, filename = normalize_upload(site_id, slug, filename)
    cfg = get_site_cfg(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": "invalid site_id"}), 400
    if not PLACES_API_KEY:
        return jsonify({"ok": False, "error": "missing GOOGLE_PLACES_API_KEY"}), 500
    bucket = storage_client.bucket(cfg["bucket"])
    try:
        res = requests.get(
            f"https://places.googleapis.com/v1/{photo_name}/media?maxWidthPx=2000&key={PLACES_API_KEY}",
            timeout=PLACES_TIMEOUT,
        )
    except requests.RequestException:
        return jsonify({"ok": False, "error": "places image download failed"}), 502
    if res.status_code != 200:
        return jsonify({"ok": False, "error": f"places media HTTP {res.status_code}"}), 502
    out = _upload_image_blob(
        site_id, bucket, slug, cfg["prefix"], res.content, filename=filename
    )
    if out.get("ok"):
        return jsonify({**out, "site_url": f"/static/img/{out['filename']}"})
    return jsonify(out), 500


@images_bp.route("/replace/upload", methods=["POST"])
@requires_auth
def api_replace_upload():
    site_id = request.form.get("site_id")
    slug = request.form.get("slug")
    filename = request.form.get("filename")
    if not site_id or not slug:
        return jsonify({"ok": False, "error": "missing fields"}), 400
    slug, filename = normalize_upload(site_id, slug, filename)
    cfg = get_site_cfg(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": "invalid site_id"}), 400
    bucket = storage_client.bucket(cfg["bucket"])
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "missing file"}), 400
    out = _upload_image_blob(
        site_id, bucket, slug, cfg["prefix"], file.read(), filename=filename
    )
    if out.get("ok"):
        return jsonify({**out, "site_url": f"/static/img/{out['filename']}"})
    return jsonify(out), 500
