"""Flask application factory for Work Hub / OK Admin."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from auth import auth_bp
from blueprints.calendar_api import calendar_bp
from blueprints.content_bp import content_bp
from blueprints.gsc_bp import gsc_bp
from blueprints.hub import hub_bp
from blueprints.images import images_bp
from blueprints.oktemplate_bp import oktemplate_bp
from blueprints.ops import ops_bp
from blueprints.pages import pages_bp
from blueprints.schedule import schedule_bp
from blueprints.todos import todos_bp


def create_app() -> Flask:
    if os.environ.get("K_SERVICE") is None:
        load_dotenv(Path(__file__).resolve().parent / ".env")

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-secret-change-me")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        ct = response.content_type or ""
        if ct.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    @app.before_request
    def gsc_oauth_root_callback():
        """gsc-token.json redirect가 http://127.0.0.1:8090 일 때 루트로 돌아옴."""
        if request.method != "GET" or request.path != "/":
            return None
        if not request.args.get("code") or session.get("gsc_oauth_state") is None:
            return None
        if request.args.get("state") != session.get("gsc_oauth_state"):
            return None
        from auth import gsc_oauth_callback

        return gsc_oauth_callback()

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(hub_bp)
    app.register_blueprint(todos_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(images_bp)
    app.register_blueprint(oktemplate_bp)
    app.register_blueprint(gsc_bp)
    app.register_blueprint(content_bp)

    return app
