#!/usr/bin/env python3
"""Apply profile-link CTA + cta_site to all queue items (preserve status/done_at)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from instagram_prompt_queue import QUEUE_PATH, instagram_common_rules  # noqa: E402
from instagram_site_profiles import apply_cta_to_item  # noqa: E402


def main() -> None:
    if not QUEUE_PATH.is_file():
        raise SystemExit(f"missing {QUEUE_PATH}")
    data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    items = data.get("items") or []
    counts: dict[str, int] = {}
    for item in items:
        apply_cta_to_item(item)
        key = item.get("cta_site") or "?"
        counts[key] = counts.get(key, 0) + 1
    data["common_rules"] = instagram_common_rules()
    data["items"] = items
    QUEUE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("updated", len(items), "items")
    print("cta_site counts:", counts)


if __name__ == "__main__":
    main()
