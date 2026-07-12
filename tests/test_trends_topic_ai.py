"""Unit tests for Google Trends → topic bank seeding (Hatena excluded)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import trends_topic_ai as tta


def test_supports_trends_excludes_hatena():
    assert tta.supports_trends_seed("krcampus")
    assert tta.supports_trends_seed("okramen")
    assert not tta.supports_trends_seed("hatena")
    assert "hatena" not in tta.TRENDS_SITES


def test_slugify_ascii_and_cjk():
    assert tta._slugify("best ramen tokyo") == "best-ramen-tokyo"
    cjk = tta._slugify("韓国留学 費用")
    assert cjk and cjk.startswith("tr-")


def test_rows_for_poi_guides_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(tta, "read_bank", lambda *a, **k: [{"id": "existing-topic", "topic_en": "x"}])
    queries = [
        {"query": "existing topic", "value": 100, "seed": "ramen"},
        {"query": "new ramen guide", "value": 90, "seed": "ramen"},
        {"query": "New Ramen Guide", "value": 80, "seed": "ramen"},
    ]
    rows = tta._rows_for_poi_guides("okramen", queries, limit=5, category="Food")
    assert len(rows) == 1
    assert rows[0]["id"] == "new-ramen-guide"
    assert "ramen" in rows[0]["keywords"]


def test_rows_for_campus_guides():
    with patch.object(tta, "read_bank", return_value=[]):
        rows = tta._rows_for_campus_guides(
            "krcampus",
            [{"query": "D-4 visa korea", "value": 50, "seed": "語学堂"}],
            limit=3,
            category="Visa",
            country="South Korea",
        )
    assert len(rows) == 1
    assert rows[0]["slug"] == "d-4-visa-korea"
    assert "South Korea" in rows[0]["prompt"]
    assert rows[0]["category"] == "Visa"


def test_rows_for_starful_strips_noise():
    with patch.object(tta, "read_bank", return_value=[]):
        rows = tta._rows_for_starful(
            [
                {"query": "site reliability engineer interview", "value": 40, "seed": "sre"},
                {"query": "x", "value": 1, "seed": "sre"},
            ],
            limit=5,
        )
    assert len(rows) >= 1
    assert "interview" not in rows[0]["position_name"].lower()


def test_append_trends_topics_poi_with_mock_fetch():
    fake_queries = [
        {"query": "tsukemen tokyo guide", "value": 200, "seed": "ramen japan"},
        {"query": "best shoyu ramen", "value": 150, "seed": "ramen japan"},
    ]

    def fake_fetch(seeds, **kwargs):
        return fake_queries

    logf = MagicMock()
    with (
        patch.object(tta, "read_bank", return_value=[]),
        patch.object(tta, "_append_bank_rows", return_value=2) as append,
        patch.object(tta, "banks_for_site") as banks,
        patch("topic_bank_pipeline.refresh_topic_state", return_value=None),
    ):
        banks.return_value = [
            MagicMock(bank_id="guides", headers=("id", "topic_en", "topic_ko", "keywords")),
        ]
        # banks_for_site is imported into trends_topic_ai namespace
        with patch.object(tta, "banks_for_site", return_value=banks.return_value):
            info = tta.append_trends_topics(
                "okramen",
                Path("/tmp"),
                logf,
                limit=8,
                fetch_fn=fake_fetch,
            )
    assert info["ok"] is True
    assert info["rows_added"] == 2
    assert info["queries_found"] == 2
    append.assert_called_once()


def test_run_trends_seed_rejects_hatena():
    info = tta.run_trends_seed("hatena")
    assert info["ok"] is False
    assert "hatena" in info["error"].lower()
