"""Dashboard API: sites registry + git summary + push/deploy."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import requires_auth
from hub_logs import dashboard_logs
from config import get_service, list_services, repo_path, work_root_available
from git_ops import deploy_job_status, deploy_script_path, git_push_repo, start_deploy
from git_util import git_summary
hub_bp = Blueprint("hub", __name__, url_prefix="/api")


@hub_bp.route("/sites")
@requires_auth
def api_sites():
    items = []
    for svc in list_services():
        item = {
            "id": svc["id"],
            "path": svc.get("path"),
            "git": svc.get("git", True),
            "label": svc.get("label", svc["id"]),
            "links": svc.get("links") or {},
            "has_gcs": bool(svc.get("gcs")),
        }
        root = repo_path(svc) if work_root_available() else None
        if svc.get("git") and root:
            item["git_summary"] = git_summary(root)
            item["has_deploy"] = deploy_script_path(root) is not None
        else:
            item["has_deploy"] = False
        items.append(item)
    return jsonify(items)


@hub_bp.route("/dashboard/logs")
@requires_auth
def api_dashboard_logs():
    """Auto-register / deploy / git commit snippets for dashboard."""
    return jsonify(dashboard_logs())


@hub_bp.route("/sites/<site_id>")
@requires_auth
def api_site_detail(site_id: str):
    svc = get_service(site_id)
    if not svc:
        return jsonify({"error": "not found"}), 404
    item = dict(svc)
    if svc.get("git") and work_root_available():
        item["git_summary"] = git_summary(repo_path(svc))
    return jsonify(item)


@hub_bp.route("/sites/<site_id>/git")
@requires_auth
def api_site_git(site_id: str):
    svc = get_service(site_id)
    if not svc:
        return jsonify({"error": "not found"}), 404
    if not svc.get("git", True):
        return jsonify({"git": False})
    if not work_root_available():
        return jsonify({"error": "WORK_ROOT not available on this host"}), 503
    summary = git_summary(repo_path(svc))
    return jsonify(summary or {"error": "no git repo"})


def _site_repo_or_error(site_id: str):
    svc = get_service(site_id)
    if not svc:
        return None, None, (jsonify({"error": "not found"}), 404)
    if not svc.get("git", True):
        return None, None, (jsonify({"error": "git disabled for this site"}), 400)
    if not work_root_available():
        return None, None, (
            jsonify({"error": "WORK_ROOT not available on this host"}),
            503,
        )
    root = repo_path(svc)
    if not (root / ".git").is_dir():
        return None, None, (jsonify({"error": "no git repository"}), 400)
    return svc, root, None


@hub_bp.route("/sites/<site_id>/push", methods=["POST"])
@requires_auth
def api_site_push(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    result = git_push_repo(
        root,
        site_id=site_id,
        message=data.get("message"),
    )
    status = 200 if result.get("ok") else 500
    if not result.get("ok"):
        err = result.get("error") or "push failed"
        return jsonify(
            {**result, "status": "failed", "message": err}
        ), status

    return jsonify(result)


@hub_bp.route("/sites/<site_id>/deploy/status")
@requires_auth
def api_site_deploy_status(site_id: str):
    job_id = (request.args.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"error": "job_id required"}), 400
    result = deploy_job_status(job_id, site_id=site_id)
    if not result.get("ok") and result.get("error"):
        return jsonify(result), 404
    return jsonify(result)


@hub_bp.route("/sites/<site_id>/deploy", methods=["POST"])
@requires_auth
def api_site_deploy(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "deploy-only").strip()
    result = start_deploy(root, site_id=site_id, mode=mode)
    if not result.get("ok"):
        return jsonify(result), 400

    return jsonify(
        {
            **result,
            "message": "deploy started in background",
        }
    )
