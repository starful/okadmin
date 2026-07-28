"""Optional GSC Search Console + GA4 Data API (requires credentials)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from config import OKADMIN_ROOT, get_service

GSC_HTTP_TIMEOUT_SEC = int(os.environ.get("GSC_HTTP_TIMEOUT_SEC", "25"))
# Per runReport RPC deadline (seconds). Without this, hung GA4 calls block the UI indefinitely.
GA4_RPC_TIMEOUT_SEC = float(os.environ.get("GA4_RPC_TIMEOUT_SEC", "25"))
GA4_REPORT_RETRIES = max(1, int(os.environ.get("GA4_REPORT_RETRIES", "2")))
GA4_REPORT_RETRY_DELAY_SEC = float(os.environ.get("GA4_REPORT_RETRY_DELAY_SEC", "1.5"))
ANALYTICS_OVERVIEW_TIMEOUT_SEC = int(os.environ.get("ANALYTICS_OVERVIEW_TIMEOUT_SEC", "90"))
# Cap concurrent GA4 RPCs so abandoned/retry storms don't jam the process.
GA4_RPC_CONCURRENCY = max(1, int(os.environ.get("GA4_RPC_CONCURRENCY", "3")))
_gsc_allowed_cache: tuple[float, set[str] | None] | None = None
_gsc_allowed_lock = threading.Lock()
_ga4_rpc_sem = threading.Semaphore(GA4_RPC_CONCURRENCY)
_overview_live_lock = threading.Lock()


GSC_USER_TOKEN_DEFAULT = OKADMIN_ROOT / "gsc-oauth-user.json"
GSC_CLIENT_SECRETS_DEFAULT = OKADMIN_ROOT / "gsc-token.json"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def gsc_user_token_path() -> Path:
    raw = os.environ.get("GSC_TOKEN_PATH") or os.environ.get("GCAL_TOKEN_PATH")
    if raw:
        return Path(raw)
    return GSC_USER_TOKEN_DEFAULT


def gsc_client_secrets_path() -> Path:
    raw = os.environ.get("GSC_CLIENT_SECRETS")
    if raw:
        return Path(raw)
    return GSC_CLIENT_SECRETS_DEFAULT


def _service_account_email() -> str:
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path or not os.path.isfile(cred_path):
        return ""
    try:
        data = json.loads(Path(cred_path).read_text(encoding="utf-8"))
        return str(data.get("client_email") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def _gsc_build_service(creds):
    from googleapiclient.discovery import build

    try:
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp

        http = AuthorizedHttp(creds, http=httplib2.Http(timeout=GSC_HTTP_TIMEOUT_SEC))
        return build("searchconsole", "v1", http=http, cache_discovery=False)
    except Exception:
        return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _gsc_allowed_sites(svc) -> set[str] | None:
    """Cache Search Console site list (sites().list is slow; do not call per site)."""
    global _gsc_allowed_cache
    now = time.time()
    with _gsc_allowed_lock:
        if _gsc_allowed_cache and now - _gsc_allowed_cache[0] < 300:
            return _gsc_allowed_cache[1]
    try:
        allowed = {
            e.get("siteUrl")
            for e in (svc.sites().list().execute().get("siteEntry") or [])
        }
    except Exception:
        return None
    with _gsc_allowed_lock:
        _gsc_allowed_cache = (now, allowed)
    return allowed


def _gsc_credentials():
    from google.oauth2.credentials import Credentials

    path = gsc_user_token_path()
    if path.is_file():
        try:
            return Credentials.from_authorized_user_file(str(path))
        except (ValueError, KeyError):
            pass

    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.isfile(cred_path):
        try:
            from google.oauth2 import service_account

            return service_account.Credentials.from_service_account_file(
                cred_path,
                scopes=[GSC_SCOPE],
            )
        except Exception:
            pass
    return None


def _gsc_search_query(
    site_url: str,
    *,
    dimensions: list[str],
    days: int = 28,
    row_limit: int = 500,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Run Search Console searchanalytics.query; returns {rows, start, end} or {error}."""
    creds = _gsc_credentials()
    if not creds:
        sa = _service_account_email()
        hint = (
            f"GSC_TOKEN_PATH({gsc_user_token_path()}) 또는 GOOGLE_APPLICATION_CREDENTIALS 필요."
        )
        if sa:
            hint += f" 또는 Search Console에 서비스 계정 추가: {sa}"
        return {"error": hint}
    try:
        svc = _gsc_build_service(creds)
        allowed = _gsc_allowed_sites(svc)
        if allowed and site_url not in allowed:
            return {
                "error": (
                    f"이 계정에 '{site_url}' 권한 없음. "
                    f"등록된 속성: {', '.join(sorted(allowed)[:6])}…"
                )
            }
        end = end_date or date.today()
        start = end - timedelta(days=days)
        body: dict[str, Any] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "rowLimit": row_limit,
        }
        res = (
            svc.searchanalytics()
            .query(siteUrl=site_url, body=body)
            .execute()
        )
        return {
            "api_rows": res.get("rows") or [],
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_gsc_daily(
    site_url: str, *, days: int = 28, end_date: date | None = None
) -> dict[str, Any]:
    raw = _gsc_search_query(
        site_url, dimensions=["date"], days=days, row_limit=400, end_date=end_date
    )
    if raw.get("error"):
        return raw
    rows = []
    for row in raw["api_rows"]:
        keys = row.get("keys") or []
        rows.append(
            {
                "date": keys[0] if keys else "",
                "clicks": int(row.get("clicks") or 0),
                "impressions": int(row.get("impressions") or 0),
                "ctr": float(row.get("ctr") or 0),
                "position": float(row.get("position") or 0),
            }
        )
    rows.sort(key=lambda r: r["date"])
    clicks = sum(r["clicks"] for r in rows)
    impressions = sum(r["impressions"] for r in rows)
    totals = {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": (clicks / impressions) if impressions else 0.0,
        "position": (
            sum(r["position"] * r["impressions"] for r in rows) / impressions
            if impressions
            else 0.0
        ),
    }
    return {
        "kind": "daily",
        "rows": rows,
        "totals": totals,
        "start": raw["start"],
        "end": raw["end"],
    }


def fetch_gsc_queries(
    site_url: str, *, days: int = 28, row_limit: int = 25000
) -> dict[str, Any]:
    """Search queries (dimension: query) — up to API row cap."""
    raw = _gsc_search_query(
        site_url, dimensions=["query"], days=days, row_limit=row_limit
    )
    if raw.get("error"):
        return raw
    rows = []
    for row in raw["api_rows"]:
        keys = row.get("keys") or []
        rows.append(
            {
                "query": keys[0] if keys else "",
                "clicks": int(row.get("clicks") or 0),
                "impressions": int(row.get("impressions") or 0),
                "ctr": float(row.get("ctr") or 0),
                "position": float(row.get("position") or 0),
            }
        )
    rows.sort(key=lambda r: r["impressions"], reverse=True)
    return {
        "kind": "queries",
        "rows": rows,
        "query_count": len(rows),
        "truncated": len(raw["api_rows"]) >= row_limit,
        "start": raw["start"],
        "end": raw["end"],
    }


def fetch_gsc_query_count_daily(
    site_url: str, *, days: int = 28, row_limit: int = 25000
) -> dict[str, Any]:
    """Distinct queries per day (dimensions: date + query)."""
    raw = _gsc_search_query(
        site_url, dimensions=["date", "query"], days=days, row_limit=row_limit
    )
    if raw.get("error"):
        return raw
    by_date: dict[str, set[str]] = {}
    for row in raw["api_rows"]:
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        d, q = keys[0], keys[1]
        if not d or not q:
            continue
        by_date.setdefault(d, set()).add(q)
    rows = [
        {"date": d, "queries": len(qs)}
        for d, qs in sorted(by_date.items())
    ]
    return {
        "kind": "query_daily",
        "rows": rows,
        "total_queries": len({q for qs in by_date.values() for q in qs}),
        "truncated": len(raw["api_rows"]) >= row_limit,
        "start": raw["start"],
        "end": raw["end"],
    }


def _build_index_period_history(
    *,
    start: str,
    end: str,
    by_date: dict[str, set[str]],
    total_submitted: int,
) -> list[dict[str, Any]]:
    """일별 색인 추이 — searchAnalytics date×page 응답만 사용 (추가 API 없음)."""
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        return []
    cumulative: set[str] = set()
    history: list[dict[str, Any]] = []
    cur = start_d
    while cur <= end_d:
        d = cur.isoformat()
        if d in by_date:
            cumulative.update(by_date[d])
        indexed = len(cumulative)
        not_indexed = max(total_submitted - indexed, 0) if total_submitted else 0
        history.append({"date": d, "indexed": indexed, "not_indexed": not_indexed})
        cur += timedelta(days=1)
    return history


def _gsc_ui_link(site_id: str) -> str:
    svc = get_service(site_id) or {}
    links = svc.get("links") or {}
    if links.get("gsc"):
        return str(links["gsc"])
    gsc_url = (site_analytics_config(site_id).get("gsc_site_url") or "").strip()
    if gsc_url.startswith("sc-domain:"):
        host = gsc_url.replace("sc-domain:", "", 1)
        return (
            "https://search.google.com/search-console/index"
            f"?resource_id=sc-domain%3A{host}"
        )
    if gsc_url:
        from urllib.parse import quote

        return (
            "https://search.google.com/search-console/index"
            f"?resource_id={quote(gsc_url, safe='')}"
        )
    return ""


def fetch_gsc_indexing(
    site_url: str, *, days: int = 28, site_id: str | None = None
) -> dict[str, Any]:
    """Page indexing summary: GSC sitemap counts + search pages (no per-URL inspection)."""
    creds = _gsc_credentials()
    if not creds:
        sa = _service_account_email()
        hint = f"GSC_TOKEN_PATH({gsc_user_token_path()}) 또는 GOOGLE_APPLICATION_CREDENTIALS 필요."
        if sa:
            hint += f" Search Console에 서비스 계정 추가: {sa}"
        return {"error": hint}
    try:
        svc = _gsc_build_service(creds)
        allowed = _gsc_allowed_sites(svc)
        if allowed and site_url not in allowed:
            return {
                "error": (
                    f"이 계정에 '{site_url}' 권한 없음. "
                    f"등록된 속성: {', '.join(sorted(allowed)[:6])}…"
                )
            }

        listed = svc.sitemaps().list(siteUrl=site_url).execute()
        sitemaps: list[dict[str, Any]] = []
        total_submitted = 0
        total_sitemap_indexed = 0
        for entry in listed.get("sitemap") or []:
            path = entry.get("path") or ""
            if not path:
                continue
            submitted = 0
            sm_indexed = 0
            try:
                detail = (
                    svc.sitemaps()
                    .get(siteUrl=site_url, feedpath=path)
                    .execute()
                )
                for block in detail.get("contents") or []:
                    submitted += int(block.get("submitted") or 0)
                    sm_indexed += int(block.get("indexed") or 0)
            except Exception:
                contents = entry.get("contents") or [{}]
                block0 = contents[0] if contents else {}
                submitted = int(block0.get("submitted") or 0)
                sm_indexed = int(block0.get("indexed") or 0)
            total_submitted += submitted
            total_sitemap_indexed += sm_indexed
            sitemaps.append(
                {
                    "path": path,
                    "submitted": submitted,
                    "indexed": sm_indexed,
                    "errors": entry.get("errors"),
                    "warnings": entry.get("warnings"),
                    "last_downloaded": entry.get("lastDownloaded"),
                }
            )

        page_raw = _gsc_search_query(
            site_url, dimensions=["date", "page"], days=days, row_limit=25000
        )
        if page_raw.get("error"):
            indexed = total_sitemap_indexed
            not_indexed = max(total_submitted - indexed, 0) if total_submitted else 0
            index_source = "gsc_sitemap" if total_sitemap_indexed else "unknown"
            end_d = date.today()
            start_d = end_d - timedelta(days=days)
            history = _build_index_period_history(
                start=start_d.isoformat(),
                end=end_d.isoformat(),
                by_date={},
                total_submitted=total_submitted,
            )
            for row in history:
                row["indexed"] = indexed
                row["not_indexed"] = not_indexed
            return {
                "kind": "indexing",
                "sitemaps": sitemaps,
                "totals": {
                    "indexed": indexed,
                    "not_indexed": not_indexed,
                    "sitemap_submitted": total_submitted,
                    "sitemap_indexed": total_sitemap_indexed,
                    "search_pages": 0,
                    "gap_est": not_indexed,
                    "index_source": index_source,
                },
                "daily": [],
                "history": history,
                "gsc_link": _gsc_ui_link(site_id) if site_id else "",
                "note": "GSC 사이트맵·검색 API 집계 (사유별 상세는 Search Console UI 전용)",
                "pages_error": page_raw["error"],
            }

        by_date: dict[str, set[str]] = {}
        all_pages: set[str] = set()
        for row in page_raw["api_rows"]:
            keys = row.get("keys") or []
            if len(keys) < 2:
                continue
            d, page = keys[0], keys[1]
            if not d or not page:
                continue
            if int(row.get("impressions") or 0) <= 0:
                continue
            by_date.setdefault(d, set()).add(page)
            all_pages.add(page)

        search_pages = len(all_pages)
        if total_sitemap_indexed > 0:
            indexed = total_sitemap_indexed
            not_indexed = max(total_submitted - total_sitemap_indexed, 0)
            index_source = "gsc_sitemap"
        elif total_submitted > 0:
            indexed = search_pages
            not_indexed = max(total_submitted - search_pages, 0)
            index_source = "search_estimate"
        else:
            indexed = search_pages
            not_indexed = 0
            index_source = "search_only"
        daily = [
            {"date": d, "pages": len(ps)} for d, ps in sorted(by_date.items())
        ]
        history = _build_index_period_history(
            start=page_raw["start"],
            end=page_raw["end"],
            by_date=by_date,
            total_submitted=total_submitted,
        )

        return {
            "kind": "indexing",
            "sitemaps": sitemaps,
            "daily": daily,
            "history": history,
            "gsc_link": _gsc_ui_link(site_id) if site_id else "",
            "note": "GSC 사이트맵·검색 API 집계 (사유별 상세는 Search Console UI 전용)",
            "totals": {
                "indexed": indexed,
                "not_indexed": not_indexed,
                "sitemap_submitted": total_submitted,
                "sitemap_indexed": total_sitemap_indexed,
                "search_pages": search_pages,
                "gap_est": not_indexed,
                "index_source": index_source,
                "coverage_pct": (
                    (indexed / total_submitted * 100) if total_submitted else None
                ),
            },
            "truncated": len(page_raw["api_rows"]) >= 25000,
            "start": page_raw["start"],
            "end": page_raw["end"],
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_gsc_pages(
    site_url: str, *, days: int = 28
) -> dict[str, Any] | None:
    """site_url e.g. sc-domain:example.com or https://example.com/"""
    raw = _gsc_search_query(site_url, dimensions=["page"], days=days, row_limit=500)
    if raw.get("error"):
        return raw
    rows = []
    for row in raw["api_rows"]:
        keys = row.get("keys") or []
        rows.append(
            {
                "page": keys[0] if keys else "",
                "clicks": int(row.get("clicks") or 0),
                "impressions": int(row.get("impressions") or 0),
                "ctr": float(row.get("ctr") or 0),
                "position": float(row.get("position") or 0),
            }
        )
    return {
        "kind": "pages",
        "rows": rows,
        "start": raw["start"],
        "end": raw["end"],
    }


def _ga4_creds_ok() -> str | None:
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path or not os.path.isfile(cred_path):
        return "GOOGLE_APPLICATION_CREDENTIALS required for GA4"
    return None


def _ga4_window(days: int, end_date: date | None) -> tuple[date, date]:
    end = end_date or date.today()
    return end - timedelta(days=days), end


def _ga4_run_report(
    property_id: str,
    *,
    dimensions: list[str],
    metrics: list[str],
    start: date,
    end: date,
    row_limit: int = 100000,
    order_metric: str | None = None,
    desc: bool = True,
) -> dict[str, Any]:
    """Low-level GA4 runReport → {rows:[{dims, metrics}], start, end} or {error}."""
    from analytics_cache import is_transient_analytics_error

    err = _ga4_creds_ok()
    if err:
        return {"error": err}
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            OrderBy,
            RunReportRequest,
        )
    except ImportError:
        return {"error": "pip install google-analytics-data"}

    order_bys = []
    if order_metric:
        order_bys = [
            OrderBy(
                metric=OrderBy.MetricOrderBy(metric_name=order_metric),
                desc=desc,
            )
        ]
    req: dict[str, Any] = {
        "property": f"properties/{property_id}",
        "metrics": [Metric(name=m) for m in metrics],
        "date_ranges": [
            DateRange(
                start_date=start.strftime("%Y-%m-%d"),
                end_date=end.strftime("%Y-%m-%d"),
            )
        ],
        "limit": row_limit,
    }
    if dimensions:
        req["dimensions"] = [Dimension(name=d) for d in dimensions]
    if order_bys:
        req["order_bys"] = order_bys
    request = RunReportRequest(**req)
    rpc_timeout = max(5.0, GA4_RPC_TIMEOUT_SEC)

    last_err = ""
    for attempt in range(GA4_REPORT_RETRIES):
        # Fresh client per attempt — avoid a shared channel jammed by abandoned RPCs.
        try:
            client = BetaAnalyticsDataClient()
        except Exception as e:
            return {"error": str(e)}
        try:
            with _ga4_rpc_sem:
                response = client.run_report(request, timeout=rpc_timeout)
            rows_out: list[dict[str, Any]] = []
            for row in response.rows:
                dims = [dv.value for dv in row.dimension_values]
                mets: list[float | int] = []
                for i, mv in enumerate(row.metric_values):
                    raw = mv.value or "0"
                    # rates / durations stay float; counts int when whole
                    if metrics[i] in (
                        "engagementRate",
                        "averageSessionDuration",
                        "bounceRate",
                    ):
                        mets.append(float(raw))
                    else:
                        try:
                            mets.append(int(float(raw)))
                        except ValueError:
                            mets.append(float(raw))
                rows_out.append({"dims": dims, "metrics": mets})
            return {
                "rows": rows_out,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "row_count": len(rows_out),
            }
        except Exception as e:
            last_err = str(e)
            retryable = is_transient_analytics_error(last_err)
            if attempt + 1 >= GA4_REPORT_RETRIES or not retryable:
                return {"error": last_err}
            time.sleep(GA4_REPORT_RETRY_DELAY_SEC * (attempt + 1))
    return {"error": last_err or "GA4 조회 실패"}


def fetch_ga4_summary(
    property_id: str, *, days: int = 28, end_date: date | None = None
) -> dict[str, Any] | None:
    """Daily traffic + period engagement / new-user totals (reports in parallel)."""
    from concurrent.futures import ThreadPoolExecutor

    start, end = _ga4_window(days, end_date)

    def _daily():
        return _ga4_run_report(
            property_id,
            dimensions=["date"],
            metrics=[
                "sessions",
                "activeUsers",
                "eventCount",
                "screenPageViews",
                "newUsers",
                "engagedSessions",
            ],
            start=start,
            end=end,
            row_limit=400,
        )

    def _period():
        return _ga4_run_report(
            property_id,
            dimensions=[],
            metrics=[
                "engagementRate",
                "averageSessionDuration",
                "sessions",
                "activeUsers",
                "newUsers",
                "engagedSessions",
                "eventCount",
                "screenPageViews",
            ],
            start=start,
            end=end,
            row_limit=10,
        )

    def _nvr():
        return _ga4_run_report(
            property_id,
            dimensions=["newVsReturning"],
            metrics=["activeUsers", "sessions"],
            start=start,
            end=end,
            row_limit=10,
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_daily = pool.submit(_daily)
        f_period = pool.submit(_period)
        f_nvr = pool.submit(_nvr)
        daily = f_daily.result()
        period = f_period.result()
        nvr = f_nvr.result()

    if daily.get("error"):
        return daily
    rows = []
    for r in daily.get("rows") or []:
        m = r["metrics"]
        rows.append(
            {
                "date": (r["dims"][0] if r["dims"] else ""),
                "sessions": int(m[0] or 0),
                "users": int(m[1] or 0),
                "events": int(m[2] or 0),
                "pageviews": int(m[3] or 0),
                "new_users": int(m[4] or 0),
                "engaged_sessions": int(m[5] or 0),
            }
        )
    rows.sort(key=lambda x: x["date"])
    totals = {
        "sessions": sum(r["sessions"] for r in rows),
        "users": sum(r["users"] for r in rows),
        "events": sum(r["events"] for r in rows),
        "pageviews": sum(r["pageviews"] for r in rows),
        "new_users": sum(r["new_users"] for r in rows),
        "engaged_sessions": sum(r["engaged_sessions"] for r in rows),
        "engagement_rate": 0.0,
        "avg_session_duration": 0.0,
    }
    if not period.get("error") and period.get("rows"):
        pm = period["rows"][0]["metrics"]
        totals["engagement_rate"] = float(pm[0] or 0)
        totals["avg_session_duration"] = float(pm[1] or 0)
        totals["sessions"] = int(pm[2] or totals["sessions"])
        totals["users"] = int(pm[3] or totals["users"])
        totals["new_users"] = int(pm[4] or totals["new_users"])
        totals["engaged_sessions"] = int(pm[5] or totals["engaged_sessions"])
        totals["events"] = int(pm[6] or totals["events"])
        totals["pageviews"] = int(pm[7] or totals["pageviews"])
    elif totals["sessions"]:
        totals["engagement_rate"] = totals["engaged_sessions"] / totals["sessions"]

    new_vs_returning: list[dict[str, Any]] = []
    if not nvr.get("error"):
        for r in nvr.get("rows") or []:
            new_vs_returning.append(
                {
                    "type": (r["dims"][0] if r["dims"] else ""),
                    "users": int(r["metrics"][0] or 0),
                    "sessions": int(r["metrics"][1] or 0),
                }
            )

    return {
        "property_id": property_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "totals": totals,
        "rows": rows,
        "new_vs_returning": new_vs_returning,
    }


def fetch_ga4_period_totals(
    property_id: str, *, days: int = 28, end_date: date | None = None
) -> dict[str, Any]:
    """Single totals report for prior-period deltas (cheap)."""
    start, end = _ga4_window(days, end_date)
    period = _ga4_run_report(
        property_id,
        dimensions=[],
        metrics=[
            "engagementRate",
            "averageSessionDuration",
            "sessions",
            "activeUsers",
            "newUsers",
            "engagedSessions",
            "eventCount",
            "screenPageViews",
        ],
        start=start,
        end=end,
        row_limit=10,
    )
    if period.get("error"):
        return period
    if not period.get("rows"):
        return {"error": "GA4 기간 합계 없음", "start": start.isoformat(), "end": end.isoformat()}
    pm = period["rows"][0]["metrics"]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "totals": {
            "engagement_rate": float(pm[0] or 0),
            "avg_session_duration": float(pm[1] or 0),
            "sessions": int(pm[2] or 0),
            "users": int(pm[3] or 0),
            "new_users": int(pm[4] or 0),
            "engaged_sessions": int(pm[5] or 0),
            "events": int(pm[6] or 0),
            "pageviews": int(pm[7] or 0),
        },
    }


def fetch_ga4_events(
    property_id: str, *, days: int = 28, end_date: date | None = None
) -> dict[str, Any]:
    """Click-related eventName × eventCount for the period (name contains 'click')."""
    start, end = _ga4_window(days, end_date)
    raw = _ga4_run_report(
        property_id,
        dimensions=["eventName"],
        metrics=["eventCount", "totalUsers"],
        start=start,
        end=end,
        row_limit=100000,
        order_metric="eventCount",
        desc=True,
    )
    if raw.get("error"):
        return raw
    rows = []
    for r in raw.get("rows") or []:
        name = r["dims"][0] if r["dims"] else ""
        if "click" not in name.lower():
            continue
        rows.append(
            {
                "event": name,
                "count": int(r["metrics"][0] or 0),
                "users": int(r["metrics"][1] or 0),
            }
        )
    return {
        "kind": "events",
        "rows": rows,
        "event_count": len(rows),
        "filter": "click",
        "start": raw["start"],
        "end": raw["end"],
    }


def fetch_ga4_channels(
    property_id: str, *, days: int = 28, end_date: date | None = None
) -> dict[str, Any]:
    start, end = _ga4_window(days, end_date)
    raw = _ga4_run_report(
        property_id,
        dimensions=["sessionDefaultChannelGroup"],
        metrics=["sessions", "activeUsers"],
        start=start,
        end=end,
        row_limit=50,
        order_metric="sessions",
        desc=True,
    )
    if raw.get("error"):
        return raw
    rows = []
    total_sessions = 0
    for r in raw.get("rows") or []:
        sess = int(r["metrics"][0] or 0)
        total_sessions += sess
        rows.append(
            {
                "channel": r["dims"][0] if r["dims"] else "",
                "sessions": sess,
                "users": int(r["metrics"][1] or 0),
            }
        )
    organic = next(
        (r for r in rows if "organic" in (r["channel"] or "").lower()),
        None,
    )
    return {
        "kind": "channels",
        "rows": rows,
        "total_sessions": total_sessions,
        "organic_sessions": (organic or {}).get("sessions") or 0,
        "organic_share": (
            ((organic or {}).get("sessions") or 0) / total_sessions
            if total_sessions
            else 0.0
        ),
        "start": raw["start"],
        "end": raw["end"],
    }


def fetch_ga4_devices(
    property_id: str, *, days: int = 28, end_date: date | None = None
) -> dict[str, Any]:
    start, end = _ga4_window(days, end_date)
    raw = _ga4_run_report(
        property_id,
        dimensions=["deviceCategory"],
        metrics=["sessions", "activeUsers"],
        start=start,
        end=end,
        row_limit=20,
        order_metric="sessions",
        desc=True,
    )
    if raw.get("error"):
        return raw
    rows = []
    total_sessions = 0
    mobile_sessions = 0
    for r in raw.get("rows") or []:
        cat = (r["dims"][0] if r["dims"] else "") or ""
        sess = int(r["metrics"][0] or 0)
        total_sessions += sess
        if cat.lower() == "mobile":
            mobile_sessions = sess
        rows.append(
            {
                "device": cat,
                "sessions": sess,
                "users": int(r["metrics"][1] or 0),
            }
        )
    return {
        "kind": "devices",
        "rows": rows,
        "total_sessions": total_sessions,
        "mobile_sessions": mobile_sessions,
        "mobile_share": (
            mobile_sessions / total_sessions if total_sessions else 0.0
        ),
        "start": raw["start"],
        "end": raw["end"],
    }


def fetch_ga4_pages(
    property_id: str, *, days: int = 28, end_date: date | None = None
) -> dict[str, Any]:
    """All page paths by views (API row cap)."""
    start, end = _ga4_window(days, end_date)
    raw = _ga4_run_report(
        property_id,
        dimensions=["pagePath"],
        metrics=["screenPageViews", "activeUsers", "sessions"],
        start=start,
        end=end,
        row_limit=100000,
        order_metric="screenPageViews",
        desc=True,
    )
    if raw.get("error"):
        return raw
    rows = []
    for r in raw.get("rows") or []:
        rows.append(
            {
                "page": r["dims"][0] if r["dims"] else "",
                "pageviews": int(r["metrics"][0] or 0),
                "users": int(r["metrics"][1] or 0),
                "sessions": int(r["metrics"][2] or 0),
            }
        )
    return {
        "kind": "pages",
        "rows": rows,
        "page_count": len(rows),
        "start": raw["start"],
        "end": raw["end"],
    }


def _gsc_site_url_from_links(links: dict) -> str:
    gsc_link = links.get("gsc") or ""
    m = re.search(r"resource_id=([^&]+)", gsc_link)
    if m:
        rid = unquote(m.group(1))
        if rid.startswith("sc-domain:"):
            return rid
        if rid.startswith("https://") or rid.startswith("http://"):
            return rid if rid.endswith("/") else rid + "/"
    return ""


def _analytics_error_short(msg: str, *, kind: str) -> str:
    """Short Korean hint for dashboard cards."""
    from analytics_cache import is_transient_analytics_error

    sa = _service_account_email()
    sa_hint = f" 서비스 계정 Viewer 추가: {sa}" if sa else ""
    text = msg or ""
    if kind == "ga4" and is_transient_analytics_error(text):
        return "GA4 일시 타임아웃 · 갱신을 다시 눌러 주세요"
    if "403" in text and kind == "ga4":
        return f"GA4 권한 없음 (property).{sa_hint}"
    if "403" in text and kind == "gsc":
        return f"GSC 권한 없음.{sa_hint}"
    if "권한 없음" in text or "permission" in text.lower():
        return text[:160] + sa_hint
    if len(text) > 180:
        return text[:180] + "…"
    return text


def site_analytics_config(site_id: str) -> dict[str, str]:
    svc = get_service(site_id) or {}
    analytics = svc.get("analytics") or {}
    links = svc.get("links") or {}
    gsc_url = (
        analytics.get("gsc_site_url")
        or links.get("gsc_property")
        or _gsc_site_url_from_links(links)
        or ""
    )
    if not gsc_url:
        prod = (links.get("production") or "").strip().rstrip("/")
        if prod:
            host = prod.replace("https://", "").replace("http://", "")
            gsc_url = f"sc-domain:{host}"
    return {
        "gsc_site_url": gsc_url,
        "ga4_property_id": str(analytics.get("ga4_property_id") or ""),
    }


def save_gsc_user_token(creds) -> Path:
    """Persist authorized-user JSON for Search Console API."""
    path = gsc_user_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(creds.to_json())
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_gsc_oauth_client() -> tuple[str, str] | None:
    """GSC 전용: gsc-token.json 우선 (.env 로그인 클라이언트와 분리)."""
    secrets_path = gsc_client_secrets_path()
    if secrets_path.is_file():
        data = json.loads(secrets_path.read_text(encoding="utf-8"))
        web = data.get("web") or data.get("installed") or {}
        cid = web.get("client_id")
        secret = web.get("client_secret")
        if cid and secret:
            return cid, secret
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if cid and secret:
        return cid, secret
    return None


def gsc_oauth_redirect_uri() -> str:
    """GCP에 등록된 redirect URI와 동일해야 함."""
    env = os.environ.get("GSC_OAUTH_REDIRECT_URI", "").strip()
    if env:
        return env
    secrets_path = gsc_client_secrets_path()
    if secrets_path.is_file():
        data = json.loads(secrets_path.read_text(encoding="utf-8"))
        web = data.get("web") or data.get("installed") or {}
        uris = list(web.get("redirect_uris") or [])
        for u in uris:
            if "/oauth/gsc/callback" in u:
                return u
        if uris:
            return uris[0]
    return "http://127.0.0.1:8090/oauth/gsc/callback"


def gsc_auth_setup_info() -> dict[str, str]:
    client = load_gsc_oauth_client()
    cid = client[0] if client else ""
    return {
        "client_id": cid,
        "redirect_uri": gsc_oauth_redirect_uri(),
        "service_account": _service_account_email(),
        "user_token_path": str(gsc_user_token_path()),
    }


def run_parallel_analytics_jobs(
    jobs: dict[str, Any],
    *,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Run named callables in parallel; never block past timeout on hung RPCs.

    On timeout, unfinished keys get ``{"error": "조회 시간 초과"}`` and the
    thread pool is shut down without waiting (so HTTP can return promptly).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    result: dict[str, Any] = {}
    if not jobs:
        return result
    timeout = (
        ANALYTICS_OVERVIEW_TIMEOUT_SEC if timeout_sec is None else max(1, int(timeout_sec))
    )
    workers = min(10, max(1, len(jobs)))
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = {pool.submit(fn): key for key, fn in jobs.items()}
        try:
            for fut in as_completed(futs, timeout=timeout):
                key = futs[fut]
                try:
                    result[key] = fut.result()
                except Exception as e:
                    result[key] = {"error": str(e)}
        except TimeoutError:
            for fut, key in futs.items():
                if key not in result:
                    result[key] = {"error": "조회 시간 초과"}
                    fut.cancel()
    finally:
        # Don't block HTTP (or pytest) on hung GA4/GSC RPCs.
        for t in getattr(pool, "_threads", ()):
            try:
                t.daemon = True
            except Exception:
                pass
        pool.shutdown(wait=False, cancel_futures=True)
    return result


def load_analytics_overview(
    site_id: str,
    *,
    days: int = 28,
    refresh: bool = False,
    phase: str = "all",
) -> dict[str, Any]:
    """GA4 + GSC charts payload (day-cached).

    phase:
      - all: compute everything (refresh button fallback)
      - core: KPIs + charts first (fast path); may return full cache
      - tables: events/queries/pages/indexing; completes partial cache
    """
    from analytics_cache import (
        deltas_for_totals,
        merge_analytics_payload,
        normalize_days,
        payload_has_transient_ga4_error,
        read_cache,
        write_cache,
    )

    days = normalize_days(days)
    phase = (phase or "all").strip().lower()
    if phase not in ("all", "core", "tables"):
        phase = "all"

    def _serve_cache() -> dict[str, Any] | None:
        cached = read_cache(site_id, days)
        if not cached:
            return None
        if not cached.get("partial"):
            out_c = dict(cached)
            out_c["cache_hit"] = True
            out_c["partial"] = False
            return out_c
        if phase == "core":
            out_c = dict(cached)
            out_c["cache_hit"] = True
            out_c["partial"] = True
            return out_c
        # Partial day: still serve tables from cache once they were fetched,
        # so page reloads don't re-storm GSC/GA4 until explicit refresh.
        if phase == "tables" and "ga4_events" in cached and "gsc_queries" in cached:
            out_c = dict(cached)
            out_c["cache_hit"] = True
            out_c["partial"] = True
            return out_c
        return None

    if not refresh:
        served = _serve_cache()
        if served is not None:
            return served

    ac = site_analytics_config(site_id)
    out: dict[str, Any] = {
        "site_id": site_id,
        "days": days,
        "analytics": ac,
        "compare_label": f"이전 {days}일 대비",
    }

    ga4_id = (ac.get("ga4_property_id") or "").strip()
    gsc_url = (ac.get("gsc_site_url") or "").strip()
    today = date.today()
    current_start = today - timedelta(days=days)
    prior_end = current_start - timedelta(days=1)

    def _ga4():
        if not ga4_id:
            return {"error": "ga4_property_id 미설정"}
        data = fetch_ga4_summary(ga4_id, days=days)
        if data and data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="ga4")}
        prior = fetch_ga4_period_totals(ga4_id, days=days, end_date=prior_end)
        if data and not prior.get("error"):
            data["prior_totals"] = prior.get("totals") or {}
            data["prior_start"] = prior.get("start")
            data["prior_end"] = prior.get("end")
            data["deltas"] = deltas_for_totals(
                data.get("totals"),
                data.get("prior_totals"),
                (
                    "sessions",
                    "users",
                    "events",
                    "pageviews",
                    "new_users",
                    "engaged_sessions",
                    "engagement_rate",
                    "avg_session_duration",
                ),
            )
            data["compare_label"] = f"이전 {days}일 대비"
        return data or {"error": "GA4 조회 실패"}

    def _ga4_events():
        if not ga4_id:
            return {"error": "ga4_property_id 미설정"}
        data = fetch_ga4_events(ga4_id, days=days)
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="ga4")}
        return data

    def _ga4_channels():
        if not ga4_id:
            return {"error": "ga4_property_id 미설정"}
        data = fetch_ga4_channels(ga4_id, days=days)
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="ga4")}
        return data

    def _ga4_devices():
        if not ga4_id:
            return {"error": "ga4_property_id 미설정"}
        data = fetch_ga4_devices(ga4_id, days=days)
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="ga4")}
        return data

    def _gsc_daily():
        if not gsc_url:
            return {"error": "gsc_site_url 미설정"}
        data = fetch_gsc_daily(gsc_url, days=days)
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="gsc")}
        prior = fetch_gsc_daily(gsc_url, days=days, end_date=prior_end)
        if not prior.get("error"):
            data["prior_totals"] = prior.get("totals") or {}
            data["prior_start"] = prior.get("start")
            data["prior_end"] = prior.get("end")
            data["deltas"] = deltas_for_totals(
                data.get("totals"),
                data.get("prior_totals"),
                ("clicks", "impressions", "ctr", "position"),
            )
            data["compare_label"] = f"이전 {days}일 대비"
        return data

    def _gsc_queries():
        if not gsc_url:
            return {"error": "gsc_site_url 미설정"}
        data = fetch_gsc_queries(gsc_url, days=days, row_limit=20)
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="gsc")}
        return data

    def _gsc_query_daily():
        if not gsc_url:
            return {"error": "gsc_site_url 미설정"}
        data = fetch_gsc_query_count_daily(gsc_url, days=days)
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="gsc")}
        return data

    def _gsc_indexing():
        if not gsc_url:
            return {"error": "gsc_site_url 미설정"}
        data = fetch_gsc_indexing(gsc_url, days=days, site_id=site_id)
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="gsc")}
        return data

    core_jobs = {
        "ga4": _ga4,
        "ga4_channels": _ga4_channels,
        "ga4_devices": _ga4_devices,
        "gsc_daily": _gsc_daily,
    }
    table_jobs = {
        "ga4_events": _ga4_events,
        "gsc_queries": _gsc_queries,
        "gsc_query_daily": _gsc_query_daily,
        "gsc_indexing": _gsc_indexing,
    }

    def _run(jobs: dict) -> dict[str, Any]:
        return run_parallel_analytics_jobs(jobs, timeout_sec=ANALYTICS_OVERVIEW_TIMEOUT_SEC)

    def _finish(payload: dict[str, Any]) -> dict[str, Any]:
        existing = read_cache(site_id, days) or {}
        merged = merge_analytics_payload(existing, payload)
        meta = write_cache(site_id, days, merged)
        merged["cache_hit"] = False
        merged["cache_day"] = meta.get("cache_day")
        merged["cached_at"] = meta.get("cached_at")
        return merged

    # One live Google fetch at a time — avoids retry storms stacking RPCs.
    with _overview_live_lock:
        if not refresh:
            served = _serve_cache()
            if served is not None:
                return served

        if phase == "tables":
            base = read_cache(site_id, days) or {}
            if base and not base.get("partial"):
                out_t = dict(base)
                out_t["cache_hit"] = True
                out_t["partial"] = False
                return out_t
            payload = dict(out)
            for k, v in base.items():
                if k not in ("cache_hit", "partial", "cached_at", "cache_day"):
                    payload[k] = v
            payload.update(_run(table_jobs))
            payload["partial"] = payload_has_transient_ga4_error(payload)
            return _finish(payload)

        if phase == "core":
            payload = dict(out)
            payload.update(_run(core_jobs))
            payload["partial"] = True
            return _finish(payload)

        # phase == all
        payload = dict(out)
        payload.update(_run({**core_jobs, **table_jobs}))
        payload["partial"] = payload_has_transient_ga4_error(payload)
        return _finish(payload)
