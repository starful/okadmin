"""Classify deploy-*.log entries as git push stubs vs Cloud Deploy."""

from hub_logs import classify_deploy_log_kind


def test_classify_via_git_push():
    head = "# okpy ship\nvia: git_push\nat: 2026-07-25T12:00:00\nDONE\n"
    assert classify_deploy_log_kind(head=head, size=len(head)) == "git"


def test_classify_via_deploy():
    head = "# okpy ship\nvia: deploy\nat: 2026-07-25T12:00:00\n"
    assert classify_deploy_log_kind(head=head, size=200) == "deploy"


def test_classify_cloud_build_body():
    head = "=== deploy okpy ===\n"
    tail = "Starting Cloud Build...\ngcloud builds submit ...\nDONE\n"
    assert classify_deploy_log_kind(head=head, tail=tail, size=50_000) == "deploy"


def test_classify_tiny_ship_with_git_word():
    head = "# site ship\n완료 (git push)\nDONE\n"
    assert classify_deploy_log_kind(head=head, size=len(head)) == "git"


def test_classify_default_large_unknown_is_deploy():
    head = "some unrelated output\n"
    assert classify_deploy_log_kind(head=head, size=12_000) == "deploy"
