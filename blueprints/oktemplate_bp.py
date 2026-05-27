"""New OK site wizard (local WORK_ROOT)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

from auth import requires_auth
from config import SITES_YAML, WORK_ROOT, get_service, work_root_available

oktemplate_bp = Blueprint("oktemplate", __name__, url_prefix="/api/oktemplate")

SITE_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
RESERVED = {"oktemplate", "okadmin", "ops", "career-hub"}


@oktemplate_bp.route("/create", methods=["POST"])
@requires_auth
def create_site():
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT not available on this host"}), 503

    data = request.get_json(silent=True) or {}
    site_id = (data.get("site_id") or "").strip().lower()
    force = bool(data.get("force"))

    if not SITE_ID_RE.match(site_id):
        return jsonify({"error": "site_id: lowercase letters, numbers, hyphen; must start with a letter"}), 400
    if site_id in RESERVED:
        return jsonify({"error": f"reserved id: {site_id}"}), 400
    if get_service(site_id):
        return jsonify({"error": "site_id already in sites.yaml"}), 400

    src = WORK_ROOT / "oktemplate"
    dest = WORK_ROOT / site_id
    if dest.exists() and not force:
        return jsonify({"error": f"{dest} already exists (use force)"}), 400

    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "venv", "node_modules", ".venv"),
        )
        quickstart = dest / "script" / "quickstart.py"
        if quickstart.is_file():
            subprocess.run(
                ["python3", str(quickstart)],
                cwd=str(dest),
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
    except subprocess.CalledProcessError as e:
        return jsonify({"error": "quickstart failed", "stderr": e.stderr, "stdout": e.stdout}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    checklist = [
        f"Edit {dest}/script/csv/items.csv and guides.csv",
        f"Set SERVICE_URL / GCP in {dest}/deploy.sh and .env",
        f"Add service entry to {SITES_YAML}",
        "git init && git remote add origin (if new repo)",
        f"Test: cd {dest} && ./deploy.sh --content-only",
    ]
    return jsonify(
        {
            "ok": True,
            "site_id": site_id,
            "path": str(dest),
            "checklist": checklist,
        }
    )
