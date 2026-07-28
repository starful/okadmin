#!/usr/bin/env python3
"""One-shot Instagram card sample: Imagen art + Pillow text/logo composite.

Usage:
  cd /opt/work/okadmin && python3 scripts/instagram_card_sample.py
"""
from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

OKADMIN = Path(__file__).resolve().parents[1]
WORK_ROOT = Path(os.environ.get("WORK_ROOT", "/opt/work"))
LOGO_PATH = OKADMIN / "static" / "instagram" / "ok-japan-logo.png"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")

W, H = 1080, 1350  # Instagram 4:5
TOP_H = int(H * 0.55)  # text zone
ART_H = H - TOP_H

# Food-focused sample (7 slides = cover + 5 points + outro)
SAMPLE = {
    "folder": "하라미vs갈비_샘플",
    "topic": "하라미 vs 갈비, 뭐가 달라?",
    "slides": [
        {
            "kind": "cover",
            "title": "하라미 vs 갈비",
            "body": "야키니쿠 메뉴판에서 제일 헷갈리는 두 부위",
            "art": "flat vector cute illustration of grilled yakiniku beef cuts on white plate, "
            "simple clean icons, bright colors, no text, no watermark",
        },
        {
            "kind": "point",
            "num": "01",
            "title": "갈비는 갈비뼈 근처",
            "body": "뼈에 붙은 살. 한국식 갈비와 느낌이 비슷하고 씹는 맛이 있어요.",
            "art": "flat vector cute illustration of short rib beef cut near bone, "
            "simple food icon style, white background, no text",
        },
        {
            "kind": "point",
            "num": "02",
            "title": "하라미는 횡격막살",
            "body": "갈비와 다른 부위. 얇고 결이 있어 부드럽고 육즙이 좋아요.",
            "art": "flat vector cute illustration of skirt steak harami beef, "
            "thin grilled strips, simple icon style, no text",
        },
        {
            "kind": "point",
            "num": "03",
            "title": "식감 차이",
            "body": "갈비=씹는 맛·진한 육향. 하라미=부드럽고 고소한 편.",
            "art": "flat vector cute illustration comparing chewy vs tender beef texture, "
            "two small plates, simple icons, no text",
        },
        {
            "kind": "point",
            "num": "04",
            "title": "초보 추천",
            "body": "처음이면 하라미부터. 질기지 않고 실패가 적어요.",
            "art": "flat vector cute illustration of beginner pointing at yakiniku menu, "
            "friendly travel food scene, no text",
        },
        {
            "kind": "point",
            "num": "05",
            "title": "메뉴판 표기",
            "body": "ハラミ / カルビ. 영어는 skirt / short rib로 나오기도 해요.",
            "art": "flat vector cute illustration of Japanese yakiniku menu board icons, "
            "simple chalkboard style without readable letters, no text",
        },
        {
            "kind": "outro",
            "title": "저장해두고 시키세요",
            "body": "메뉴판 앞에서 다시 열어보면 편해요",
            "art": "flat vector cute illustration of happy toast at yakiniku table, "
            "grilled meat plates, bright colors, no text, no watermark, no URL",
        },
    ],
}


def _load_env() -> str:
    load_dotenv(OKADMIN / ".env")
    load_dotenv(WORK_ROOT / "okramen" / ".env")
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise SystemExit("GEMINI_API_KEY missing")
    return key


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=size, index=0)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        cur = ""
        for ch in paragraph:
            trial = cur + ch
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines or [""]


def generate_art(api_key: str, prompt: str) -> Image.Image:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    enhanced = (
        f"{prompt}. Flat vector illustration, cute clean Japanese food card-news style, "
        "pure white background, bright diverse colors, no purple neon, no watermark, "
        "no logos, no letters, no Korean or Japanese characters."
    )
    response = client.models.generate_images(
        model="imagen-4.0-fast-generate-001",
        prompt=enhanced,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="3:4",
            output_mime_type="image/png",
            person_generation="dont_allow",
        ),
    )
    if not response.generated_images:
        raise RuntimeError("Imagen returned no image")
    raw = response.generated_images[0].image.image_bytes
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def compose_card(
    *,
    title: str,
    body: str,
    art: Image.Image,
    num: str | None,
    logo: Image.Image,
) -> Image.Image:
    canvas = Image.new("RGB", (W, H), "#FFFFFF")
    draw = ImageDraw.Draw(canvas)

    # Logo top-left
    logo_s = logo.copy()
    logo_s.thumbnail((96, 96), Image.Resampling.LANCZOS)
    canvas.paste(logo_s, (48, 40), logo_s if logo_s.mode == "RGBA" else None)

    # Number badge
    y = 160
    if num:
        badge_font = _font(28)
        label = num
        bw = int(draw.textlength(label, font=badge_font)) + 28
        draw.rounded_rectangle((48, y, 48 + bw, y + 44), radius=22, fill="#1a1a1a")
        draw.text((48 + 14, y + 6), label, font=badge_font, fill="#FFFFFF")
        y += 64
    else:
        y = 150

    title_font = _font(54 if len(title) < 16 else 44)
    body_font = _font(32)
    max_w = W - 96

    for line in _wrap(draw, title, title_font, max_w):
        draw.text((48, y), line, font=title_font, fill="#111111")
        y += int(title_font.size * 1.25)
    y += 16
    for line in _wrap(draw, body, body_font, max_w):
        draw.text((48, y), line, font=body_font, fill="#444444")
        y += int(body_font.size * 1.35)

    # Art into bottom area (contain)
    art_box = Image.new("RGB", (W - 64, ART_H - 48), "#FFFFFF")
    art_r = art.copy()
    art_r.thumbnail((art_box.width, art_box.height), Image.Resampling.LANCZOS)
    ox = (art_box.width - art_r.width) // 2
    oy = (art_box.height - art_r.height) // 2
    if art_r.mode == "RGBA":
        art_box.paste(art_r, (ox, oy), art_r)
    else:
        art_box.paste(art_r, (ox, oy))
    canvas.paste(art_box, (32, TOP_H + 16))
    return canvas


def main() -> int:
    api_key = _load_env()
    if not LOGO_PATH.is_file():
        print(f"❌ logo missing: {LOGO_PATH}")
        return 1
    logo = Image.open(LOGO_PATH).convert("RGBA")

    out_dir = WORK_ROOT / "cardnews" / SAMPLE["folder"]
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 {out_dir}")
    print(f"📌 {SAMPLE['topic']} — {len(SAMPLE['slides'])} slides\n")

    ok = 0
    for i, slide in enumerate(SAMPLE["slides"], start=1):
        print(f"[{i}/{len(SAMPLE['slides'])}] {slide['title']} …", flush=True)
        try:
            art = generate_art(api_key, slide["art"])
            card = compose_card(
                title=slide["title"],
                body=slide["body"],
                art=art,
                num=slide.get("num"),
                logo=logo,
            )
            path = out_dir / f"{i}.png"
            card.save(path, "PNG", optimize=True)
            print(f"  ✅ {path.name} ({path.stat().st_size // 1024}KB)")
            ok += 1
        except Exception as e:
            print(f"  ❌ {e}")
            return 1

    print(f"\n🎉 done: {ok}/{len(SAMPLE['slides'])} → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
