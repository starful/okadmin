"""GSC / GA4 API hub + action queue."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from analytics_api import fetch_gsc_pages, fetch_ga4_summary, site_analytics_config
from auth import requires_auth
from config import COL_GSC_ACTIONS, COL_OPS_EVENTS, get_service, list_services, repo_path, work_root_available
from git_ops import deploy_script_path
from firestore_db import doc_to_dict, firestore_unavailable_message, get_db
from gsc_hub_helpers import record_gsc_seo_calendar, seo_commit_message
from gsc_run_store import gsc_last_runs, write_gsc_seo_run
from gsc_seo_worker import delete_url_content_files, load_dashboard, run_seo_jobs
from gsc_service import (
    analyze_gsc_page_patterns,
    indexing_export_lines,
    priority_snippet,
)

gsc_bp = Blueprint("gsc", __name__, url_prefix="/api/gsc")


def _require_db():
    db = get_db()
    if db is None:
        return None, (jsonify({"error": firestore_unavailable_message()}), 503)
    return db, None


@gsc_bp.route("/sites")
@requires_auth
def gsc_sites():
    items = []
    for svc in list_services():
        if svc.get("id") == "okadmin":
            continue
        ac = site_analytics_config(svc["id"])
        root = repo_path(svc) if work_root_available() else None
        sid = svc["id"]
        last = gsc_last_runs(sid)
        items.append(
            {
                "id": sid,
                "label": svc.get("label", sid),
                "links": svc.get("links") or {},
                "analytics": ac,
                "git": bool(svc.get("git", True)),
                "has_deploy": bool(
                    root and svc.get("git", True) and deploy_script_path(root)
                ),
                "last_run_at": last.get("last_run_at"),
                "last_run_display": last.get("last_run_display"),
                "last_run_ok": last.get("last_run_ok"),
                "last_run_kind": last.get("last_run_kind"),
                "last_dashboard_display": last.get("last_dashboard_display"),
                "last_dashboard_ok": last.get("last_dashboard_ok"),
                "last_seo_display": last.get("last_seo_display"),
                "last_seo_ok": last.get("last_seo_ok"),
            }
        )
    return jsonify(items)


@gsc_bp.route("/dashboard")
@requires_auth
def gsc_dashboard():
    site_id = (request.args.get("site_id") or "").strip()
    if not site_id:
        return jsonify({"error": "site_id required"}), 400
    return jsonify(load_dashboard(site_id))


@gsc_bp.route("/run", methods=["POST"])
@requires_auth
def gsc_run_seo():
    body = request.get_json(silent=True) or {}
    site_id = (body.get("site_id") or "").strip()
    if not site_id:
        return jsonify({"error": "site_id required"}), 400
    raw_urls = body.get("urls") or []
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    urls = [str(u).strip() for u in raw_urls if u and str(u).strip()][:15]
    if not urls:
        return jsonify({"error": "urls required — 표에서 URL을 선택하세요"}), 400
    apply_files = True
    raw_patterns = body.get("patterns")
    url_patterns: dict[str, str] = {}
    if isinstance(raw_patterns, dict):
        for k, v in raw_patterns.items():
            uk = str(k).strip()
            pv = str(v).strip()
            if uk and pv in ("low_ctr", "low_impression"):
                url_patterns[uk] = pv
    if url_patterns:
        distinct = {v for v in url_patterns.values() if v in ("low_ctr", "low_impression")}
        if len(distinct) > 1:
            return jsonify(
                {"error": "한 패턴씩만 SEO 실행할 수 있습니다 (저CTR 또는 저노출 중 하나)"}
            ), 400
    result = run_seo_jobs(
        site_id,
        urls=urls,
        apply_files=apply_files,
        url_patterns=url_patterns or None,
    )
    results = result.get("results") or []
    seo_ok = bool(results) and any(
        r.get("status") in ("applied", "no_changes")
        for r in results
    )
    write_gsc_seo_run(site_id, result, ok=seo_ok)
    if seo_ok:
        try:
            from ai_spend import record_gsc_seo

            applied = [r for r in results if r.get("status") in ("applied", "no_changes", "pending")]
            record_gsc_seo(site_id, len(applied) or len(urls))
        except Exception:
            pass
    result["calendar_event"] = record_gsc_seo_calendar(site_id, result)
    result["calendar_skipped"] = result["calendar_event"] is None
    result["suggested_commit_message"] = seo_commit_message(site_id, result)
    result["last_runs"] = gsc_last_runs(site_id)
    from gsc_url_store import url_history_meta

    result["url_history"] = url_history_meta(site_id)
    if result.get("error") and not result.get("results"):
        return jsonify(result), 400
    return jsonify(result)


@gsc_bp.route("/delete-files", methods=["POST"])
@requires_auth
def gsc_delete_files():
    body = request.get_json(silent=True) or {}
    site_id = (body.get("site_id") or "").strip()
    if not site_id:
        return jsonify({"error": "site_id required"}), 400
    raw_urls = body.get("urls") or []
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    urls = [str(u).strip() for u in raw_urls if u and str(u).strip()][:15]
    if not urls:
        return jsonify({"error": "urls required"}), 400
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT not available"}), 503
    result = delete_url_content_files(site_id, urls)
    if result.get("error") and not result.get("results"):
        return jsonify(result), 400
    return jsonify(result)


@gsc_bp.route("/url-history")
@requires_auth
def gsc_url_history():
    from gsc_url_store import url_history_meta

    site_id = (request.args.get("site_id") or "").strip()
    if not site_id:
        return jsonify({"error": "site_id required"}), 400
    return jsonify({"site_id": site_id, "urls": url_history_meta(site_id)})


@gsc_bp.route("/actions", methods=["GET"])
@requires_auth
def gsc_list_actions():
    db, err = _require_db()
    if err:
        return err
    site_id = request.args.get("site_id")
    items = []
    for doc in db.collection(COL_GSC_ACTIONS).stream():
        data = doc_to_dict(doc)
        if site_id and data.get("site_id") != site_id:
            continue
        items.append(data)
    items.sort(key=lambda x: (x.get("done"), x.get("created_at") or ""))
    return jsonify(items)


@gsc_bp.route("/actions", methods=["POST"])
@requires_auth
def gsc_create_action():
    db, err = _require_db()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or body.get("label") or "").strip()
    site_id = (body.get("site_id") or "").strip()
    if not site_id or not url:
        return jsonify({"error": "site_id and url required"}), 400
    from firebase_admin import firestore as fs

    payload = {
        "site_id": site_id,
        "url": url,
        "note": body.get("note") or "",
        "done": False,
        "created_at": fs.SERVER_TIMESTAMP,
    }
    if body.get("add_to_calendar"):
        from datetime import date

        start_at = (body.get("start_at") or date.today().isoformat()).strip()
        title = (body.get("title") or f"GSC · {url[:80]}").strip()
        ev = {
            "title": title,
            "site_id": site_id,
            "kind": "gsc",
            "start_at": start_at,
            "end_at": body.get("end_at") or "",
            "all_day": True,
            "notes": url,
            "created_at": fs.SERVER_TIMESTAMP,
        }
        ev_ref = db.collection(COL_OPS_EVENTS).add(ev)[1]
        payload["calendar_event_id"] = ev_ref.id
    ref = db.collection(COL_GSC_ACTIONS).add(payload)[1]
    return jsonify(doc_to_dict(ref.get())), 201


@gsc_bp.route("/actions/<action_id>", methods=["PUT"])
@requires_auth
def gsc_update_action(action_id: str):
    db, err = _require_db()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    ref = db.collection(COL_GSC_ACTIONS).document(action_id)
    if not ref.get().exists:
        return jsonify({"error": "not found"}), 404
    patch = {}
    if "done" in body:
        patch["done"] = bool(body["done"])
    if "note" in body:
        patch["note"] = body["note"]
    if patch:
        ref.update(patch)
    return jsonify(doc_to_dict(ref.get()))


@gsc_bp.route("/actions/<action_id>", methods=["DELETE"])
@requires_auth
def gsc_delete_action(action_id: str):
    db, err = _require_db()
    if err:
        return err
    ref = db.collection(COL_GSC_ACTIONS).document(action_id)
    if not ref.get().exists:
        return jsonify({"error": "not found"}), 404
    ref.delete()
    return jsonify({"ok": True})


@gsc_bp.route("/export/indexing", methods=["POST"])
@requires_auth
def gsc_export_indexing():
    body = request.get_json(silent=True) or {}
    urls = body.get("urls") or []
    site_id = body.get("site_id") or "site"
    text = indexing_export_lines(urls, site_id)
    return jsonify({"text": text})


@gsc_bp.route("/export/priority-snippet", methods=["POST"])
@requires_auth
def gsc_export_snippet():
    body = request.get_json(silent=True) or {}
    urls = body.get("urls") or []
    text = priority_snippet(urls)
    return jsonify({"text": text})


@gsc_bp.route("/api/fetch", methods=["POST"])
@requires_auth
def gsc_api_fetch():
    body = request.get_json(silent=True) or {}
    site_id = (body.get("site_id") or "").strip()
    ac = site_analytics_config(site_id)
    gsc_url = body.get("gsc_site_url") or ac.get("gsc_site_url")
    if not gsc_url:
        return jsonify({"error": "gsc_site_url not configured in sites.yaml analytics"}), 400
    result = fetch_gsc_pages(gsc_url)
    if result and result.get("rows"):
        result["analysis"] = analyze_gsc_page_patterns(result["rows"], key="page")
    return jsonify(result or {"error": "fetch failed"})


@gsc_bp.route("/api/ga4", methods=["POST"])
@requires_auth
def ga4_api_fetch():
    body = request.get_json(silent=True) or {}
    site_id = (body.get("site_id") or "").strip()
    ac = site_analytics_config(site_id)
    prop = body.get("ga4_property_id") or ac.get("ga4_property_id")
    if not prop:
        return jsonify({"error": "ga4_property_id not in sites.yaml"}), 400
    return jsonify(fetch_ga4_summary(prop))
