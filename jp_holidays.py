"""Japanese national holidays (holidays-jp.github.io, no API key)."""
from __future__ import annotations

from datetime import date
from functools import lru_cache

import requests

_HOLIDAYS_URL = "https://holidays-jp.github.io/api/v1/{year}/date.json"


@lru_cache(maxsize=12)
def holidays_for_year(year: int) -> dict[str, str]:
    try:
        res = requests.get(_HOLIDAYS_URL.format(year=year), timeout=10)
        res.raise_for_status()
        data = res.json()
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


def holidays_between(start: date, end: date) -> dict[str, str]:
    out: dict[str, str] = {}
    for year in range(start.year, end.year + 1):
        out.update(holidays_for_year(year))
    start_s, end_s = start.isoformat(), end.isoformat()
    return {k: v for k, v in out.items() if start_s <= k <= end_s}
