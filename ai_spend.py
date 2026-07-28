"""GCP Cloud Billing spend (BigQuery export) for the hub dashboard.

Categories: Gemini, Imagen, Banana (Nano Banana / Gemini image), Places, Total.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path
from typing import Any

OKADMIN_ROOT = Path(__file__).resolve().parent
CACHE_PATH = OKADMIN_ROOT / "data" / "ai_spend_bq_cache.json"
CACHE_VERSION = 4

_lock = threading.Lock()

_CACHE_TTL_SEC = max(60, int(os.environ.get("BILLING_BQ_CACHE_SEC", "3600")))

_DEFAULT_PROJECT = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "starful-258005"
_DEFAULT_DATASET = os.environ.get("BILLING_BQ_DATASET", "billing_new")

# Dashboard card keys (order matters for UI)
CATEGORY_KEYS = ("gemini", "imagen", "banana", "places", "total")
# Categories that trigger the home over-budget banner (not Total)
ALERT_KEYS = ("gemini", "imagen", "banana", "places")
ALERT_LABELS = {
    "gemini": "Gemini",
    "imagen": "Imagen",
    "banana": "Banana",
    "places": "Places",
}
# Default per-category alert budget ≈ ¥3000
_DEFAULT_ALERT_YEN = 3000.0
_USD_YEN_RATE = max(1.0, float(os.environ.get("USD_YEN_RATE", "150")))


def _month_key(d: date | None = None) -> str:
    return (d or date.today()).strftime("%Y-%m")


def _day_key(d: date | None = None) -> str:
    return (d or date.today()).strftime("%Y-%m-%d")


def _budget_for(kind: str, currency: str) -> float:
    """Budget in billing currency. Alert categories default to ~¥3000."""
    cur = (currency or "USD").upper()
    yen_env = {
        "gemini": "GEMINI_BUDGET_YEN",
        "imagen": "IMAGEN_BUDGET_YEN",
        "banana": "BANANA_BUDGET_YEN",
        "places": "PLACES_BUDGET_YEN",
        "total": "TOTAL_BUDGET_YEN",
    }
    usd_env = {
        "gemini": ("GEMINI_BUDGET_USD", "GEMINI_BUDGET"),
        "imagen": ("IMAGEN_BUDGET_USD", "IMAGEN_BUDGET"),
        "banana": ("BANANA_BUDGET_USD", "BANANA_BUDGET"),
        "places": ("PLACES_BUDGET_USD", "PLACES_BUDGET"),
        "total": ("TOTAL_BUDGET_USD", "TOTAL_BUDGET"),
    }
    default_yen = 0.0 if kind == "total" else _DEFAULT_ALERT_YEN

    if cur == "JPY":
        return float(os.environ.get(yen_env[kind], str(default_yen)))

    primary, secondary = usd_env[kind]
    if os.environ.get(primary):
        return float(os.environ[primary])
    if os.environ.get(secondary):
        return float(os.environ[secondary])
    # Prefer explicit yen budget even when billing is USD
    if os.environ.get(yen_env[kind]):
        return float(os.environ[yen_env[kind]]) / _USD_YEN_RATE
    return round(default_yen / _USD_YEN_RATE, 4) if default_yen else 0.0


def _pct(used: float, budget: float) -> float:
    if budget <= 0:
        return 0.0
    return round(min(999.0, used * 100.0 / budget), 1)


def _bar_level(pct: float, *, has_budget: bool) -> str:
    if not has_budget:
        return "ok"
    if pct >= 100:
        return "over"
    if pct >= 85:
        return "danger"
    if pct >= 60:
        return "warn"
    return "ok"


def _money(n: float) -> float:
    return round(float(n or 0), 4)


def _load_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.is_file():
        return None
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if int(raw.get("_cache_version") or 0) != CACHE_VERSION:
        return None
    fetched = float(raw.get("_fetched_at") or 0)
    if time.time() - fetched > _CACHE_TTL_SEC:
        return None
    summary = raw.get("summary")
    if not isinstance(summary, dict):
        return None
    if "banana" not in summary or "places" not in summary:
        return None
    return summary


def _save_cache(summary: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            {"_fetched_at": time.time(), "_cache_version": CACHE_VERSION, "summary": summary},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _bq_client():
    from google.cloud import bigquery

    return bigquery.Client(project=_DEFAULT_PROJECT)


def _resolve_table(client: Any, project: str, dataset: str) -> str | None:
    tables = list(client.list_tables(f"{project}.{dataset}"))
    preferred = [t.table_id for t in tables if t.table_id.startswith("gcp_billing_export_resource_v1_")]
    if preferred:
        return preferred[0]
    standard = [t.table_id for t in tables if t.table_id.startswith("gcp_billing_export_v1_")]
    if standard:
        return standard[0]
    for t in tables:
        if "billing" in t.table_id.lower() or "usage" in t.table_id.lower():
            return t.table_id
    return None


def _empty_daily(month: str) -> list[dict[str, Any]]:
    today = date.today()
    days_in_month = monthrange(today.year, today.month)[1]
    if month != _month_key(today):
        try:
            y, m = map(int, month.split("-"))
            days_in_month = monthrange(y, m)[1]
        except ValueError:
            pass
    daily = []
    for dom in range(1, days_in_month + 1):
        dk = f"{month}-{dom:02d}"
        daily.append({"day": dom, "date": dk, "cost": 0.0, "yen": 0, "is_today": dk == _day_key(today)})
    return daily


def _empty_block(budget: float, month: str) -> dict[str, Any]:
    return {
        "budget": budget,
        "budget_yen": int(budget) if budget == int(budget) else budget,
        "cost": 0.0,
        "estimated_yen": 0,
        "today_cost": 0.0,
        "today_yen": 0,
        "remaining": max(0.0, budget),
        "remaining_yen": max(0.0, budget),
        "percent": 0.0,
        "level": "ok",
        "daily": _empty_daily(month),
        "daily_max": 0.0,
        "daily_max_yen": 0,
        "by_site": {},
        "events": 0,
    }


def _fill_block(block: dict[str, Any], day_map: dict[str, float], currency: str) -> None:
    today = _day_key()
    total = sum(day_map.values())
    today_cost = day_map.get(today, 0.0)
    budget = float(block.get("budget") or 0)
    daily = []
    max_d = 0.0
    for item in block["daily"]:
        c = _money(day_map.get(item["date"], 0.0))
        max_d = max(max_d, c)
        display = int(round(c)) if currency.upper() == "JPY" else c
        daily.append({**item, "cost": c, "yen": display})
    pct = _pct(total, budget)
    block.update(
        {
            "cost": _money(total),
            "estimated_yen": _money(total) if currency.upper() != "JPY" else int(round(total)),
            "today_cost": _money(today_cost),
            "today_yen": _money(today_cost) if currency.upper() != "JPY" else int(round(today_cost)),
            "remaining": _money(max(0.0, budget - total)) if budget > 0 else 0.0,
            "remaining_yen": _money(max(0.0, budget - total)) if budget > 0 else 0.0,
            "percent": pct,
            "level": _bar_level(pct, has_budget=budget > 0),
            "daily": daily,
            "daily_max": max_d,
            "daily_max_yen": max_d,
        }
    )


def _query_month_costs(client: Any, table_fqn: str, month: str, project_id: str) -> dict[str, Any]:
    """Return classified daily costs for the billing month."""
    from google.cloud import bigquery

    sql = f"""
    SELECT
      CASE
        WHEN REGEXP_CONTAINS(LOWER(IFNULL(sku.description, '')), r'imagen') THEN 'imagen'
        WHEN (
          REGEXP_CONTAINS(
            LOWER(IFNULL(sku.description, '')),
            r'flash.?image|image generation|nano.?banana|gemini[^a-z0-9]{0,12}image|image[^a-z0-9]{0,12}output|imagenext'
          )
          OR (
            REGEXP_CONTAINS(LOWER(IFNULL(service.description, '')), r'generative language|gemini api')
            AND REGEXP_CONTAINS(LOWER(IFNULL(sku.description, '')), r'\\bimage\\b')
            AND NOT REGEXP_CONTAINS(LOWER(IFNULL(sku.description, '')), r'imagen')
          )
        ) THEN 'banana'
        WHEN (
          REGEXP_CONTAINS(LOWER(IFNULL(sku.description, '')), r'gemini|palm|generate content')
          OR REGEXP_CONTAINS(LOWER(IFNULL(service.description, '')), r'generative language|gemini api')
          OR (
            REGEXP_CONTAINS(LOWER(IFNULL(service.description, '')), r'vertex')
            AND REGEXP_CONTAINS(
              LOWER(IFNULL(sku.description, '')),
              r'online prediction|generat|gemini|flash|pro'
            )
          )
        ) THEN 'gemini'
        WHEN (
          REGEXP_CONTAINS(LOWER(IFNULL(service.description, '')), r'places api')
          OR REGEXP_CONTAINS(
            LOWER(IFNULL(sku.description, '')),
            r'places|nearby search|text search|place details|place photo'
          )
        ) THEN 'places'
        ELSE 'other'
      END AS kind,
      FORMAT_DATE('%Y-%m-%d', DATE(usage_start_time)) AS day,
      SUM(cost) AS cost,
      ANY_VALUE(currency) AS currency
    FROM `{table_fqn}`
    WHERE DATE(usage_start_time) >= @month_start
      AND DATE(usage_start_time) < @month_end
      AND cost != 0
      AND (project.id = @project_id OR project.id IS NULL OR project.id = '')
    GROUP BY kind, day
    ORDER BY day, kind
    """
    y, m = map(int, month.split("-"))
    if m == 12:
        month_end = date(y + 1, 1, 1)
    else:
        month_end = date(y, m + 1, 1)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("month_start", "DATE", date(y, m, 1)),
            bigquery.ScalarQueryParameter("month_end", "DATE", month_end),
            bigquery.ScalarQueryParameter("project_id", "STRING", project_id),
        ]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return {
        "rows": [
            {
                "kind": str(r["kind"]),
                "day": str(r["day"]),
                "cost": float(r["cost"] or 0),
                "currency": str(r["currency"] or "USD"),
            }
            for r in rows
        ]
    }


def _build_summary_from_rows(month: str, rows: list[dict[str, Any]], *, note: str, table: str) -> dict[str, Any]:
    currency = "USD"
    if rows:
        currency = rows[0].get("currency") or "USD"

    blocks = {k: _empty_block(_budget_for(k, currency), month) for k in CATEGORY_KEYS}
    by_kind_day: dict[str, dict[str, float]] = {k: {} for k in CATEGORY_KEYS}
    by_kind_day["other"] = {}

    for r in rows:
        kind = r["kind"] if r["kind"] in by_kind_day else "other"
        day = r["day"]
        cost = float(r["cost"])
        by_kind_day[kind][day] = by_kind_day[kind].get(day, 0.0) + cost
        by_kind_day["total"][day] = by_kind_day["total"].get(day, 0.0) + cost

    for kind in CATEGORY_KEYS:
        _fill_block(blocks[kind], by_kind_day[kind], currency)

    over = {
        k: float(blocks[k]["budget"] or 0) > 0 and blocks[k]["cost"] >= float(blocks[k]["budget"])
        for k in CATEGORY_KEYS
    }
    alert_over = [k for k in ALERT_KEYS if over.get(k)]
    alert_names = [ALERT_LABELS[k] for k in alert_over]
    if alert_over:
        alert_level = "over"
        alert_headline = "예산 초과 · " + " · ".join(alert_names)
        alert_hint = "월 예산(기본 ¥3000) 초과 · Billing 수시간 지연 있음"
    else:
        # Near-limit (danger ≥85%) still surfaces a softer banner
        danger = [
            k
            for k in ALERT_KEYS
            if (blocks[k].get("level") in ("danger", "warn"))
            and float(blocks[k].get("budget") or 0) > 0
        ]
        if any(blocks[k].get("level") == "danger" for k in danger):
            alert_level = "danger"
            alert_headline = "예산 임박 · " + " · ".join(ALERT_LABELS[k] for k in danger if blocks[k].get("level") == "danger")
            alert_hint = "85% 이상 · 사용량 주의"
        else:
            alert_level = "ok"
            alert_headline = ""
            alert_hint = ""

    return {
        "month": month,
        "today": _day_key(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "gcp_billing",
        "currency": currency,
        "table": table,
        "note": note,
        "categories": list(CATEGORY_KEYS),
        **blocks,
        "over_budget": over,
        "alert_over": alert_over,
        "alert_level": alert_level,
        "alert_headline": alert_headline,
        "alert_hint": alert_hint,
    }


def _fetch_summary(*, force: bool = False) -> dict[str, Any]:
    month = _month_key()
    if not force:
        cached = _load_cache()
        if cached and cached.get("month") == month:
            return cached

    project = _DEFAULT_PROJECT
    dataset = _DEFAULT_DATASET

    try:
        client = _bq_client()
        table_id = _resolve_table(client, project, dataset)
        if not table_id:
            summary = _build_summary_from_rows(
                month,
                [],
                note=f"GCP Billing 待機中 · `{project}.{dataset}` にテーブルがまだありません",
                table="",
            )
            _save_cache(summary)
            return summary

        fqn = f"{project}.{dataset}.{table_id}"
        raw = _query_month_costs(client, fqn, month, project)
        summary = _build_summary_from_rows(
            month,
            raw["rows"],
            note="GCP Billing (BigQuery) · Gemini / Imagen / Banana / Places · 数時間遅延あり",
            table=fqn,
        )
        _save_cache(summary)
        return summary
    except Exception as exc:  # noqa: BLE001 — surface to UI
        err = re.sub(r"\s+", " ", str(exc))[:240]
        summary = _build_summary_from_rows(
            month,
            [],
            note=f"GCP Billing 取得失敗: {err}",
            table="",
        )
        summary["error"] = err
        return summary


def spend_summary() -> dict[str, Any]:
    with _lock:
        return _fetch_summary(force=False)


def spend_preflight() -> dict[str, Any]:
    """No longer blocks pipelines (billing export is delayed)."""
    summary = spend_summary()
    return {
        "ok": True,
        "block_gemini": False,
        "block_imagen": False,
        "message": "",
        "summary": summary,
    }


# --- Compatibility no-ops (old estimate ledger removed) ---

GEMINI_UNIT_YEN: dict[str, int] = {}
IMAGEN_UNIT_YEN = 0


def record_spend(**_kwargs: Any) -> dict[str, Any]:
    return spend_summary()


def record_pipeline_step(*_a: Any, **_k: Any) -> None:
    return None


def record_gsc_seo(*_a: Any, **_k: Any) -> None:
    return None


def record_topic_seed(*_a: Any, **_k: Any) -> None:
    return None


def estimate_pipeline_step(
    site_id: str,
    step_id: str,
    env: dict[str, str],
    output: str,
) -> tuple[int, int, int]:
    return 0, 0, 0


def apply_backfill_day(*_a: Any, **_k: Any) -> dict[str, Any]:
    return spend_summary()
