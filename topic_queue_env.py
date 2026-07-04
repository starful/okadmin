"""Environment variables pointing generators at okadmin topic bank CSVs."""
from __future__ import annotations

from config import get_service, repo_path, work_root_available
from topic_bank import bank_csv_path, ensure_bootstrapped, queue_path
from topic_bank_registry import banks_for_site

# Extra env aliases for scripts that expect a specific variable name.
_SITE_ALIASES: dict[str, dict[str, str]] = {
    "okstats": {
        "TOPIC_QUEUE_CSV": "insights",
    },
    "okramen": {
        "TOPIC_QUEUE_RAMENS": "items",
    },
    "okonsen": {
        "TOPIC_QUEUE_ONSENS": "items",
    },
    "okcaddie": {
        "TOPIC_QUEUE_COURSES": "items",
    },
    "starful.biz": {
        "TOPIC_QUEUE_CSV": "positions",
    },
    "jpcampus": {
        "TOPIC_QUEUE_GUIDE_TOPICS": "guide_topics",
        "TOPIC_QUEUE_UNIVERSITIES": "universities",
    },
    "krcampus": {
        "TOPIC_QUEUE_GUIDE_TOPICS": "guide_topics",
        "TOPIC_QUEUE_LANGUAGE_SCHOOLS": "language_schools",
        "TOPIC_QUEUE_UNIVERSITIES": "universities",
    },
    "hatena": {
        "TOPIC_QUEUE_PYTHON": "python",
        "TOPIC_QUEUE_CLOUD": "cloud",
    },
}


def queue_env_for_site(site_id: str, *, sync: bool = True) -> dict[str, str]:
    """Expose topic bank + pipeline queue CSV paths (TOPIC_QUEUE_* = queue when synced)."""
    if not work_root_available():
        return {}
    svc = get_service(site_id)
    if not svc:
        return {}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {}
    ensure_bootstrapped(site_id, repo)
    env: dict[str, str] = {}
    for spec in banks_for_site(site_id):
        bpath = bank_csv_path(site_id, spec.bank_id)
        qpath = queue_path(site_id, spec.bank_id)
        env[f"TOPIC_BANK_{spec.bank_id.upper()}"] = str(bpath)
        env[f"TOPIC_QUEUE_{spec.bank_id.upper()}"] = str(qpath if qpath.is_file() else bpath)
    for alias, bank_id in _SITE_ALIASES.get(site_id, {}).items():
        if bank_id in {s.bank_id for s in banks_for_site(site_id)}:
            bpath = bank_csv_path(site_id, bank_id)
            qpath = queue_path(site_id, bank_id)
            env[alias] = str(qpath if qpath.is_file() else bpath)
    return env
