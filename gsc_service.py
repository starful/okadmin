"""GSC API analysis helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def low_ctr_high_impression(
    rows: list[dict[str, Any]],
    *,
    min_impressions: int = 10,
    max_ctr: float = 0.03,
    key: str = "page",
) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        imp = int(r.get("impressions") or 0)
        ctr = float(r.get("ctr") or 0)
        label = r.get(key) or r.get("page") or r.get("query") or ""
        if not label or imp < min_impressions:
            continue
        if ctr <= max_ctr:
            out.append({**r, "label": label, "key": key})
    out.sort(key=lambda x: (-(x.get("impressions") or 0), x.get("ctr") or 0))
    return out


def indexing_export_lines(urls: list[str], site_id: str) -> str:
    lines = [
        f"# GSC indexing — {site_id}",
        f"# generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
    ]
    for u in urls:
        lines.append(f"- {u}")
    return "\n".join(lines) + "\n"


def priority_snippet(urls: list[str], *, var_name: str = "GSC_PRIORITY_URLS") -> str:
    body = ",\n".join(f'    "{u}"' for u in urls[:40])
    return f"{var_name} = [\n{body}\n]\n"
