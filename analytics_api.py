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
_gsc_allowed_cache: tuple[float, set[str] | None] | None = None
_gsc_allowed_lock = threading.Lock()

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
        end = date.today()
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


def fetch_gsc_daily(site_url: str, *, days: int = 28) -> dict[str, Any]:
    raw = _gsc_search_query(site_url, dimensions=["date"], days=days, row_limit=400)
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
    site_url: str, *, days: int = 28, row_limit: int = 500
) -> dict[str, Any]:
    """Top search queries (dimension: query)."""
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


def fetch_ga4_summary(property_id: str, *, days: int = 28) -> dict[str, Any] | None:
    """property_id: numeric GA4 property ID."""
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path or not os.path.isfile(cred_path):
        return {"error": "GOOGLE_APPLICATION_CREDENTIALS required for GA4"}
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
        )

        client = BetaAnalyticsDataClient()
        end = date.today()
        start = end - timedelta(days=days)
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name="date")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="activeUsers"),
                Metric(name="eventCount"),
                Metric(name="screenPageViews"),
            ],
            date_ranges=[
                DateRange(
                    start_date=start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                )
            ],
        )
        response = client.run_report(request)
        rows = []
        for row in response.rows:
            d = row.dimension_values[0].value
            rows.append(
                {
                    "date": d,
                    "sessions": int(row.metric_values[0].value or 0),
                    "users": int(row.metric_values[1].value or 0),
                    "events": int(row.metric_values[2].value or 0),
                    "pageviews": int(row.metric_values[3].value or 0),
                }
            )
        totals = {"sessions": 0, "users": 0, "events": 0, "pageviews": 0}
        for r in rows:
            totals["sessions"] += r["sessions"]
            totals["users"] += r["users"]
            totals["events"] += r["events"]
            totals["pageviews"] += r["pageviews"]
        return {
            "property_id": property_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "totals": totals,
            "rows": rows,
        }
    except ImportError:
        return {"error": "pip install google-analytics-data"}
    except Exception as e:
        return {"error": str(e)}


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
    sa = _service_account_email()
    sa_hint = f" 서비스 계정 Viewer 추가: {sa}" if sa else ""
    text = msg or ""
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


def load_analytics_overview(site_id: str, *, days: int = 28) -> dict[str, Any]:
    """GA4 + GSC charts payload for unified analytics page."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    ac = site_analytics_config(site_id)
    out: dict[str, Any] = {
        "site_id": site_id,
        "days": days,
        "analytics": ac,
    }

    ga4_id = (ac.get("ga4_property_id") or "").strip()
    gsc_url = (ac.get("gsc_site_url") or "").strip()

    def _ga4():
        if not ga4_id:
            return {"error": "ga4_property_id 미설정"}
        data = fetch_ga4_summary(ga4_id, days=days)
        if data and data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="ga4")}
        return data or {"error": "GA4 조회 실패"}

    def _gsc_daily():
        if not gsc_url:
            return {"error": "gsc_site_url 미설정"}
        data = fetch_gsc_daily(gsc_url, days=days)
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="gsc")}
        return data

    def _gsc_queries():
        if not gsc_url:
            return {"error": "gsc_site_url 미설정"}
        data = fetch_gsc_queries(gsc_url, days=days)
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

    def _gsc_pages():
        if not gsc_url:
            return {"error": "gsc_site_url 미설정"}
        data = fetch_gsc_pages(gsc_url, days=days)
        if not data:
            return {"error": "GSC 페이지 조회 실패"}
        if data.get("error"):
            return {"error": _analytics_error_short(data["error"], kind="gsc")}
        return {
            "page_count": len(data.get("rows") or []),
            "start": data.get("start"),
            "end": data.get("end"),
        }

    jobs = {
        "ga4": _ga4,
        "gsc_daily": _gsc_daily,
        "gsc_queries": _gsc_queries,
        "gsc_query_daily": _gsc_query_daily,
        "gsc_indexing": _gsc_indexing,
        "gsc_pages": _gsc_pages,
    }
    timeout = int(os.environ.get("ANALYTICS_OVERVIEW_TIMEOUT_SEC", "45"))
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(fn): key for key, fn in jobs.items()}
        try:
            completed = as_completed(futs, timeout=timeout)
            for fut in completed:
                key = futs[fut]
                try:
                    out[key] = fut.result()
                except Exception as e:
                    out[key] = {"error": str(e)}
        except TimeoutError:
            for fut, key in futs.items():
                if key not in out:
                    out[key] = {"error": "조회 시간 초과"}

    return out
