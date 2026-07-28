#!/usr/bin/env python3
"""Apply TODO_REVISIONS to seed data and queue.json (preserve done items)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from instagram_seed_data import _RAW, build_seed_items, POINT_COUNT  # noqa: E402
from instagram_todo_revisions import TODO_REVISIONS  # noqa: E402
from instagram_prompt_queue import COMMON_RULES, QUEUE_PATH  # noqa: E402


def main() -> None:
    if len(TODO_REVISIONS) != 46:
        raise SystemExit(f"Expected 46 revisions, got {len(TODO_REVISIONS)}")

    for raw in TODO_REVISIONS:
        if len(raw["points"]) != POINT_COUNT:
            raise SystemExit(f"{raw['topic']}: need {POINT_COUNT} points")

    # Update in-memory seed (first 4 unchanged)
    new_raw = _RAW[:4] + TODO_REVISIONS
    if len(new_raw) != 50:
        raise SystemExit(f"Expected 50 total topics, got {len(new_raw)}")

    # Patch instagram_seed_data.py _RAW
    seed_path = ROOT / "instagram_seed_data.py"
    text = seed_path.read_text(encoding="utf-8")
    start = text.index("_RAW: list[dict[str, Any]] = [")
    end = text.index("]\n\n\nPOINT_COUNT", start)
    # Rebuild _RAW block from new_raw using repr-like formatting
    import pprint

    raw_block = "_RAW: list[dict[str, Any]] = " + pprint.pformat(new_raw, width=120, sort_dicts=False)
    new_text = text[:start] + raw_block + text[end + 1 :]  # skip closing ]
    seed_path.write_text(new_text, encoding="utf-8")

    # Reload seed module after file patch
    import importlib
    import instagram_seed_data as seed_mod

    importlib.reload(seed_mod)
    fresh = {item["id"]: item for item in seed_mod.build_seed_items(batch=1)}

    # Merge queue
    if QUEUE_PATH.is_file():
        queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    else:
        queue = {"version": 1, "items": [], "next_batch": 2}

    queue["common_rules"] = COMMON_RULES
    merged: list[dict] = []
    for old in queue.get("items") or []:
        item_id = old["id"]
        new_item = fresh.get(item_id)
        if not new_item:
            merged.append(old)
            continue
        if old.get("status") == "done":
            merged.append(old)  # keep done as-is
        else:
            updated = dict(new_item)
            updated["status"] = old.get("status", "todo")
            updated["done_at"] = old.get("done_at")
            merged.append(updated)

    queue["items"] = merged
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    todo = sum(1 for i in merged if i.get("status") != "done")
    done = sum(1 for i in merged if i.get("status") == "done")
    print(f"OK: seed updated, queue merged — done={done} todo={todo}")


if __name__ == "__main__":
    main()
