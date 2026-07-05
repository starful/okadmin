from pathlib import Path
from unittest.mock import MagicMock

from content_done import is_content_row_done, row_backlog_missing_files
from content_slugs import content_item_slug


def _spec(bank_id: str, *, key_kind: str = "id"):
    spec = MagicMock()
    spec.bank_id = bank_id
    spec.key_kind = key_kind
    return spec


def test_poi_item_done_and_missing(tmp_path: Path):
    repo = tmp_path / "okramen"
    content = repo / "app" / "content"
    content.mkdir(parents=True)
    name = "Test Ramen Shop"
    slug = content_item_slug("okramen", name)
    spec = _spec("items", key_kind="coord")
    row = {"Name": name}

    assert row_backlog_missing_files("okramen", repo, spec, row) == 2
    assert not is_content_row_done("okramen", repo, spec, row)

    (content / f"{slug}_en.md").write_text("en", encoding="utf-8")
    assert row_backlog_missing_files("okramen", repo, spec, row) == 1
    assert not is_content_row_done("okramen", repo, spec, row)

    (content / f"{slug}_ko.md").write_text("ko", encoding="utf-8")
    assert row_backlog_missing_files("okramen", repo, spec, row) == 0
    assert is_content_row_done("okramen", repo, spec, row)


def test_insight_missing(tmp_path: Path):
    repo = tmp_path / "okstats"
    content = repo / "app" / "content"
    content.mkdir(parents=True)
    spec = _spec("insights")
    row = {"id": "sample-insight"}

    assert row_backlog_missing_files("okstats", repo, spec, row) == 1
    (content / "sample-insight_en.md").write_text("x", encoding="utf-8")
    assert row_backlog_missing_files("okstats", repo, spec, row) == 0
    assert is_content_row_done("okstats", repo, spec, row)


def test_poi_guide_partial_done_vs_backlog(tmp_path: Path):
    repo = tmp_path / "okonsen"
    guides = repo / "app" / "content" / "guides"
    guides.mkdir(parents=True)
    spec = _spec("guides")
    row = {"id": "onsen-guide-1"}

    (guides / "onsen-guide-1_en.md").write_text("en", encoding="utf-8")
    assert is_content_row_done("okonsen", repo, spec, row)
    assert row_backlog_missing_files("okonsen", repo, spec, row) == 1
