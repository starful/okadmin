"""HTML pages for work hub."""
from __future__ import annotations

import os

from flask import Blueprint, redirect, render_template, session, url_for

from auth import requires_auth
from config import (
    AUTO_REGISTER_SCHEDULE,
    CALENDAR_WINDOW_DAYS,
    DEFAULT_GCS_IMAGE_SITE,
    EVENT_KINDS,
    SITE_COLORS,
    gcs_sites,
    list_services,
    work_root_available,
)

pages_bp = Blueprint("pages", __name__)

PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")


@pages_bp.route("/")
@requires_auth
def dashboard():
    return render_template(
        "dashboard.html",
        active="dashboard",
        user_email=session.get("user_email", ""),
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
        event_kinds=EVENT_KINDS,
        site_colors=SITE_COLORS,
        calendar_window_days=CALENDAR_WINDOW_DAYS,
    )


@pages_bp.route("/ops")
@requires_auth
def ops_page():
    return render_template(
        "ops.html",
        active="ops",
        user_email=session.get("user_email", ""),
        schedule=AUTO_REGISTER_SCHEDULE,
        work_root_ok=work_root_available(),
    )


@pages_bp.route("/oktemplate")
@requires_auth
def oktemplate_page():
    return render_template(
        "oktemplate.html",
        active="oktemplate",
        user_email=session.get("user_email", ""),
        work_root_ok=work_root_available(),
    )


@pages_bp.route("/gsc")
@requires_auth
def gsc_page():
    return render_template(
        "gsc.html",
        active="gsc",
        user_email=session.get("user_email", ""),
    )


@pages_bp.route("/content")
@requires_auth
def content_page():
    return render_template(
        "content.html",
        active="content",
        user_email=session.get("user_email", ""),
    )


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
