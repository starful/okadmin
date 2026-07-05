"""Tests for okonsen topic_queue_csv sibling fallback."""
from __future__ import annotations

import sys
from pathlib import Path

OKONSEN_SCRIPT = Path("/opt/work/okonsen/script")
sys.path.insert(0, str(OKONSEN_SCRIPT))

from topic_queue_csv import resolve  # noqa: E402


def test_sibling_okadmin_queue(tmp_path: Path, monkeypatch):
    okadmin = tmp_path / "okadmin"
    okonsen = tmp_path / "okonsen"
    queue = okadmin / "data" / "pipeline_queues" / "okonsen" / "items.csv"
    queue.parent.mkdir(parents=True)
    queue.write_text("Name\nTest Onsen\n", encoding="utf-8")

    default = str(okonsen / "script" / "csv" / "onsens.csv")
    monkeypatch.delenv("TOPIC_QUEUE_ITEMS", raising=False)
    monkeypatch.delenv("TOPIC_QUEUE_CSV", raising=False)

    # resolve() walks default_path parents to find sibling okadmin
    (okonsen / "script" / "csv").mkdir(parents=True)
    resolved = resolve("items", default)
    assert resolved == str(queue)
