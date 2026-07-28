"""Dashboard API: sites registry + git summary + push/deploy."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import requires_auth
from hub_logs import dashboard_logs
from config import get_service, list_hub_services, repo_path, work_root_available
from git_ops import (
    deploy_job_status,
    deploy_script_path,
    git_commit_only,
    git_create_branch,
    git_current_branch,
    git_diff_detail,
    git_push_only,
    git_push_repo,
    git_status_detail,
    is_production_branch,
    site_has_running_deploy,
    start_deploy,
    suggest_branch_name,
)
from git_util import git_summary

hub_bp = Blueprint("hub", __name__, url_prefix="/api")


@hub_bp.route("/sites")
@requires_auth
def api_sites():
    items = []
    for svc in list_hub_services():
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
    """Deploy / git commit snippets for dashboard."""
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


@hub_bp.route("/sites/<site_id>/git/status")
@requires_auth
def api_site_git_status(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    return jsonify(git_status_detail(root))


@hub_bp.route("/sites/<site_id>/git/diff")
@requires_auth
def api_site_git_diff(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    staged = (request.args.get("staged") or "").strip().lower() in ("1", "true", "yes")
    return jsonify(git_diff_detail(root, staged=staged))


@hub_bp.route("/sites/<site_id>/git/branch/suggest", methods=["GET"])
@requires_auth
def api_site_git_branch_suggest(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    hint = (request.args.get("hint") or "").strip()
    issue_title = (request.args.get("issue_title") or request.args.get("title") or "").strip()
    try:
        issue_number = int(request.args["issue_number"]) if request.args.get("issue_number") is not None else None
    except (TypeError, ValueError):
        issue_number = None
    prefix = (request.args.get("prefix") or "feat").strip() or "feat"
    name = suggest_branch_name(
        issue_number=issue_number,
        hint=hint,
        issue_title=issue_title,
        prefix=prefix,
    )
    return jsonify({"ok": True, "name": name, "issue_number": issue_number})


@hub_bp.route("/sites/<site_id>/git/branch", methods=["POST"])
@requires_auth
def api_site_git_branch(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    if site_has_running_deploy(site_id):
        return jsonify({"error": "배포가 진행 중입니다. 끝난 뒤 브랜치를 만드세요"}), 409
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or data.get("branch") or "").strip()
    hint = (data.get("hint") or "").strip()
    issue_title = (data.get("issue_title") or data.get("title") or "").strip()
    try:
        issue_number = int(data["issue_number"]) if data.get("issue_number") is not None else None
    except (TypeError, ValueError):
        issue_number = None
    prefix = (data.get("prefix") or "feat").strip() or "feat"
    if not name:
        name = suggest_branch_name(
            issue_number=issue_number,
            hint=hint,
            issue_title=issue_title,
            prefix=prefix,
        )
    base = (data.get("base") or "main").strip() or "main"
    result = git_create_branch(root, name, base=base)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/git/commit/draft", methods=["POST"])
@requires_auth
def api_site_git_commit_draft(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    from github_ops import draft_commit_english

    data = request.get_json(silent=True) or {}
    hint = (data.get("hint") or data.get("context") or "").strip()
    result = draft_commit_english(root, site_id=site_id, hint=hint)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/git/commit", methods=["POST"])
@requires_auth
def api_site_git_commit(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    if site_has_running_deploy(site_id):
        return jsonify({"error": "배포가 진행 중입니다. 끝난 뒤 커밋하세요"}), 409
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    hint = (data.get("hint") or "").strip()
    from_diff = (data.get("from_diff") or data.get("auto") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if from_diff and not message:
        from github_ops import draft_commit_english

        draft = draft_commit_english(root, site_id=site_id, hint=hint)
        if not draft.get("ok"):
            return jsonify(draft), 400
        message = draft.get("message") or ""
    result = git_commit_only(root, site_id=site_id, message=message)
    status = 200 if result.get("ok") else 500
    if result.get("ok") and from_diff:
        result["drafted"] = True
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/push", methods=["POST"])
@requires_auth
def api_site_push(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    if site_has_running_deploy(site_id):
        return jsonify({"error": "배포가 진행 중입니다. 끝난 뒤 Push하세요"}), 409
    data = request.get_json(silent=True) or {}
    branch = git_current_branch(root)
    allow_main = (data.get("allow_main") or "").strip().lower() in ("1", "true", "yes")
    if is_production_branch(root, branch) and not allow_main:
        return jsonify(
            {
                "ok": False,
                "error": "main/master direct push blocked — use a feature branch + PR",
                "branch": branch,
                "hint": "Create branch, push, open PR in Git tab, merge on GitHub, then pull main",
            }
        ), 409
    # Default: add+commit+push. commit_only=0 & push_only=1 → push existing commits.
    if data.get("push_only"):
        result = git_push_only(root, site_id=site_id)
    else:
        result = git_push_repo(
            root,
            site_id=site_id,
            message=data.get("message"),
        )
    status = 200 if result.get("ok") else 500
    if not result.get("ok"):
        err_msg = result.get("error") or "push failed"
        return jsonify({**result, "status": "failed", "message": err_msg}), status

    return jsonify(result)


@hub_bp.route("/sites/<site_id>/content-cycle/shipped", methods=["POST"])
@requires_auth
def api_site_content_cycle_shipped(site_id: str):
    """Stamp content 7-day clock + deploy log (Paperclip / external deploy)."""
    svc = get_service(site_id)
    if not svc:
        return jsonify({"error": "not found"}), 404
    from config import is_hub_site
    from pipeline_runner import mark_content_cycle_shipped

    if not is_hub_site(svc):
        return jsonify({"error": "site hidden from hub"}), 400
    data = request.get_json(silent=True) or {}
    via = (data.get("via") or "deploy").strip() or "deploy"
    if via not in ("deploy", "git_push", "paperclip"):
        via = "deploy"
    if via == "paperclip":
        via = "deploy"
    detail = (data.get("detail") or "").strip()
    result = mark_content_cycle_shipped(
        site_id,
        via=via,
        record_deploy_log=True,
        detail=detail or f"api content-cycle/shipped via={via}",
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


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


@hub_bp.route("/sites/<site_id>/deploy/logs")
@requires_auth
def api_site_deploy_logs(site_id: str):
    svc = get_service(site_id)
    if not svc:
        return jsonify({"error": "not found"}), 404
    from hub_logs import deploy_logs_for_site

    try:
        max_files = min(50, max(1, int(request.args.get("limit") or "20")))
    except ValueError:
        max_files = 20
    return jsonify({"ok": True, "site_id": site_id, "logs": deploy_logs_for_site(site_id, max_files=max_files)})


@hub_bp.route("/sites/<site_id>/deploy/logs/<filename>")
@requires_auth
def api_site_deploy_log_body(site_id: str, filename: str):
    svc = get_service(site_id)
    if not svc:
        return jsonify({"error": "not found"}), 404
    from hub_logs import read_deploy_log

    result = read_deploy_log(site_id, filename)
    if not result.get("ok"):
        return jsonify(result), 404
    return jsonify(result)


@hub_bp.route("/sites/<site_id>/deploy", methods=["POST"])
@requires_auth
def api_site_deploy(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    if site_has_running_deploy(site_id):
        return jsonify({"error": "이미 배포가 진행 중입니다"}), 409
    try:
        from blueprints.content_bp import is_content_pipeline_running
    except Exception:
        is_content_pipeline_running = None  # type: ignore[assignment]
    if is_content_pipeline_running and is_content_pipeline_running(site_id):
        return jsonify({"error": "콘텐츠 생성이 진행 중입니다. 끝난 뒤 배포하세요"}), 409

    branch = git_current_branch(root)
    if not is_production_branch(root, branch):
        return jsonify(
            {
                "ok": False,
                "error": "production deploy only from main/master",
                "branch": branch,
                "hint": "Merge PR on GitHub, git checkout main && git pull, then Deploy",
            }
        ), 409

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "deploy-only").strip()
    # Hub ④ Deploy = Cloud Build only (git is ③ Git tab).
    with_git = bool(data.get("with_git"))
    result = start_deploy(
        root,
        site_id=site_id,
        mode=mode,
        with_git=with_git,
        with_deploy=True,
        include_build_data=False,
    )
    if not result.get("ok"):
        return jsonify(result), 400

    return jsonify(
        {
            **result,
            "message": "deploy started in background",
        }
    )


@hub_bp.route("/sites/<site_id>/github")
@requires_auth
def api_site_github_config(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    from github_ops import github_config

    return jsonify(github_config(root))


@hub_bp.route("/sites/<site_id>/github/issue/draft", methods=["POST"])
@requires_auth
def api_site_github_issue_draft(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    from github_ops import draft_issue_english

    data = request.get_json(silent=True) or {}
    hint = (data.get("hint") or data.get("context") or "").strip()
    result = draft_issue_english(root, site_id=site_id, hint=hint)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/github/issue", methods=["POST"])
@requires_auth
def api_site_github_issue(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    from github_ops import create_issue, draft_issue_english

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    hint = (data.get("hint") or "").strip()
    from_diff = (data.get("from_diff") or data.get("auto") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if from_diff and not title:
        draft = draft_issue_english(root, site_id=site_id, hint=hint)
        if not draft.get("ok"):
            return jsonify(draft), 400
        title = draft.get("title") or ""
        body = body or (draft.get("body") or "")
    result = create_issue(root, title=title, body=body)
    status = 200 if result.get("ok") else 400
    if result.get("ok") and from_diff:
        result["drafted"] = True
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/github/pr/draft", methods=["POST"])
@requires_auth
def api_site_github_pr_draft(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    from github_ops import draft_pr_english

    data = request.get_json(silent=True) or {}
    hint = (data.get("hint") or data.get("context") or "").strip()
    base = (data.get("base") or "main").strip() or "main"
    try:
        issue_number = int(data["issue_number"]) if data.get("issue_number") is not None else None
    except (TypeError, ValueError):
        issue_number = None
    result = draft_pr_english(
        root,
        site_id=site_id,
        hint=hint,
        issue_number=issue_number,
        base=base,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/github/pr", methods=["GET", "POST"])
@requires_auth
def api_site_github_pr(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    if request.method == "GET":
        from github_ops import pr_for_branch

        branch = (request.args.get("branch") or "").strip() or None
        return jsonify(pr_for_branch(root, branch=branch))

    from github_ops import create_pr, draft_pr_english

    data = request.get_json(silent=True) or {}
    try:
        issue_number = int(data["issue_number"]) if data.get("issue_number") is not None else None
    except (TypeError, ValueError):
        issue_number = None
    from_diff = (data.get("from_diff") or data.get("auto") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    title = (data.get("title") or "").strip()
    body = data.get("body")
    summary = (data.get("summary") or "").strip()
    test_plan = (data.get("test_plan") or "").strip()
    base = (data.get("base") or "main").strip() or "main"
    hint = (data.get("hint") or "").strip()
    if from_diff and not title:
        draft = draft_pr_english(
            root,
            site_id=site_id,
            hint=hint,
            issue_number=issue_number,
            base=base,
        )
        if not draft.get("ok"):
            return jsonify(draft), 400
        title = draft.get("title") or ""
        body = body if body is not None else draft.get("body")
        summary = summary or (draft.get("summary") or "")
        test_plan = test_plan or (draft.get("test_plan") or "")
    result = create_pr(
        root,
        title=title,
        body=body,
        summary=summary,
        issue_number=issue_number,
        test_plan=test_plan,
        base=base,
        head=(data.get("head") or "").strip() or None,
    )
    status = 200 if result.get("ok") else 400
    if result.get("ok") and from_diff:
        result["drafted"] = True
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/github/ship/draft", methods=["POST"])
@requires_auth
def api_site_github_ship_draft(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    from github_ops import draft_ship_english

    data = request.get_json(silent=True) or {}
    hint = (data.get("hint") or data.get("context") or "").strip()
    base = (data.get("base") or "main").strip() or "main"
    result = draft_ship_english(root, site_id=site_id, hint=hint, base=base)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/github/ship/prepare", methods=["POST"])
@requires_auth
def api_site_github_ship_prepare(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    if site_has_running_deploy(site_id):
        return jsonify({"error": "배포가 진행 중입니다. 끝난 뒤 Ship prep하세요"}), 409
    from github_ops import ship_prepare

    data = request.get_json(silent=True) or {}
    hint = (data.get("hint") or data.get("context") or "").strip()
    base = (data.get("base") or "main").strip() or "main"
    try:
        issue_number = int(data["issue_number"]) if data.get("issue_number") is not None else None
    except (TypeError, ValueError):
        issue_number = None
    skip_issue = (data.get("skip_issue") or "").strip().lower() in ("1", "true", "yes")
    result = ship_prepare(
        root,
        site_id=site_id,
        hint=hint,
        base=base,
        issue_number=issue_number,
        skip_issue=skip_issue,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/github/pr/review", methods=["GET"])
@requires_auth
def api_site_github_pr_review(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    from github_ops import pr_review

    number = request.args.get("number")
    try:
        num = int(number) if number is not None and str(number).strip() else None
    except (TypeError, ValueError):
        num = None
    base = (request.args.get("base") or "main").strip() or "main"
    result = pr_review(root, number=num, base=base)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@hub_bp.route("/sites/<site_id>/github/pr/merge", methods=["POST"])
@requires_auth
def api_site_github_pr_merge(site_id: str):
    svc, root, err = _site_repo_or_error(site_id)
    if err:
        return err
    from github_ops import merge_pr

    data = request.get_json(silent=True) or {}
    number = data.get("number")
    try:
        num = int(number) if number is not None else None
    except (TypeError, ValueError):
        num = None
    result = merge_pr(
        root,
        number=num,
        squash=bool(data.get("squash", True)),
        delete_branch=bool(data.get("delete_branch", True)),
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status
