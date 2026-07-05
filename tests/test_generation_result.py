from generation_result import MARKER, emit_generation_result, last_generation_result, parse_generation_results
from pipeline_runner import _content_generation_warning


def test_emit_and_parse(capsys):
    emit_generation_result(step="items", topics=3, generated=6, failed=0)
    out = capsys.readouterr().out
    assert MARKER in out
    parsed = last_generation_result(out)
    assert parsed == {
        "step": "items",
        "topics": 3,
        "generated": 6,
        "failed": 0,
        "skipped": 0,
        "ok": True,
    }


def test_parse_multiple_results():
    text = (
        "log line\n"
        f"{MARKER}{{\"step\":\"guides\",\"topics\":0,\"generated\":0,\"failed\":0,\"skipped\":0,\"ok\":true}}\n"
        f"{MARKER}{{\"step\":\"items\",\"topics\":2,\"generated\":4,\"failed\":0,\"skipped\":0,\"ok\":true}}\n"
    )
    assert len(parse_generation_results(text)) == 2
    assert last_generation_result(text)["step"] == "items"


def test_content_warning_structured_zero():
    steps = [
        {
            "step": "items",
            "ok": True,
            "generation_result": {"topics": 0, "generated": 0, "failed": 0},
        },
        {
            "step": "guides",
            "ok": True,
            "generation_result": {"topics": 0, "generated": 0, "failed": 0},
        },
    ]
    assert _content_generation_warning(steps) == "이번 실행에서 신규 콘텐츠 0건 (백로그 없음 또는 이미 완료)"


def test_content_warning_structured_ok():
    steps = [
        {
            "step": "items",
            "ok": True,
            "generation_result": {"topics": 3, "generated": 3, "failed": 0},
        },
        {
            "step": "guides",
            "ok": True,
            "generation_result": {"topics": 1, "generated": 1, "failed": 0},
        },
    ]
    assert _content_generation_warning(steps) is None


def test_content_warning_structured_all_failed():
    steps = [
        {
            "step": "items",
            "ok": True,
            "label": "insight_generator",
            "generation_result": {"topics": 3, "generated": 0, "failed": 3},
        },
        {
            "step": "guides",
            "ok": True,
            "generation_result": {"topics": 0, "generated": 0, "failed": 0},
        },
    ]
    warn = _content_generation_warning(steps)
    assert warn is not None
    assert "성공 0건" in warn
