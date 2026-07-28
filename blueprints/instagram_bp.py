"""Instagram prompt queue API (shared food-focused queue)."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import requires_auth
from instagram_prompt_queue import (
    DEFAULT_BATCH_SIZE,
    ensure_queue,
    enqueue_md_suggestions,
    format_caption_block,
    format_gemini_prompt,
    generate_next_batch,
    get_item,
    list_items,
    md_suggestions,
    queue_stats,
    reset_to_seed,
    set_status,
)
from instagram_site_profiles import INSTAGRAM_PROFILE, instagram_common_rules

instagram_bp = Blueprint("instagram", __name__, url_prefix="/api/instagram")


def _optional_site() -> str | None:
    """Site is optional (hub embed). Queue is always shared."""
    site_id = (request.args.get("site") or request.args.get("site_id") or "").strip()
    if not site_id:
        body = request.get_json(silent=True) or {}
        site_id = (body.get("site_id") or body.get("site") or "").strip()
    return site_id or None


@instagram_bp.route("/queue")
@requires_auth
def api_queue():
    ensure_queue()
    status = (request.args.get("status") or "").strip() or None
    category = (request.args.get("category") or "").strip() or None
    batch_raw = (request.args.get("batch") or "").strip()
    batch = int(batch_raw) if batch_raw.isdigit() else None
    items = list_items(status=status, batch=batch, category=category)
    data = ensure_queue()
    return jsonify(
        {
            "site_id": None,
            "profile": INSTAGRAM_PROFILE,
            "stats": queue_stats(data),
            "common_rules": data.get("common_rules") or instagram_common_rules(),
            "items": items,
        }
    )


@instagram_bp.route("/items/<item_id>")
@requires_auth
def api_item(item_id: str):
    item = get_item(item_id)
    if not item:
        return jsonify({"error": "not found"}), 404
    data = ensure_queue()
    return jsonify(
        {
            "item": item,
            "gemini_prompt": format_gemini_prompt(item, data.get("common_rules")),
            "caption_block": format_caption_block(item),
        }
    )


@instagram_bp.route("/items/<item_id>/status", methods=["POST"])
@requires_auth
def api_set_status(item_id: str):
    body = request.get_json(silent=True) or {}
    status = (body.get("status") or "").strip()
    try:
        item = set_status(item_id, status)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not item:
        return jsonify({"error": "not found"}), 404
    return jsonify({"item": item, "stats": queue_stats()})


@instagram_bp.route("/items/<item_id>/render", methods=["POST"])
@requires_auth
def api_render_item(item_id: str):
    """Start Nano Banana 2 render (+ auto reel) in background."""
    from instagram_card_render import start_render

    body = request.get_json(silent=True) or {}
    force = bool(body.get("force", True))
    with_reel = body.get("with_reel", True)
    if isinstance(with_reel, str):
        with_reel = with_reel.lower() not in ("0", "false", "no")
    seconds = body.get("seconds", 2.5)
    result = start_render(
        item_id,
        force=force,
        with_reel=bool(with_reel),
        reel_seconds=float(seconds) if seconds is not None else 2.5,
    )
    if result.get("error") == "항목 없음":
        return jsonify(result), 404
    if result.get("running"):
        return jsonify(result), 409
    if not result.get("ok"):
        return jsonify(result), 500
    return jsonify(result)


@instagram_bp.route("/items/<item_id>/render/status")
@requires_auth
def api_render_status(item_id: str):
    from instagram_card_render import job_status

    st = job_status(item_id)
    if not st:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "job": st})


@instagram_bp.route("/render/running")
@requires_auth
def api_render_running():
    from instagram_card_render import list_running

    return jsonify({"ok": True, "jobs": list_running()})


@instagram_bp.route("/generate", methods=["POST"])
@requires_auth
def api_generate():
    body = request.get_json(silent=True) or {}
    count = body.get("count", DEFAULT_BATCH_SIZE)
    result = generate_next_batch(count=count)
    code = 200 if result.get("ok") else 500
    return jsonify(result), code


@instagram_bp.route("/md-suggestions")
@requires_auth
def api_md_suggestions():
    return jsonify(md_suggestions())


@instagram_bp.route("/enqueue-md", methods=["POST"])
@requires_auth
def api_enqueue_md():
    body = request.get_json(silent=True) or {}
    titles = body.get("titles")
    limit = body.get("limit", 8)
    result = enqueue_md_suggestions(titles=titles, limit=limit)
    return jsonify(result)


@instagram_bp.route("/reset-seed", methods=["POST"])
@requires_auth
def api_reset_seed():
    return jsonify(reset_to_seed())


@instagram_bp.route("/reel/folders")
@requires_auth
def api_reel_folders():
    from instagram_reel import list_cardnews_folders

    data = list_cardnews_folders()
    code = 200 if data.get("ok") else 500
    return jsonify(data), code


@instagram_bp.route("/reel", methods=["POST"])
@requires_auth
def api_reel_build():
    from instagram_reel import build_reel, ffmpeg_ready

    body = request.get_json(silent=True) or {}
    folder = (body.get("folder") or body.get("path") or body.get("name") or "").strip()
    seconds = body.get("seconds", 2.5)
    site_id = _optional_site() or "instagram"
    if not folder:
        return jsonify({"ok": False, "error": "폴더를 선택하세요"}), 400
    if not ffmpeg_ready():
        return jsonify({"ok": False, "error": "ffmpeg 없음 — brew install ffmpeg"}), 503
    result = build_reel(folder, site_id=site_id, seconds=seconds)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@instagram_bp.route("/reel/download")
@requires_auth
def api_reel_download():
    from flask import send_file

    from instagram_reel import resolve_output_file

    rel = (request.args.get("file") or "").strip()
    try:
        path = resolve_output_file(rel)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return send_file(
        path,
        mimetype="video/mp4",
        as_attachment=True,
        download_name=path.name,
    )
