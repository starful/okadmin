#!/usr/bin/env python3
"""Bootstrap okadmin topic banks from site repos + seed lists."""
from __future__ import annotations

import sys
from pathlib import Path

OKADMIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OKADMIN_ROOT))

from config import get_service, repo_path, work_root_available
from content_pipeline import CONTENT_PIPELINES
from topic_bank import bootstrap_site, bank_stats
from topic_bank_seeds import seeds_for_site


def main() -> int:
    if not work_root_available():
        print("WORK_ROOT not available", file=sys.stderr)
        return 1
    for site_id in CONTENT_PIPELINES:
        svc = get_service(site_id)
        repo = repo_path(svc) if svc else None
        if repo is None or not repo.is_dir():
            print(f"skip {site_id}: missing repo")
            continue
        result = bootstrap_site(site_id, repo, seeds_for_site(site_id))
        stats = bank_stats(site_id)
        print(site_id, result.get("bank_rows_added"), stats.get("banks"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
