"""Render Instagram queue items to cardnews PNGs via Nano Banana 2 (+ optional reel)."""
from __future__ import annotations

import io
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PIL import Image

from config import OKADMIN_ROOT, WORK_ROOT
from instagram_prompt_queue import get_item, patch_item
from instagram_reel import build_reel, cardnews_root, ffmpeg_ready
from instagram_site_profiles import strip_slide_copy

MODEL = "gemini-3.1-flash-image"
LOGO_PATH = OKADMIN_ROOT / "static" / "instagram" / "ok-japan-logo.png"
W, H = 1080, 1350
DEFAULT_REEL_SECONDS = 2.5

_lock = threading.Lock()
# item_id -> live job snapshot (also mirrored onto queue item via patch_item)
_jobs: dict[str, dict[str, Any]] = {}


def _gemini_key() -> str:
    load_dotenv(OKADMIN_ROOT / ".env")
    load_dotenv(WORK_ROOT / "okramen" / ".env")
    return (os.environ.get("GEMINI_API_KEY") or "").strip()


def folder_name_for_topic(topic: str) -> str:
    name = (topic or "card").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "", name)
    name = re.sub(r"\s+", " ", name).strip() or "card"
    return name[:80]


def is_rendering(item_id: str) -> bool:
    with _lock:
        job = _jobs.get(item_id)
        return bool(job and job.get("status") == "running")


def list_running() -> list[dict[str, Any]]:
    with _lock:
        return [dict(j) for j in _jobs.values() if j.get("status") == "running"]


def job_status(item_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(item_id)
        if job:
            return dict(job)
    item = get_item(item_id)
    if not item:
        return None
    return {
        "item_id": item_id,
        "topic": item.get("topic"),
        "status": item.get("render_status") or "idle",
        "phase": item.get("render_phase") or "",
        "progress": item.get("render_progress") or "",
        "message": item.get("render_message") or "",
        "folder": item.get("cardnews_folder"),
        "path": item.get("cardnews_path"),
        "reel_file": item.get("reel_file"),
        "reel_download_url": item.get("reel_download_url"),
        "error": item.get("render_error"),
        "images": item.get("render_images"),
        "expected": item.get("render_expected"),
    }


def _set_job(item_id: str, **fields: Any) -> dict[str, Any]:
    with _lock:
        job = _jobs.setdefault(item_id, {"item_id": item_id, "status": "running"})
        job.update(fields)
        snap = dict(job)
    patch_fields = {
        "render_status": snap.get("status"),
        "render_phase": snap.get("phase"),
        "render_progress": snap.get("progress"),
        "render_message": snap.get("message"),
        "render_error": snap.get("error"),
        "cardnews_folder": snap.get("folder"),
        "cardnews_path": snap.get("path"),
        "reel_file": snap.get("reel_file"),
        "reel_download_url": snap.get("reel_download_url"),
        "render_images": snap.get("images"),
        "render_expected": snap.get("expected"),
    }
    patch_item(item_id, {k: v for k, v in patch_fields.items() if v is not None or k == "render_error"})
    return snap


def _build_prompt(slide: dict[str, Any], *, topic: str) -> str:
    title = strip_slide_copy(slide.get("title") or topic or "")
    body = strip_slide_copy(slide.get("body") or "")
    art = (slide.get("art") or "cute flat vector Japanese food illustration").strip()
    num = slide.get("num")

    num_line = (
        f"Small dark rounded badge with number '{num}' near the top (not overlapping logo). "
        if num
        else "No number badge. "
    )
    return (
        "Create ONE Instagram card-news image, portrait 4:5 (about 1080x1350). "
        "Pure white (#FFFFFF) background. Flat vector, cute clean Japanese food style. "
        "Bright colors, no purple, no neon, no watermark, no website URL/domain, no QR code. "
        "Outro may say profile link CTA in Korean. "
        "Korean text must be sharp, large, and perfectly readable. "
        "Do NOT draw any logo, brand mark, or empty circle placeholder in the corners. "
        "Leave plain white space at top-left for a logo to be added later. "
        "Bottom area: illustration. Top/middle: text. "
        f"{num_line}"
        f"Topic context: {topic}. "
        f"Large Korean title exactly: '{title}'. "
        f"Korean body exactly: '{body}'. "
        f"Illustration: {art}. No extra English slogans."
    )


def _generate_one(client: Any, prompt: str) -> Image.Image:
    from google.genai import types

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    parts = (response.candidates or [None])[0]
    if not parts or not parts.content:
        raise RuntimeError("빈 응답")
    for part in parts.content.parts or []:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            return Image.open(io.BytesIO(inline.data)).convert("RGBA")
    raise RuntimeError("이미지 없음")


def _fit_with_logo(img: Image.Image, logo: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (W, H), "#FFFFFF")
    fitted = img.copy()
    fitted.thumbnail((W, H), Image.Resampling.LANCZOS)
    ox = (W - fitted.width) // 2
    oy = (H - fitted.height) // 2
    if fitted.mode == "RGBA":
        canvas.paste(fitted, (ox, oy), fitted)
    else:
        canvas.paste(fitted, (ox, oy))
    logo_s = logo.copy()
    logo_s.thumbnail((96, 96), Image.Resampling.LANCZOS)
    canvas.paste(logo_s, (48, 40), logo_s)
    return canvas


def _run_job(
    item_id: str,
    *,
    force: bool,
    with_reel: bool,
    reel_seconds: float,
) -> None:
    try:
        item = get_item(item_id)
        if not item:
            _set_job(item_id, status="error", error="항목 없음", phase="error", message="항목 없음")
            return

        key = _gemini_key()
        if not key:
            _set_job(item_id, status="error", error="GEMINI_API_KEY 없음", phase="error", message="API 키 없음")
            return
        if not LOGO_PATH.is_file():
            _set_job(item_id, status="error", error=f"로고 없음: {LOGO_PATH}", phase="error", message="로고 없음")
            return

        slides = [s for s in (item.get("slides") or []) if isinstance(s, dict)]
        if not slides:
            _set_job(item_id, status="error", error="슬라이드 없음", phase="error", message="슬라이드 없음")
            return

        topic = (item.get("topic") or item_id).strip()
        folder = folder_name_for_topic(topic)
        out_dir = cardnews_root() / folder
        out_dir.mkdir(parents=True, exist_ok=True)

        _set_job(
            item_id,
            status="running",
            topic=topic,
            folder=folder,
            path=str(out_dir),
            phase="images",
            progress=f"0/{len(slides)}",
            message=f"이미지 생성 시작 · {topic}",
            expected=len(slides),
            images=0,
            error=None,
            model=MODEL,
        )

        from google import genai

        client = genai.Client(api_key=key)
        logo = Image.open(LOGO_PATH).convert("RGBA")
        paths: list[str] = []
        errors: list[str] = []

        for i, slide in enumerate(slides, start=1):
            slide_title = (slide.get("title") or topic).strip()
            _set_job(
                item_id,
                phase="images",
                progress=f"{i - 1}/{len(slides)}",
                message=f"이미지 {i}/{len(slides)} · {slide_title}",
                current_slide=i,
                current_title=slide_title,
            )
            prompt = _build_prompt(slide, topic=topic)
            last_err = None
            for attempt in range(1, 4):
                try:
                    raw = _generate_one(client, prompt)
                    card = _fit_with_logo(raw, logo)
                    path = out_dir / f"{i}.png"
                    card.save(path, "PNG", optimize=True)
                    paths.append(str(path))
                    _set_job(
                        item_id,
                        progress=f"{i}/{len(slides)}",
                        images=len(paths),
                        message=f"이미지 {i}/{len(slides)} 완료 · {slide_title}",
                    )
                    last_err = None
                    break
                except Exception as e:
                    last_err = str(e)
                    time.sleep(1.5 * attempt)
            if last_err:
                errors.append(f"{i}: {last_err}")
                _set_job(item_id, message=f"이미지 {i} 실패 · {last_err[:80]}")
            time.sleep(0.3)

        reel_info: dict[str, Any] = {}
        if with_reel and paths and ffmpeg_ready():
            _set_job(
                item_id,
                phase="reel",
                message=f"릴스 인코딩 중 · {topic}",
                progress=f"{len(paths)}/{len(slides)}",
            )
            reel = build_reel(str(out_dir), site_id="instagram", seconds=reel_seconds)
            if reel.get("ok"):
                reel_info = {
                    "reel_file": reel.get("file"),
                    "reel_download_url": reel.get("download_url"),
                    "reel_path": reel.get("path"),
                }
                _set_job(
                    item_id,
                    message=f"릴스 완료 · {reel.get('file')}",
                    **reel_info,
                )
            else:
                errors.append(f"reel: {reel.get('error') or '실패'}")
                _set_job(item_id, message=f"릴스 실패 · {reel.get('error')}")
        elif with_reel and not ffmpeg_ready():
            errors.append("reel: ffmpeg 없음")
            _set_job(item_id, message="릴스 건너뜀 · ffmpeg 없음")

        ok = len(paths) == len(slides)
        status = "done" if ok else "error"
        _set_job(
            item_id,
            status=status,
            phase="done" if status == "done" else "error",
            progress=f"{len(paths)}/{len(slides)}",
            images=len(paths),
            expected=len(slides),
            folder=folder,
            path=str(out_dir),
            error="; ".join(errors) if errors else None,
            message=(
                f"완료 · 이미지 {len(paths)}장"
                + (f" · 릴스 OK" if reel_info.get("reel_file") else "")
                + (f" · {topic}")
            ),
            **reel_info,
        )
    except Exception as e:
        _set_job(
            item_id,
            status="error",
            phase="error",
            error=str(e),
            message=f"실패 · {e}",
        )
    finally:
        # Keep last job snapshot for polling; clear "running" membership via status field.
        pass


def start_render(
    item_id: str,
    *,
    force: bool = True,
    with_reel: bool = True,
    reel_seconds: float = DEFAULT_REEL_SECONDS,
) -> dict[str, Any]:
    """Kick off background render. Returns immediately."""
    item = get_item(item_id)
    if not item:
        return {"ok": False, "error": "항목 없음"}

    with _lock:
        existing = _jobs.get(item_id)
        if existing and existing.get("status") == "running":
            return {"ok": False, "error": "이미 생성 중", "running": True, "job": dict(existing)}

    topic = (item.get("topic") or item_id).strip()
    _set_job(
        item_id,
        status="running",
        topic=topic,
        phase="queued",
        progress="0/?",
        message=f"대기열 · {topic}",
        error=None,
        folder=folder_name_for_topic(topic),
        images=0,
        expected=len(item.get("slides") or []),
        reel_file=None,
        reel_download_url=None,
    )

    t = threading.Thread(
        target=_run_job,
        kwargs={
            "item_id": item_id,
            "force": force,
            "with_reel": with_reel,
            "reel_seconds": reel_seconds,
        },
        daemon=True,
        name=f"ig-render-{item_id}",
    )
    t.start()
    return {
        "ok": True,
        "started": True,
        "item_id": item_id,
        "topic": topic,
        "with_reel": with_reel,
        "job": job_status(item_id),
    }


# Back-compat sync wrapper (tests / scripts)
def render_item(
    item_id: str,
    *,
    force: bool = False,
    with_reel: bool = True,
    reel_seconds: float = DEFAULT_REEL_SECONDS,
) -> dict[str, Any]:
    started = start_render(item_id, force=force, with_reel=with_reel, reel_seconds=reel_seconds)
    if not started.get("ok") and not started.get("running"):
        return started
    # Wait until finished
    while True:
        st = job_status(item_id) or {}
        if st.get("status") in ("done", "error"):
            return {
                "ok": st.get("status") == "done",
                "folder": st.get("folder"),
                "path": st.get("path"),
                "images": st.get("images"),
                "expected": st.get("expected"),
                "errors": [st["error"]] if st.get("error") else [],
                "model": MODEL,
                "reel_file": st.get("reel_file"),
                "reel_download_url": st.get("reel_download_url"),
                "message": st.get("message"),
            }
        time.sleep(0.5)
