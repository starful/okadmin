"""Estimated Gemini / Imagen spend ledger (×3 API cost, monthly reset)."""
from __future__ import annotations

import json
import os
import re
import threading
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from typing import Any

OKADMIN_ROOT = Path(__file__).resolve().parent
LEDGER_PATH = OKADMIN_ROOT / "data" / "ai_spend.json"

_lock = threading.Lock()

# Actual-cost × 3 (gemini-flash-latest, conservative retries).
GEMINI_UNIT_YEN: dict[str, int] = {
    "krcampus_guide_en": 7,
    "krcampus_guide_ja": 7,
    "krcampus_school_en": 4,
    "krcampus_school_ja": 4,
    "krcampus_univ_en": 7,
    "krcampus_univ_ja": 7,
    "krcampus_featured": 8,
    "jpcampus_guide_en": 7,
    "jpcampus_univ_en": 7,
    "jpcampus_korean_md": 3,
    "poi_item_md": 3,
    "poi_guide_md": 4,
    "okstats_insight": 3,
    "okstats_guide": 6,
    "starful_position_md": 7,
    "hatena_post": 3,
    "gsc_seo_url": 2,
    "topic_seed_batch": 3,
}

IMAGEN_UNIT_YEN = int(os.environ.get("IMAGEN_UNIT_YEN", "15"))


def _month_key() -> str:
    return datetime.now().strftime("%Y-%m")


def _day_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _budget_gemini() -> int:
    return max(0, int(os.environ.get("GEMINI_BUDGET_YEN", "7000")))


def _budget_imagen() -> int:
    return max(0, int(os.environ.get("IMAGEN_BUDGET_YEN", "120")))


def _empty_ledger() -> dict[str, Any]:
    return {
        "month": _month_key(),
        "gemini": {
            "budget_yen": _budget_gemini(),
            "estimated_yen": 0,
            "events": 0,
            "by_site": {},
            "by_day": {},
        },
        "imagen": {
            "budget_yen": _budget_imagen(),
            "estimated_yen": 0,
            "images": 0,
            "by_site": {},
            "by_day": {},
        },
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _load_unlocked() -> dict[str, Any]:
    if LEDGER_PATH.is_file():
        try:
            data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return _empty_ledger()


def _normalize_month(data: dict[str, Any]) -> dict[str, Any]:
    month = _month_key()
    if data.get("month") != month:
        data = _empty_ledger()
    data["gemini"]["budget_yen"] = _budget_gemini()
    data["imagen"]["budget_yen"] = _budget_imagen()
    for key in ("gemini", "imagen"):
        block = data.setdefault(key, {})
        block.setdefault("estimated_yen", 0)
        block.setdefault("by_site", {})
        block.setdefault("by_day", {})
    data["gemini"].setdefault("events", 0)
    data["imagen"].setdefault("images", 0)
    return data


def _day_gemini(block: dict[str, Any], day: str) -> dict[str, Any]:
    by_day = block.setdefault("by_day", {})
    d = by_day.setdefault(
        day,
        {"estimated_yen": 0, "events": 0, "by_site": {}},
    )
    d.setdefault("estimated_yen", 0)
    d.setdefault("events", 0)
    d.setdefault("by_site", {})
    return d


def _day_imagen(block: dict[str, Any], day: str) -> dict[str, Any]:
    by_day = block.setdefault("by_day", {})
    d = by_day.setdefault(
        day,
        {"estimated_yen": 0, "images": 0, "by_site": {}},
    )
    d.setdefault("estimated_yen", 0)
    d.setdefault("images", 0)
    d.setdefault("by_site", {})
    return d


def _save_unlocked(data: dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    LEDGER_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_spend(
    *,
    gemini_yen: int = 0,
    imagen_yen: int = 0,
    imagen_count: int = 0,
    site_id: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Add estimated spend; returns updated summary."""
    gemini_yen = max(0, int(gemini_yen))
    imagen_yen = max(0, int(imagen_yen))
    imagen_count = max(0, int(imagen_count))
    day = _day_key()
    with _lock:
        data = _normalize_month(_load_unlocked())
        if gemini_yen:
            g = data["gemini"]
            g["estimated_yen"] = int(g.get("estimated_yen") or 0) + gemini_yen
            g["events"] = int(g.get("events") or 0) + 1
            if site_id:
                by = g.setdefault("by_site", {})
                by[site_id] = int(by.get(site_id) or 0) + gemini_yen
            gd = _day_gemini(g, day)
            gd["estimated_yen"] = int(gd.get("estimated_yen") or 0) + gemini_yen
            gd["events"] = int(gd.get("events") or 0) + 1
            if site_id:
                by_d = gd.setdefault("by_site", {})
                by_d[site_id] = int(by_d.get(site_id) or 0) + gemini_yen
        if imagen_yen or imagen_count:
            im = data["imagen"]
            im_n_add = imagen_count or (1 if imagen_yen else 0)
            im["estimated_yen"] = int(im.get("estimated_yen") or 0) + imagen_yen
            im["images"] = int(im.get("images") or 0) + im_n_add
            if site_id:
                by = im.setdefault("by_site", {})
                by[site_id] = int(by.get(site_id) or 0) + imagen_yen
            id_ = _day_imagen(im, day)
            id_["estimated_yen"] = int(id_.get("estimated_yen") or 0) + imagen_yen
            id_["images"] = int(id_.get("images") or 0) + im_n_add
            if site_id:
                by_d = id_.setdefault("by_site", {})
                by_d[site_id] = int(by_d.get(site_id) or 0) + imagen_yen
        _save_unlocked(data)
        return _summary_from(data)


def _int_env(env: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return max(0, int(str(env.get(key, default)).strip()))
    except (TypeError, ValueError):
        return default


def _first_int(patterns: list[str], text: str) -> int | None:
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                return max(0, int(m.group(1)))
            except (TypeError, ValueError):
                continue
    return None


def _imagen_success_count(output: str) -> int:
    n = _first_int(
        [
            r"성공\s*:\s*(\d+)",
            r"✅\s*성공\s*:\s*(\d+)",
            r"success\s*:\s*(\d+)",
            r"새로 생성됨:\s*(\d+)",
            r"생성 완료\s*\((\d+)\)",
        ],
        output,
    )
    return n or 0


def _starful_created_count(output: str, env: dict[str, str]) -> int:
    n = _first_int(
        [
            r"(\d+)件のファイルが新しく作成",
            r"(\d+)件のファイルが新規",
            r"(\d+)건의 파일",
        ],
        output,
    )
    if n is not None:
        return n
    done = len(re.findall(r"✅\s*完了:", output))
    if done:
        return done
    if output and ("完了" in output or "件" in output or "ターゲット" in output):
        return min(_int_env(env, "CONTENT_LIMIT", 6), 6)
    return 0


def _featured_created(output: str) -> int:
    m = re.search(r"created:\s*(\d+)", output, re.I)
    if m:
        return max(0, int(m.group(1)))
    if "Featured done" in output and "created: 0" in output:
        return 0
    return 0


def estimate_pipeline_step(
    site_id: str,
    step_id: str,
    env: dict[str, str],
    output: str,
) -> tuple[int, int, int]:
    """Return (gemini_yen, imagen_yen, imagen_image_count)."""
    out = output or ""
    g = 0
    im_yen = 0
    im_n = 0

    if site_id == "krcampus":
        if step_id == "guides":
            g = _int_env(env, "GUIDE_LIMIT", 3) * GEMINI_UNIT_YEN["krcampus_guide_en"]
        elif step_id == "schools":
            g = _int_env(env, "SCHOOL_LIMIT", 3) * GEMINI_UNIT_YEN["krcampus_school_en"]
        elif step_id == "universities":
            g = _int_env(env, "UNIVERSITY_LIMIT", 3) * GEMINI_UNIT_YEN["krcampus_univ_en"]
        elif step_id == "japanese":
            gn = _int_env(env, "GUIDE_LIMIT", 0)
            sn = _int_env(env, "SCHOOL_LIMIT", 0)
            un = _int_env(env, "UNIVERSITY_LIMIT", 0)
            g = (
                gn * GEMINI_UNIT_YEN["krcampus_guide_ja"]
                + sn * GEMINI_UNIT_YEN["krcampus_school_ja"]
                + un * GEMINI_UNIT_YEN["krcampus_univ_ja"]
            )
        elif step_id == "featured":
            g = _featured_created(out) * GEMINI_UNIT_YEN["krcampus_featured"]

    elif site_id == "jpcampus":
        if step_id == "guides":
            g = _int_env(env, "GUIDE_LIMIT", 3) * GEMINI_UNIT_YEN["jpcampus_guide_en"]
        elif step_id == "universities":
            g = _int_env(env, "UNIVERSITY_LIMIT", 6) * GEMINI_UNIT_YEN["jpcampus_univ_en"]
        elif step_id == "korean":
            g = _int_env(env, "KOREAN_LIMIT", 6) * GEMINI_UNIT_YEN["jpcampus_korean_md"]

    elif site_id in ("okramen", "okonsen", "okcaddie"):
        item_n = _int_env(env, "CONTENT_LIMIT", 6)
        guide_n = _int_env(env, "GUIDE_LIMIT", 3)
        if step_id == "items":
            g = item_n * 2 * GEMINI_UNIT_YEN["poi_item_md"]
        elif step_id == "guides":
            g = guide_n * 2 * GEMINI_UNIT_YEN["poi_guide_md"]
        elif step_id == "images" and site_id == "okramen":
            im_n = _imagen_success_count(out)
            im_yen = im_n * IMAGEN_UNIT_YEN

    elif site_id == "okstats":
        if step_id == "items":
            g = _int_env(env, "CONTENT_LIMIT", 6) * GEMINI_UNIT_YEN["okstats_insight"]
        elif step_id == "guides":
            g = _int_env(env, "GUIDE_LIMIT", 3) * GEMINI_UNIT_YEN["okstats_guide"]
        elif step_id == "images":
            im_n = _imagen_success_count(out)
            im_yen = im_n * IMAGEN_UNIT_YEN

    elif site_id == "starful.biz":
        if step_id == "guides":
            n = _starful_created_count(out, env)
            g = n * GEMINI_UNIT_YEN["starful_position_md"]
        elif step_id == "images":
            im_n = _imagen_success_count(out)
            im_yen = im_n * IMAGEN_UNIT_YEN

    elif site_id == "hatena":
        n = _int_env(env, "HATENA_MAX_POSTS", 6)
        if step_id in ("py", "cloud"):
            g = n * GEMINI_UNIT_YEN["hatena_post"]

    return g, im_yen, im_n


def record_pipeline_step(
    site_id: str,
    step_id: str,
    env: dict[str, str],
    output: str,
) -> None:
    g, im_yen, im_n = estimate_pipeline_step(site_id, step_id, env, output)
    if g or im_yen or im_n:
        record_spend(
            gemini_yen=g,
            imagen_yen=im_yen,
            imagen_count=im_n,
            site_id=site_id,
            note=f"{step_id}",
        )


def record_gsc_seo(site_id: str, url_count: int) -> None:
    n = max(0, int(url_count))
    if n:
        record_spend(
            gemini_yen=n * GEMINI_UNIT_YEN["gsc_seo_url"],
            site_id=site_id,
            note="gsc_seo",
        )


def record_topic_seed(site_id: str) -> None:
    record_spend(
        gemini_yen=GEMINI_UNIT_YEN["topic_seed_batch"],
        site_id=site_id,
        note="topic_seed",
    )


def _pct(used: int, budget: int) -> float:
    if budget <= 0:
        return 0.0
    return round(min(999.0, used * 100.0 / budget), 1)


def _bar_level(pct: float) -> str:
    if pct >= 100:
        return "over"
    if pct >= 90:
        return "danger"
    if pct >= 70:
        return "warn"
    return "ok"


def _daily_series(block: dict[str, Any], month: str) -> tuple[list[dict[str, Any]], int]:
    """Day 1..today (or full month if viewing past) with yen per day."""
    by_day = block.get("by_day") or {}
    try:
        year_s, mon_s = month.split("-", 1)
        year, mon = int(year_s), int(mon_s)
    except (TypeError, ValueError):
        return [], 0
    last_dom = monthrange(year, mon)[1]
    today = _day_key()
    if today.startswith(f"{month}-"):
        end_dom = int(today.split("-")[2])
    else:
        end_dom = last_dom
    rows: list[dict[str, Any]] = []
    max_yen = 0
    for dom in range(1, end_dom + 1):
        dk = f"{month}-{dom:02d}"
        entry = by_day.get(dk) if isinstance(by_day.get(dk), dict) else {}
        yen = int((entry or {}).get("estimated_yen") or 0)
        max_yen = max(max_yen, yen)
        rows.append(
            {
                "date": dk,
                "day": dom,
                "yen": yen,
                "is_today": dk == today,
            }
        )
    return rows, max_yen


def _today_yen(block: dict[str, Any]) -> int:
    by_day = block.get("by_day") or {}
    entry = by_day.get(_day_key())
    if not isinstance(entry, dict):
        return 0
    return int(entry.get("estimated_yen") or 0)


def _summary_from(data: dict[str, Any]) -> dict[str, Any]:
    g = data.get("gemini") or {}
    im = data.get("imagen") or {}
    g_used = int(g.get("estimated_yen") or 0)
    g_budget = int(g.get("budget_yen") or _budget_gemini())
    im_used = int(im.get("estimated_yen") or 0)
    im_budget = int(im.get("budget_yen") or _budget_imagen())
    g_pct = _pct(g_used, g_budget)
    im_pct = _pct(im_used, im_budget)
    month = data.get("month") or _month_key()
    g_daily, g_daily_max = _daily_series(g, month)
    im_daily, im_daily_max = _daily_series(im, month)
    return {
        "month": month,
        "today": _day_key(),
        "updated_at": data.get("updated_at"),
        "note": "推定値 · GCP請求と完全一致しません (API原価×3)",
        "gemini": {
            "budget_yen": g_budget,
            "estimated_yen": g_used,
            "today_yen": _today_yen(g),
            "remaining_yen": max(0, g_budget - g_used),
            "percent": g_pct,
            "level": _bar_level(g_pct),
            "events": int(g.get("events") or 0),
            "by_site": dict(g.get("by_site") or {}),
            "daily": g_daily,
            "daily_max_yen": g_daily_max,
            "unit_yen": dict(GEMINI_UNIT_YEN),
        },
        "imagen": {
            "budget_yen": im_budget,
            "estimated_yen": im_used,
            "today_yen": _today_yen(im),
            "remaining_yen": max(0, im_budget - im_used),
            "percent": im_pct,
            "level": _bar_level(im_pct),
            "images": int(im.get("images") or 0),
            "by_site": dict(im.get("by_site") or {}),
            "daily": im_daily,
            "daily_max_yen": im_daily_max,
            "unit_yen_per_image": IMAGEN_UNIT_YEN,
        },
        "over_budget": {
            "gemini": g_budget > 0 and g_used >= g_budget,
            "imagen": im_budget > 0 and im_used >= im_budget,
        },
    }


def _recompute_month_from_days(data: dict[str, Any]) -> None:
    """Sync month totals from by_day blocks (after backfill)."""
    g = data["gemini"]
    g_by_day = g.get("by_day") or {}
    g["estimated_yen"] = sum(
        int(d.get("estimated_yen") or 0) for d in g_by_day.values() if isinstance(d, dict)
    )
    g["events"] = sum(int(d.get("events") or 0) for d in g_by_day.values() if isinstance(d, dict))
    g_by_site: dict[str, int] = {}
    for d in g_by_day.values():
        if not isinstance(d, dict):
            continue
        for sid, yen in (d.get("by_site") or {}).items():
            g_by_site[sid] = g_by_site.get(sid, 0) + int(yen)
    g["by_site"] = g_by_site

    im = data["imagen"]
    im_by_day = im.get("by_day") or {}
    im["estimated_yen"] = sum(
        int(d.get("estimated_yen") or 0) for d in im_by_day.values() if isinstance(d, dict)
    )
    im["images"] = sum(int(d.get("images") or 0) for d in im_by_day.values() if isinstance(d, dict))
    im_by_site: dict[str, int] = {}
    for d in im_by_day.values():
        if not isinstance(d, dict):
            continue
        for sid, yen in (d.get("by_site") or {}).items():
            im_by_site[sid] = im_by_site.get(sid, 0) + int(yen)
    im["by_site"] = im_by_site


def apply_backfill_day(
    day: str,
    *,
    gemini_yen: int = 0,
    imagen_yen: int = 0,
    imagen_images: int = 0,
    gemini_events: int = 0,
    gemini_by_site: dict[str, int] | None = None,
    imagen_by_site: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Replace one day's ledger from log backfill; recompute month totals."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError(f"invalid day: {day}")
    month = day[:7]
    with _lock:
        data = _load_unlocked()
        if data.get("month") != month:
            data = _empty_ledger()
            data["month"] = month
        data = _normalize_month(data)
        g_day = _day_gemini(data["gemini"], day)
        im_day = _day_imagen(data["imagen"], day)
        g_day["estimated_yen"] = max(0, int(gemini_yen))
        g_day["events"] = max(0, int(gemini_events))
        g_day["by_site"] = {k: int(v) for k, v in (gemini_by_site or {}).items()}
        im_day["estimated_yen"] = max(0, int(imagen_yen))
        im_day["images"] = max(0, int(imagen_images))
        im_day["by_site"] = {k: int(v) for k, v in (imagen_by_site or {}).items()}
        _recompute_month_from_days(data)
        data["backfill_note"] = f"log backfill applied for {day}"
        _save_unlocked(data)
        return _summary_from(data)


def spend_summary() -> dict[str, Any]:
    with _lock:
        data = _normalize_month(_load_unlocked())
        _save_unlocked(data)
        return _summary_from(data)


def spend_preflight() -> dict[str, Any]:
    """Check before starting a pipeline."""
    summary = spend_summary()
    over_g = summary["over_budget"]["gemini"]
    over_i = summary["over_budget"]["imagen"]
    block = over_g
    msg = ""
    if over_g:
        g = summary["gemini"]
        msg = f"Gemini 월 추정 예산 ¥{g['budget_yen']:,} 초과 (현재 ¥{g['estimated_yen']:,})"
    elif over_i:
        im = summary["imagen"]
        msg = f"Imagen 월 추정 예산 ¥{im['budget_yen']:,} 초과 (현재 ¥{im['estimated_yen']:,})"
    return {
        "ok": not block,
        "block_gemini": over_g,
        "block_imagen": over_i,
        "message": msg,
        "summary": summary,
    }
