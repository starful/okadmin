"""HTML pages for work hub."""
from __future__ import annotations

import os

from flask import Blueprint, redirect, render_template, request, session, url_for

from analytics_api import site_analytics_config
from auth import requires_auth
from config import (
    CALENDAR_WINDOW_DAYS,
    DEFAULT_GCS_IMAGE_SITE,
    SCHEDULE_EVENT_KINDS,
    SITE_COLORS,
    gcs_sites,
    get_service,
    list_services,
    repo_path,
    site_favicon_urls,
    work_root_available,
)
from git_ops import deploy_script_path
from gsc_run_store import gsc_last_runs

pages_bp = Blueprint("pages", __name__)

PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")
ACTIVE_SITE_KEY = "okadmin_active_site_v1"


def _hub_site_list() -> tuple[list[str], list[dict]]:
    site_ids: list[str] = []
    sites: list[dict] = []
    for svc in list_services():
        sid = svc["id"]
        if sid == "okadmin":
            continue
        site_ids.append(sid)
        sites.append({"id": sid, "label": svc.get("label", sid), "links": svc.get("links") or {}})
    return site_ids, sites


def _resolve_site_id(requested: str, site_ids: list[str]) -> str:
    rid = (requested or "").strip()
    if rid in site_ids:
        return rid
    if site_ids:
        return site_ids[0]
    return ""


@pages_bp.route("/")
@requires_auth
def dashboard():
    return render_template(
        "dashboard.html",
        active="dashboard",
        user_email=session.get("user_email", ""),
        work_root_ok=work_root_available(),
    )


@pages_bp.route("/site/<site_id>")
@requires_auth
def site_page(site_id: str):
    site_ids, hub_sites = _hub_site_list()
    if site_id not in site_ids:
        if site_ids:
            return redirect(url_for("pages.site_page", site_id=site_ids[0], section=request.args.get("section") or request.args.get("tab") or "content"))
        return redirect(url_for("pages.dashboard"))

    tab = (request.args.get("section") or request.args.get("tab") or "content").strip().lower()
    if tab == "work":
        tab = "content"
    if tab not in ("content", "deploy", "metrics", "seo"):
        tab = "content"

    try:
        current_days = int(request.args.get("days") or "28")
    except ValueError:
        current_days = 28
    current_days = max(7, min(current_days, 90))

    svc = get_service(site_id)
    site_label = svc.get("label", site_id) if svc else site_id
    site_links = (svc or {}).get("links") or {}
    ac = site_analytics_config(site_id)

    return render_template(
        "site.html",
        active="site",
        user_email=session.get("user_email", ""),
        work_root_ok=work_root_available(),
        site_id=site_id,
        site_label=site_label,
        site_links=site_links,
        hub_sites=hub_sites,
        current_section=tab,
        current_days=current_days,
        site_color=SITE_COLORS.get(site_id, "#e8ff47"),
        gsc_hint=ac.get("gsc_site_url") or "—",
        ga4_hint=ac.get("ga4_property_id") or "(미설정)",
    )


@pages_bp.route("/todos")
@requires_auth
def todos_page():
    return redirect(url_for("pages.schedule_page"))


@pages_bp.route("/schedule")
@requires_auth
def schedule_page():
    return render_template(
        "schedule.html",
        active="schedule",
        user_email=session.get("user_email", ""),
        services=list_services(),
        event_kinds=SCHEDULE_EVENT_KINDS,
        site_colors=SITE_COLORS,
        site_icons=site_favicon_urls(),
        calendar_window_days=CALENDAR_WINDOW_DAYS,
    )


@pages_bp.route("/ops")
@requires_auth
def ops_page():
    """Legacy URL → unified dashboard."""
    return redirect(url_for("pages.dashboard"))


@pages_bp.route("/analytics")
@requires_auth
def analytics_page():
    embed = request.args.get("embed") == "1"
    site_ids, _ = _hub_site_list()

    if not embed:
        requested = (request.args.get("site") or "").strip()
        if requested in site_ids:
            try:
                days = int(request.args.get("days") or "28")
            except ValueError:
                days = 28
            days = max(7, min(days, 90))
            return redirect(url_for("pages.site_page", site_id=requested, section="metrics", days=days))
        if site_ids:
            return redirect(url_for("pages.site_page", site_id=site_ids[0], section="metrics"))

    analytics_sites = []
    for svc in list_services():
        sid = svc["id"]
        if sid == "okadmin":
            continue
        analytics_sites.append(
            {
                "id": sid,
                "label": svc.get("label", sid),
                "analytics": site_analytics_config(sid),
            }
        )

    try:
        current_days = int(request.args.get("days") or "28")
    except ValueError:
        current_days = 28
    current_days = max(7, min(current_days, 90))

    current_site = _resolve_site_id(request.args.get("site") or "", site_ids)

    current_meta = site_analytics_config(current_site) if current_site else {}
    gsc_hint = current_meta.get("gsc_site_url") or "—"
    ga4_hint = current_meta.get("ga4_property_id") or "(미설정)"
    current_site_label = current_site
    for s in analytics_sites:
        if s["id"] == current_site:
            current_site_label = s.get("label") or current_site
            break

    return render_template(
        "analytics.html",
        active="analytics",
        embed=embed,
        user_email=session.get("user_email", ""),
        site_colors=SITE_COLORS,
        analytics_sites=analytics_sites,
        current_site=current_site,
        current_site_label=current_site_label,
        current_days=current_days,
        gsc_hint=gsc_hint,
        ga4_hint=ga4_hint,
    )


@pages_bp.route("/gsc")
@requires_auth
def gsc_page():
    embed = request.args.get("embed") == "1"
    site_ids, _ = _hub_site_list()

    if not embed:
        requested = (request.args.get("site") or "").strip()
        if requested in site_ids:
            return redirect(url_for("pages.site_page", site_id=requested, section="seo"))
        if site_ids:
            return redirect(url_for("pages.site_page", site_id=site_ids[0], section="seo"))

    gsc_sites = []
    for svc in list_services():
        sid = svc["id"]
        if sid == "okadmin":
            continue
        ac = site_analytics_config(sid)
        root = repo_path(svc) if work_root_available() else None
        last = gsc_last_runs(sid)
        gsc_sites.append(
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

    current_site = _resolve_site_id(request.args.get("site") or "", site_ids)

    current_site_label = current_site
    current_meta = site_analytics_config(current_site) if current_site else {}
    for s in gsc_sites:
        if s["id"] == current_site:
            current_site_label = s.get("label") or current_site
            break

    return render_template(
        "gsc.html",
        active="gsc",
        embed=embed,
        user_email=session.get("user_email", ""),
        site_colors=SITE_COLORS,
        gsc_sites=gsc_sites,
        current_site=current_site,
        current_site_label=current_site_label,
        gsc_hint=current_meta.get("gsc_site_url") or "—",
        ga4_hint=current_meta.get("ga4_property_id") or "(미설정)",
    )


@pages_bp.route("/content")
@requires_auth
def content_page():
    """Legacy URL → dashboard."""
    return redirect(url_for("pages.dashboard"))


@pages_bp.route("/images")
@requires_auth
def images_page():
    return render_template(
        "images.html",
        active="images",
        user_email=session.get("user_email", ""),
        sites=gcs_sites(),
        places_key=PLACES_API_KEY,
        default_image_site=DEFAULT_GCS_IMAGE_SITE,
    )
