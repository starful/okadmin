"""GCS image admin (legacy okadmin)."""
from __future__ import annotations

import io
import os
from datetime import timedelta
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request
from google.cloud import storage
from PIL import Image

from auth import requires_auth
from config import PLACES_TIMEOUT, PROTECTED_IMAGES, gcs_sites

images_bp = Blueprint("images", __name__, url_prefix="/api")

storage_client = storage.Client()
PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")


def get_site_cfg(site_id: str):
    return gcs_sites().get(site_id)


def process_and_optimize_image(image_bytes, max_width=1200):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / float(img.width)
            img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue()
    except Exception:
        return None


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
            result.append(
                {
                    "filename": fname,
                    "slug": Path(fname).stem,
                    "size_kb": round(blob.size / 1024),
                    "date_str": mtime.strftime("%Y-%m-%d"),
                    "url": f"https://storage.googleapis.com/{cfg['bucket']}/{blob.name}",
                }
            )
    result.sort(key=lambda x: x["slug"].lower())
    result.sort(key=lambda x: x["date_str"], reverse=True)
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
    if not site_id or not slug or not photo_name:
        return jsonify({"ok": False, "error": "missing fields"}), 400
    cfg = get_site_cfg(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": "invalid site_id"}), 400
    if not PLACES_API_KEY:
        return jsonify({"ok": False, "error": "missing GOOGLE_PLACES_API_KEY"}), 500
    bucket = storage_client.bucket(cfg["bucket"])
    blob = bucket.blob(f"{cfg['prefix']}{slug}.jpg")
    try:
        res = requests.get(
            f"https://places.googleapis.com/v1/{photo_name}/media?maxWidthPx=2000&key={PLACES_API_KEY}",
            timeout=PLACES_TIMEOUT,
        )
    except requests.RequestException:
        return jsonify({"ok": False, "error": "places image download failed"}), 502
    if res.status_code == 200:
        opt = process_and_optimize_image(res.content)
        if opt:
            blob.cache_control = "no-cache, max-age=0"
            blob.upload_from_string(opt, content_type="image/jpeg")
            return jsonify({"ok": True})
    return jsonify({"ok": False})


@images_bp.route("/replace/upload", methods=["POST"])
@requires_auth
def api_replace_upload():
    site_id = request.form.get("site_id")
    slug = request.form.get("slug")
    if not site_id or not slug:
        return jsonify({"ok": False, "error": "missing fields"}), 400
    cfg = get_site_cfg(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": "invalid site_id"}), 400
    bucket = storage_client.bucket(cfg["bucket"])
    blob = bucket.blob(f"{cfg['prefix']}{slug}.jpg")
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "missing file"}), 400
    opt = process_and_optimize_image(file.read())
    if opt:
        blob.cache_control = "no-cache, max-age=0"
        blob.upload_from_string(opt, content_type="image/jpeg")
        return jsonify({"ok": True})
    return jsonify({"ok": False})
