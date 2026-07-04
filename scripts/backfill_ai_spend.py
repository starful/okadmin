#!/usr/bin/env python3
"""Backfill ai_spend.json from pipeline logs for a given day."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_spend_backfill import backfill_day  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill AI spend from pipeline logs")
    parser.add_argument("--day", default="2026-07-01", help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Compute only, do not write ledger")
    args = parser.parse_args()
    result = backfill_day(args.day, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
