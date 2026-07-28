"""Per-URL GSC SEO attempts and file deletions (local JSON)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import OKADMIN_ROOT

GSC_URL_HISTORY_DIR = OKADMIN_ROOT / "data" / "gsc_logs" / "url_history"

# Soft action hints for the GSC 「대응」 column (display only — not auto-actions).
SEO_ADVICE_DELETE_AFTER = 3


def _history_path(site_id: str) -> Path:
    GSC_URL_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", site_id)
    return GSC_URL_HISTORY_DIR / f"{safe}.json"


def read_url_history(site_id: str) -> dict[str, dict[str, Any]]:
    path = _history_path(site_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_url_history(site_id: str, data: dict[str, dict[str, Any]]) -> None:
    _history_path(site_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _stamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _display(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso[:19]).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16] if iso else None


def _display_day(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso[:19]).strftime("%Y-%m-%d")
    except ValueError:
        return (iso or "")[:10] or None


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trend_from_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare first → last SEO snapshot for a short ↑/→/↓ signal + tooltip."""
    if not attempts:
        return {
            "trend": "none",
            "trend_arrow": "",
            "trend_label": "",
            "tip": "",
            "first_ctr": None,
            "last_ctr": None,
            "first_position": None,
            "last_position": None,
            "first_impressions": None,
            "last_impressions": None,
        }
    first = attempts[0] if isinstance(attempts[0], dict) else {}
    last = attempts[-1] if isinstance(attempts[-1], dict) else {}
    pattern = (last.get("pattern") or first.get("pattern") or "").strip()
    f_ctr, l_ctr = _f(first.get("ctr")), _f(last.get("ctr"))
    f_pos, l_pos = _f(first.get("position")), _f(last.get("position"))
    f_imp, l_imp = _f(first.get("impressions")), _f(last.get("impressions"))

    score = 0  # >0 improve, <0 worsen
    parts: list[str] = []
    if f_ctr is not None and l_ctr is not None:
        parts.append(f"CTR {f_ctr * 100:.2f}%→{l_ctr * 100:.2f}%")
        # low_ctr: CTR up is good
        if l_ctr > f_ctr + 0.001 or (f_ctr > 0 and l_ctr >= f_ctr * 1.15):
            score += 1
        elif l_ctr < f_ctr - 0.001 or (f_ctr > 0 and l_ctr <= f_ctr * 0.85):
            score -= 1
    if f_pos is not None and l_pos is not None:
        parts.append(f"순위 {f_pos:.1f}→{l_pos:.1f}")
        # lower position is better
        if l_pos < f_pos - 1.0:
            score += 1
        elif l_pos > f_pos + 1.0:
            score -= 1
    if pattern == "low_impression" and f_imp is not None and l_imp is not None:
        parts.append(f"노출 {int(f_imp)}→{int(l_imp)}")
        if l_imp > f_imp * 1.2 + 2:
            score += 1
        elif l_imp < f_imp * 0.8 - 2:
            score -= 1

    if len(attempts) < 2 or not parts:
        if len(attempts) < 2:
            trend, arrow, label = "flat", "→", "1회"
        else:
            trend, arrow, label = "flat", "→", "비교불가"
    elif score > 0:
        trend, arrow, label = "up", "↑", "개선"
    elif score < 0:
        trend, arrow, label = "down", "↓", "악화"
    else:
        trend, arrow, label = "flat", "→", "정체"

    tip_bits = [f"SEO {len(attempts)}회", label]
    if pattern:
        tip_bits.append(pattern)
    tip_bits.extend(parts)
    last_at = _display(last.get("at"))
    if last_at:
        tip_bits.append(f"마지막 {last_at}")
    return {
        "trend": trend,
        "trend_arrow": arrow,
        "trend_label": label,
        "tip": " · ".join(tip_bits),
        "first_ctr": f_ctr,
        "last_ctr": l_ctr,
        "first_position": f_pos,
        "last_position": l_pos,
        "first_impressions": f_imp,
        "last_impressions": l_imp,
        "pattern": pattern or None,
    }


def seo_action_advice(
    *,
    seo_count: int = 0,
    trend: str = "",
    has_md: bool = True,
    is_deleted: bool = False,
) -> dict[str, str]:
    """Conservative action hint for URLs still in low-CTR / low-impression lists."""
    if is_deleted or not has_md:
        return {"advice": "", "advice_label": "", "advice_tip": ""}
    try:
        n = int(seo_count or 0)
    except (TypeError, ValueError):
        n = 0
    t = (trend or "").strip() or ("none" if n == 0 else "flat")
    if n >= SEO_ADVICE_DELETE_AFTER:
        if t == "up":
            return {
                "advice": "keep",
                "advice_label": "유지",
                "advice_tip": f"SEO {n}회 · 개선됨 · 유지",
            }
        return {
            "advice": "delete_review",
            "advice_label": "삭제 검토",
            "advice_tip": f"SEO {n}회 · 개선 없음 · 삭제 검토 (자동 삭제 아님)",
        }
    return {
        "advice": "seo",
        "advice_label": "SEO 추천",
        "advice_tip": f"SEO {n}회 · SEO 여지 있음",
    }


def url_history_meta(site_id: str) -> dict[str, dict[str, Any]]:
    """URL → seo_count, trend, tip, dates, deletion flags, advice."""
    raw = read_url_history(site_id)
    out: dict[str, dict[str, Any]] = {}
    for url, block in raw.items():
        if not url or not isinstance(block, dict):
            continue
        attempts = [a for a in (block.get("seo_attempts") or []) if isinstance(a, dict)]
        deleted_at = block.get("deleted_at")
        last = attempts[-1] if attempts else {}
        trend = _trend_from_attempts(attempts)
        is_deleted = bool(deleted_at)
        adv = seo_action_advice(
            seo_count=len(attempts),
            trend=str(trend.get("trend") or ""),
            has_md=True,
            is_deleted=is_deleted,
        )
        out[url] = {
            "seo_count": len(attempts),
            "last_seo_at": last.get("at"),
            "last_seo_display": _display(last.get("at")),
            "last_seo_day": _display_day(last.get("at")),
            "last_seo_status": last.get("status"),
            "deleted_at": deleted_at,
            "deleted_display": _display(deleted_at),
            "deleted_day": _display_day(deleted_at),
            "deleted_files": block.get("deleted_files") or [],
            "is_deleted": is_deleted,
            **trend,
            **adv,
        }
    return out


def record_seo_attempts(site_id: str, results: list[dict[str, Any]]) -> None:
    if not results:
        return
    data = read_url_history(site_id)
    now = _stamp()
    for row in results:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        block = data.setdefault(url, {"seo_attempts": []})
        block.setdefault("seo_attempts", []).append(
            {
                "at": now,
                "status": row.get("status"),
                "pattern": row.get("pattern"),
                "impressions": row.get("impressions"),
                "ctr": row.get("ctr"),
                "position": row.get("position"),
            }
        )
        attempts = block["seo_attempts"]
        if len(attempts) > 30:
            block["seo_attempts"] = attempts[-30:]
    _write_url_history(site_id, data)


def record_url_deletion(
    site_id: str, url: str, *, deleted_files: list[str]
) -> None:
    url = url.strip()
    if not url:
        return
    data = read_url_history(site_id)
    block = data.setdefault(url, {"seo_attempts": []})
    block["deleted_at"] = _stamp()
    block["deleted_files"] = deleted_files
    _write_url_history(site_id, data)
