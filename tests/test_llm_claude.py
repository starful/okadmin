"""llm_claude model-tier helpers."""
from __future__ import annotations

import llm_claude as lc


def test_model_tier_defaults():
    assert lc.MODEL_LIGHT == "haiku"
    assert lc.MODEL_HEAVY == "sonnet"


def test_claude_text_passes_model(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class P:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return P()

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    out = lc.claude_text("hi", model=lc.MODEL_HEAVY)
    assert out == "ok"
    assert "--model" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "sonnet"


def test_claude_json_defaults_to_light(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class P:
            returncode = 0
            stdout = '{"a": 1}'
            stderr = ""

        return P()

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    data = lc.claude_json("return json")
    assert data == {"a": 1}
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "haiku"


def test_claude_bin_skips_paperclip_tools(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text("#!/bin/sh\necho hi\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CLAUDE_BIN", str(fake))
    assert lc.claude_bin() == str(fake)
