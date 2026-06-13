"""Unified GA4 + GSC analytics overview API."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from analytics_api import load_analytics_overview, site_analytics_config
from auth import requires_auth
from config import list_services

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


@analytics_bp.route("/sites")
@requires_auth
def analytics_sites():
    items = []
    for svc in list_services():
        sid = svc["id"]
        if sid == "okadmin":
            continue
        ac = site_analytics_config(sid)
        items.append(
            {
                "id": sid,
                "label": svc.get("label", sid),
                "analytics": ac,
                "links": svc.get("links") or {},
            }
        )
    return jsonify(items)


@analytics_bp.route("/overview")
@requires_auth
def analytics_overview():
    site_id = (request.args.get("site_id") or "").strip()
    if not site_id:
        return jsonify({"error": "site_id required"}), 400
    try:
        days = int(request.args.get("days") or "28")
    except ValueError:
        days = 28
    days = max(7, min(days, 90))
    return jsonify(load_analytics_overview(site_id, days=days))

