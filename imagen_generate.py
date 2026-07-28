"""Google Imagen image generation (GEMINI_API_KEY)."""
from __future__ import annotations

import os

DEFAULT_MODEL = os.environ.get("IMAGEN_MODEL", "imagen-4.0-fast-generate-001")


def generate_imagen_bytes(
    prompt: str,
    *,
    aspect_ratio: str = "16:9",
    output_mime_type: str = "image/jpeg",
    prompt_suffix: str = "",
    person_generation: str = "allow_adult",
) -> bytes:
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing")

    full_prompt = f"{prompt} {prompt_suffix}".strip() if prompt_suffix else prompt.strip()
    if len(full_prompt) < 10:
        raise RuntimeError("prompt too short")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_images(
        model=DEFAULT_MODEL,
        prompt=full_prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect_ratio,
            output_mime_type=output_mime_type,
            person_generation=person_generation,
        ),
    )
    if not response.generated_images:
        raise RuntimeError("Imagen returned no image")

    raw = response.generated_images[0].image.image_bytes
    if not raw:
        raise RuntimeError("Imagen returned empty image")
    return raw
