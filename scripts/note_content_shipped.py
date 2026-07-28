#!/usr/bin/env python3
"""Record a successful site ship (Paperclip / deploy.sh) into okadmin hub clocks.

Usage:
  python3 /opt/work/okadmin/scripts/note_content_shipped.py okramen
  python3 /opt/work/okadmin/scripts/note_content_shipped.py okramen --via deploy
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OKADMIN_ROOT = Path(__file__).resolve().parents[1]
if str(OKADMIN_ROOT) not in sys.path:
    sys.path.insert(0, str(OKADMIN_ROOT))

from pipeline_runner import mark_content_cycle_shipped  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Bump okadmin content cycle after site push/deploy")
    parser.add_argument("site_id", help="Site id (okramen, okonsen, …)")
    parser.add_argument(
        "--via",
        default="deploy",
        choices=("deploy", "git_push", "paperclip"),
        help="How the ship happened (default: deploy)",
    )
    parser.add_argument("--detail", default="", help="Optional note stored in deploy log")
    args = parser.parse_args()
    via = "deploy" if args.via == "paperclip" else args.via
    result = mark_content_cycle_shipped(
        args.site_id,
        via=via,
        record_deploy_log=True,
        detail=args.detail or f"paperclip/site ship via={args.via}",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
