"""Imagen prompt resolution and generate API helpers."""

from unittest.mock import MagicMock, patch

from image_site_meta import IMAGEN_SITE_KEYS, imagen_site_config, resolve_imagen_prompt


def test_imagen_site_keys():
    assert IMAGEN_SITE_KEYS == frozenset({"statfacts", "starful_biz", "okpy"})


def test_resolve_imagen_prompt_from_md():
    meta = {"slug": "insight-1", "image_prompt": "A chart about population trends"}
    assert resolve_imagen_prompt("statfacts", "insight-1", meta) == "A chart about population trends"


def test_resolve_imagen_prompt_from_template(monkeypatch):
    monkeypatch.setattr(
        "image_site_meta.gcs_sites",
        lambda: {
            "okpy": {
                "prompt_template": "Cover art about [{slug}], no text",
            }
        },
    )
    meta = {"slug": "marimo"}
    assert resolve_imagen_prompt("okpy", "20260727064420", meta) == "Cover art about marimo, no text"


def test_imagen_site_config_statfacts():
    cfg = imagen_site_config("statfacts")
    assert cfg["aspect_ratio"] == "16:9"
    assert "Editorial infographic" in cfg["prompt_suffix"]


def test_imagen_site_config_starful():
    cfg = imagen_site_config("starful_biz")
    assert cfg["aspect_ratio"] == "4:3"
    assert cfg["output_mime_type"] == "image/png"


def test_generate_imagen_bytes_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from imagen_generate import generate_imagen_bytes

    try:
        generate_imagen_bytes("long enough prompt here")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)


def test_generate_imagen_bytes_ok(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_image = MagicMock()
    fake_image.image_bytes = b"fake-jpeg-bytes"
    fake_gen = MagicMock()
    fake_gen.image = fake_image
    fake_response = MagicMock()
    fake_response.generated_images = [fake_gen]

    with patch("google.genai.Client") as client_cls:
        client_cls.return_value.models.generate_images.return_value = fake_response
        from imagen_generate import generate_imagen_bytes

        out = generate_imagen_bytes(
            "population chart",
            aspect_ratio="16:9",
            prompt_suffix="no text",
        )
    assert out == b"fake-jpeg-bytes"
