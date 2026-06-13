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
            out.append({**r, "label": label, "key": key, "pattern": "low_ctr"})
    out.sort(key=lambda x: (-(x.get("impressions") or 0), x.get("ctr") or 0))
    return out


def low_impression_growth(
    rows: list[dict[str, Any]],
    *,
    min_impressions: int = 1,
    max_impressions: int = 9,
    exclude_labels: set[str] | frozenset[str] | None = None,
    key: str = "page",
) -> list[dict[str, Any]]:
    """Pages with some GSC signal but below the low-CTR band (노출 상향 후보)."""
    skip = exclude_labels or frozenset()
    out = []
    for r in rows:
        imp = int(r.get("impressions") or 0)
        label = r.get(key) or r.get("page") or r.get("query") or ""
        if not label or label in skip:
            continue
        if imp < min_impressions or imp > max_impressions:
            continue
        out.append({**r, "label": label, "key": key, "pattern": "low_impression"})
    out.sort(
        key=lambda x: (
            -(x.get("impressions") or 0),
            float(x.get("position") or 999),
        )
    )
    return out


def analyze_gsc_page_patterns(
    rows: list[dict[str, Any]],
    *,
    key: str = "page",
) -> dict[str, Any]:
    low_ctr = low_ctr_high_impression(rows, key=key)
    exclude = frozenset(
        (r.get("label") or r.get("page") or "").strip() for r in low_ctr if r.get("label") or r.get("page")
    )
    low_impression = low_impression_growth(rows, key=key, exclude_labels=exclude)
    return {
        "low_ctr": low_ctr,
        "low_ctr_count": len(low_ctr),
        "low_impression": low_impression,
        "low_impression_count": len(low_impression),
        "page_rows": len(rows),
    }


def count_md_actionable(rows: list[dict[str, Any]]) -> int:
    return sum(1 for r in rows if r.get("has_md"))


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
