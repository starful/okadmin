"""Optional GSC Search Console + GA4 Data API (requires credentials)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, timedelta
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
                    "pageviews": int(row.metric_values[2].value or 0),
                }
            )
        totals = {"sessions": 0, "users": 0, "pageviews": 0}
        for r in rows:
            totals["sessions"] += r["sessions"]
            totals["users"] += r["users"]
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


def _site_analytics_compact_impl(site_id: str, *, days: int = 28) -> dict[str, Any]:
    ac = site_analytics_config(site_id)
    out: dict[str, Any] = {"site_id": site_id}

    ga4_id = (ac.get("ga4_property_id") or "").strip()
    if not ga4_id:
        out["ga4"] = {"error": "ga4_property_id 미설정"}
    else:
        ga4 = fetch_ga4_summary(ga4_id, days=days)
        if not ga4 or ga4.get("error"):
            raw = (ga4 or {}).get("error") or "GA4 조회 실패"
            out["ga4"] = {"error": _analytics_error_short(raw, kind="ga4")}
        else:
            t = ga4.get("totals") or {}
            out["ga4"] = {
                "sessions": t.get("sessions", 0),
                "users": t.get("users", 0),
                "pageviews": t.get("pageviews", 0),
                "start": ga4.get("start"),
                "end": ga4.get("end"),
            }

    gsc_url = (ac.get("gsc_site_url") or "").strip()
    if not gsc_url:
        out["gsc"] = {"error": "gsc_site_url 미설정"}
    else:
        gsc = fetch_gsc_daily(gsc_url, days=days)
        if gsc.get("error"):
            out["gsc"] = {"error": _analytics_error_short(gsc["error"], kind="gsc")}
        else:
            t = gsc.get("totals") or {}
            out["gsc"] = {
                "clicks": t.get("clicks", 0),
                "impressions": t.get("impressions", 0),
                "ctr": t.get("ctr", 0),
                "position": t.get("position", 0),
                "start": gsc.get("start"),
                "end": gsc.get("end"),
            }
    return out


def site_analytics_compact(site_id: str, *, days: int = 28) -> dict[str, Any]:
    """Lightweight GA4 + GSC totals for dashboard cards (per-site timeout)."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

    timeout = int(os.environ.get("SITE_ANALYTICS_TIMEOUT_SEC", "18"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_site_analytics_compact_impl, site_id, days=days)
        try:
            return fut.result(timeout=timeout)
        except FutTimeout:
            return {
                "site_id": site_id,
                "ga4": {"error": "조회 시간 초과"},
                "gsc": {"error": "조회 시간 초과"},
            }


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
