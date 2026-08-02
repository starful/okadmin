"""Tests for Instagram Reels slideshow builder."""
from __future__ import annotations

from pathlib import Path

import pytest

import instagram_reel as ir


def _write_tiny_png(path: Path, rgb: tuple[int, int, int] = (240, 240, 240)) -> None:
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow required")
    img = Image.new("RGB", (540, 675), rgb)  # 4:5-ish
    img.save(path, "PNG")


def test_list_images_natural_sort(tmp_path: Path):
    for name in ("10.png", "2.png", "01.png", "readme.txt", ".hidden.png"):
        p = tmp_path / name
        if name.endswith(".png") and not name.startswith("."):
            _write_tiny_png(p)
        else:
            p.write_text("x", encoding="utf-8")
    names = [p.name for p in ir.list_images(tmp_path)]
    assert names == ["01.png", "2.png", "10.png"]


def test_resolve_folder_rejects_outside(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    card = tmp_path / "cardnews"
    card.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(ir, "cardnews_root", lambda: card.resolve())
    with pytest.raises(ValueError, match="cardnews|안"):
        ir.resolve_folder(str(outside))


def test_list_cardnews_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    card = tmp_path / "cardnews"
    card.mkdir()
    ready = card / "온천 매너"
    ready.mkdir()
    for i in range(3):
        _write_tiny_png(ready / f"{i+1:02d}.png")
    empty = card / "빈폴더"
    empty.mkdir()
    monkeypatch.setattr(ir, "cardnews_root", lambda: card.resolve())
    data = ir.list_cardnews_folders()
    assert data["ok"] is True
    by_name = {f["name"]: f for f in data["folders"]}
    assert by_name["온천 매너"]["ready"] is True
    assert by_name["온천 매너"]["image_count"] == 3
    assert by_name["빈폴더"]["ready"] is False


def test_resolve_output_file_blocks_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    card = tmp_path / "cardnews"
    topic = card / "온천"
    topic.mkdir(parents=True)
    good = topic / "a_reel.mp4"
    good.write_bytes(b"\x00" * 20)
    monkeypatch.setattr(ir, "cardnews_root", lambda: card.resolve())
    monkeypatch.setattr(ir, "OUT_ROOT", tmp_path / "legacy")
    assert ir.resolve_output_file("온천/a_reel.mp4") == good.resolve()
    with pytest.raises(ValueError):
        ir.resolve_output_file("../a_reel.mp4")
    with pytest.raises(ValueError):
        ir.resolve_output_file("온천/../../etc/passwd")


@pytest.mark.skipif(not ir.ffmpeg_ready(), reason="ffmpeg not installed")
def test_build_reel_mixed_png_jpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ffmpeg concat fails on mixed codecs unless we normalize frames first."""
    card = tmp_path / "cardnews"
    folder = card / "mixed"
    folder.mkdir(parents=True)
    monkeypatch.setattr(ir, "cardnews_root", lambda: card.resolve())
    _write_tiny_png(folder / "0.png", (255, 200, 200))
    from PIL import Image

    Image.new("RGB", (400, 500), (100, 180, 220)).save(folder / "1.jpeg", "JPEG", quality=85)
    Image.new("RGB", (400, 500), (220, 180, 100)).save(folder / "2.jpeg", "JPEG", quality=85)

    result = ir.build_reel(str(folder), site_id="okramen", seconds=1.0)
    assert result["ok"] is True, result.get("error")
    assert result["image_count"] == 3
    out = Path(result["path"])
    assert out.parent == folder.resolve()
    assert out.stat().st_size > 1000
    # AirDrop / iPhone: silent AAC track should be present
    import subprocess

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name",
            "-of",
            "csv=p=0",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert probe.returncode == 0, probe.stderr
    text = probe.stdout
    assert "video" in text and "h264" in text, text
    assert "audio" in text and "aac" in text, text


def test_ffmpeg_error_message_prefers_real_errors():
    stderr = """
[libx264 @ 0x1] 8x8 transform intra:32.7%
[png @ 0x2] Invalid PNG signature 0xFFD8FFE000104A46.
Conversion failed!
"""
    msg = ir._ffmpeg_error_message(stderr)
    assert "Invalid PNG" in msg or "Conversion failed" in msg
    assert "8x8 transform" not in msg
