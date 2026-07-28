"""Same-site deploy and content pipeline must not overlap."""
from __future__ import annotations

from blueprints import content_bp as content_mod
from blueprints.content_bp import is_content_pipeline_running
from git_ops import site_has_running_deploy


def test_is_content_pipeline_running_flag(monkeypatch):
    monkeypatch.setitem(content_mod._pipeline_running, "okramen", True)
    assert is_content_pipeline_running("okramen") is True
    assert is_content_pipeline_running("other") is False


def test_site_has_running_deploy_reads_jobs(monkeypatch):
    class Proc:
        def poll(self):
            return None

    monkeypatch.setattr(
        "git_ops._DEPLOY_JOBS",
        {"okramen-1": {"site_id": "okramen", "proc": Proc()}},
    )
    assert site_has_running_deploy("okramen") is True
    assert site_has_running_deploy("other") is False


def _authed_client(monkeypatch):
    from app_factory import create_app

    monkeypatch.setattr("auth.is_allowed_email", lambda email: bool(email))
    app = create_app()
    app.config["SECRET_KEY"] = "test-secret"
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_email"] = "tester@example.com"
    return client


def test_deploy_api_409_when_content_running(monkeypatch):
    monkeypatch.setitem(content_mod._pipeline_running, "okramen", True)
    monkeypatch.setattr(
        "blueprints.hub._site_repo_or_error",
        lambda site_id: (object(), "/tmp", None),
    )
    monkeypatch.setattr("blueprints.hub.site_has_running_deploy", lambda site_id: False)
    client = _authed_client(monkeypatch)
    res = client.post("/api/sites/okramen/deploy", json={})
    assert res.status_code == 409
    assert "콘텐츠" in (res.get_json() or {}).get("error", "")


def test_content_api_409_when_deploy_running(monkeypatch):
    from content_pipeline import CONTENT_PIPELINES

    monkeypatch.setitem(content_mod._pipeline_running, "okramen", False)
    if "okramen" not in CONTENT_PIPELINES:
        monkeypatch.setitem(CONTENT_PIPELINES, "okramen", {"label": "OKRamen"})
    monkeypatch.setattr("blueprints.content_bp.work_root_available", lambda: True)
    monkeypatch.setattr(
        "git_ops.site_has_running_deploy",
        lambda site_id: site_id == "okramen",
    )
    client = _authed_client(monkeypatch)
    res = client.post("/api/content/pipeline/run", json={"site_id": "okramen"})
    assert res.status_code == 409
    assert "배포" in (res.get_json() or {}).get("error", "")
