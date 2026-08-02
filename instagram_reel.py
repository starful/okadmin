"""Build Instagram Reels slideshow MP4 from a local image folder (ffmpeg)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from config import OKADMIN_ROOT, WORK_ROOT

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGES = 20
MIN_IMAGES = 2
DEFAULT_SECONDS = 2.5
MIN_SECONDS = 1.0
MAX_SECONDS = 8.0
WIDTH = 1080
HEIGHT = 1920  # 9:16 Reels
PAD_COLOR = "white"

OUT_ROOT = OKADMIN_ROOT / "data" / "instagram_reels"  # legacy; new reels go under cardnews/


def cardnews_root() -> Path:
    env = (os.environ.get("CARDNEWS_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (WORK_ROOT / "cardnews").resolve()


def ffmpeg_bin() -> str:
    env = (os.environ.get("FFMPEG_BIN") or "").strip()
    if env and Path(env).is_file():
        return env
    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


def ffmpeg_ready() -> bool:
    try:
        proc = subprocess.run(
            [ffmpeg_bin(), "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _allowed_roots() -> list[Path]:
    """Reels folders must live under work/cardnews (or CARDNEWS_ROOT)."""
    return [cardnews_root()]


def list_cardnews_folders() -> dict[str, Any]:
    """Immediate subfolders of cardnews with image counts (for UI select)."""
    root = cardnews_root()
    if not root.is_dir():
        return {
            "ok": True,
            "root": str(root),
            "folders": [],
            "note": f"폴더 없음 — {root} 를 만들어 카드뉴스를 넣으세요",
        }
    folders: list[dict[str, Any]] = []
    try:
        children = sorted(
            [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=lambda p: p.name.lower(),
        )
    except OSError as exc:
        return {"ok": False, "root": str(root), "folders": [], "error": str(exc)}

    for child in children:
        images = list_images(child)
        folders.append(
            {
                "name": child.name,
                "path": str(child.resolve()),
                "image_count": len(images),
                "ready": len(images) >= MIN_IMAGES,
            }
        )
    return {"ok": True, "root": str(root), "folders": folders}


def resolve_folder(folder: str) -> Path:
    """Resolve and validate folder is under cardnews root."""
    raw = (folder or "").strip()
    if not raw:
        raise ValueError("폴더를 선택하세요")
    root = cardnews_root()

    path = Path(raw).expanduser()
    # Allow selecting by leaf name relative to cardnews
    if not path.is_absolute():
        path = root / raw

    resolved: Path | None = None
    try:
        if path.exists() and path.is_dir():
            resolved = path.resolve()
    except OSError:
        resolved = None

    # Trailing-space / Unicode-normalization mismatches: match by leaf name
    if resolved is None or not resolved.is_dir():
        leaf = Path(raw).name.strip()
        if root.is_dir() and leaf:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if child.name == leaf or child.name.strip() == leaf:
                    resolved = child.resolve()
                    break

    if resolved is None or not resolved.is_dir():
        raise ValueError(f"폴더를 찾을 수 없습니다: {raw}")

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{root} 안의 폴더만 사용할 수 있습니다") from exc
    return resolved


def list_images(folder: Path) -> list[Path]:
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
    ]

    def sort_key(p: Path) -> tuple:
        stem = p.stem
        m = re.match(r"^(\d+)", stem)
        if m:
            return (0, int(m.group(1)), stem.lower())
        return (1, 0, stem.lower())

    files.sort(key=sort_key)
    return files


def _materialize_rgb_pngs(images: list[Path], dest_dir: Path) -> list[Path]:
    """Normalize mixed PNG/JPEG/WebP (and RGBA) into sequential RGB PNGs."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow 필요 — pip install Pillow") from exc

    out: list[Path] = []
    dest_dir.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(images):
        dest = dest_dir / f"frame_{i:03d}.png"
        with Image.open(src) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                background.save(dest, "PNG", optimize=True)
            else:
                img.convert("RGB").save(dest, "PNG", optimize=True)
        out.append(dest)
    return out


def _ffmpeg_error_message(stderr: str, stdout: str = "") -> str:
    text = (stderr or "") + "\n" + (stdout or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    interesting = [
        ln
        for ln in lines
        if any(
            k in ln.lower()
            for k in (
                "error",
                "invalid",
                "failed",
                "does not",
                "no such",
                "conversion failed",
                "could not",
            )
        )
    ]
    if interesting:
        return " · ".join(interesting[-4:])[:400]
    return ("\n".join(lines[-6:]) if lines else "unknown")[:400]


def build_reel(
    folder: str,
    *,
    site_id: str | None = None,
    seconds: float = DEFAULT_SECONDS,
    pad_color: str = PAD_COLOR,
) -> dict[str, Any]:
    """Create 9:16 slideshow MP4 from images in folder."""
    if not ffmpeg_ready():
        return {"ok": False, "error": "ffmpeg 없음 — brew install ffmpeg"}

    try:
        sec = float(seconds)
    except (TypeError, ValueError):
        sec = DEFAULT_SECONDS
    sec = max(MIN_SECONDS, min(MAX_SECONDS, sec))

    try:
        folder_path = resolve_folder(folder)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    images = list_images(folder_path)
    if len(images) < MIN_IMAGES:
        return {
            "ok": False,
            "error": f"이미지가 {MIN_IMAGES}장 이상 필요합니다 (png/jpg/webp, 현재 {len(images)}장)",
        }
    if len(images) > MAX_IMAGES:
        images = images[:MAX_IMAGES]

    sid = re.sub(r"[^a-zA-Z0-9._-]+", "_", (site_id or "reel").strip()) or "reel"
    # Save next to the card images: work/cardnews/<topic>/<stamp>_reel.mp4
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_name = f"{stamp}_reel.mp4"
    out_path = folder_path / out_name

    color = re.sub(r"[^a-zA-Z0-9#]", "", pad_color or PAD_COLOR) or PAD_COLOR
    # Image sequence (-framerate 1/sec) avoids concat demuxer's leading black frame.
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color={color},"
        f"setsar=1,format=yuv420p"
    )
    # Rational input rate so each still is held exactly `sec` seconds
    fr_num, fr_den = 1000, max(1, int(round(sec * 1000)))

    with tempfile.TemporaryDirectory(prefix="okadmin-reel-") as tmp:
        tmp_path = Path(tmp)
        try:
            frames = _materialize_rgb_pngs(images, tmp_path / "frames")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"이미지 변환 실패: {exc}"}

        pattern = str(tmp_path / "frames" / "frame_%03d.png")
        # Silent AAC track: video-only MP4s often fail AirDrop / iPhone receive.
        cmd = [
            ffmpeg_bin(),
            "-y",
            "-framerate",
            f"{fr_num}/{fr_den}",
            "-start_number",
            "0",
            "-i",
            pattern,
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            vf,
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "ffmpeg 타임아웃 (180초)"}
        except OSError as exc:
            return {"ok": False, "error": f"ffmpeg 실행 실패: {exc}"}

        if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size < 1000:
            if out_path.is_file():
                try:
                    out_path.unlink()
                except OSError:
                    pass
            msg = _ffmpeg_error_message(proc.stderr or "", proc.stdout or "")
            return {"ok": False, "error": f"ffmpeg 실패: {msg}"}

    duration = round(len(images) * sec, 1)
    try:
        rel = str(out_path.relative_to(cardnews_root()))
    except ValueError:
        rel = out_name
    return {
        "ok": True,
        "site_id": sid,
        "folder": str(folder_path),
        "images": [p.name for p in images],
        "image_count": len(images),
        "seconds_per_slide": sec,
        "duration_sec": duration,
        "width": WIDTH,
        "height": HEIGHT,
        "file": rel,
        "path": str(out_path),
        "download_url": f"/api/instagram/reel/download?file={rel}",
        "size_bytes": out_path.stat().st_size,
    }


def resolve_output_file(rel: str) -> Path:
    """Validate download relative path under cardnews root (or legacy OUT_ROOT)."""
    raw = (rel or "").strip().lstrip("/")
    if not raw or ".." in Path(raw).parts:
        raise ValueError("잘못된 파일")

    # Prefer cardnews (current)
    root = cardnews_root()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
        if path.is_file() and path.suffix.lower() == ".mp4":
            return path
    except ValueError:
        pass

    # Legacy: data/instagram_reels/
    legacy = (OUT_ROOT / raw).resolve()
    try:
        legacy.relative_to(OUT_ROOT.resolve())
        if legacy.is_file() and legacy.suffix.lower() == ".mp4":
            return legacy
    except ValueError:
        pass

    raise ValueError("파일을 찾을 수 없습니다")
