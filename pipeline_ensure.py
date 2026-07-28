"""Topic-bank ensure step before content generation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline_limits import (
    DEFAULT_CONTENT_LIMIT,
    DEFAULT_GUIDE_LIMIT,
    DEFAULT_KRCAMPUS_SCHOOL_LIMIT,
    DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT,
    int_env_allow_zero,
)
from pipeline_specs import RELEASE_QUEUE_SITES, ensure_mode

def ensure_site_topic_bank(
    site_id: str,
    repo: Path,
    logf,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Prepare topic bank queues according to SITE_ENSURE_MODE."""
    mode = ensure_mode(site_id)
    if mode is None:
        raise ValueError(f"no ensure mode for site: {site_id}")

    env = env or {}

    if mode == "sync_only":
        from topic_bank_pipeline import topic_bank_sync_only

        return topic_bank_sync_only(site_id, repo, logf)

    if mode == "expand":
        from topic_bank_pipeline import prepare_topics_for_generation

        content_limit = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        guide_limit = int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
        return prepare_topics_for_generation(
            site_id,
            repo,
            logf,
            content_limit=content_limit,
            guide_limit=guide_limit,
        )

    from topic_bank_pipeline import topic_bank_release_queues

    if site_id == "starful.biz":
        content_limit = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        return topic_bank_release_queues(
            site_id,
            repo,
            logf,
            content_limit=content_limit,
            guide_limit=0,
        )

    if site_id == "jpcampus":
        guide_limit = int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
        university_limit = int_env_allow_zero(env, "UNIVERSITY_LIMIT", DEFAULT_CONTENT_LIMIT)
        return topic_bank_release_queues(
            site_id,
            repo,
            logf,
            content_limit=university_limit,
            guide_limit=guide_limit,
        )

    if site_id == "krcampus":
        guide_limit = int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
        school_limit = int_env_allow_zero(env, "SCHOOL_LIMIT", DEFAULT_KRCAMPUS_SCHOOL_LIMIT)
        university_limit = int_env_allow_zero(
            env, "UNIVERSITY_LIMIT", DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT
        )
        return topic_bank_release_queues(
            site_id,
            repo,
            logf,
            content_limit=0,
            guide_limit=guide_limit,
            school_limit=school_limit,
            university_limit=university_limit,
            content_limit_each=False,
        )

    if site_id == "okpy":
        py_n = int_env_allow_zero(env, "PYTHON_LIMIT", DEFAULT_CONTENT_LIMIT)
        cloud_n = int_env_allow_zero(env, "CLOUD_LIMIT", DEFAULT_CONTENT_LIMIT)
        tf_n = int_env_allow_zero(env, "TERRAFORM_LIMIT", DEFAULT_CONTENT_LIMIT)
        if "PYTHON_LIMIT" not in env:
            py_n = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        if "CLOUD_LIMIT" not in env:
            cloud_n = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        if "TERRAFORM_LIMIT" not in env:
            tf_n = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        return topic_bank_release_queues(
            site_id,
            repo,
            logf,
            content_limit=0,
            guide_limit=0,
            bank_caps={"python": py_n, "cloud": cloud_n, "terraform": tf_n},
        )

    if site_id in RELEASE_QUEUE_SITES:
        content_limit = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        guide_limit = int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
        return topic_bank_release_queues(
            site_id,
            repo,
            logf,
            content_limit=content_limit,
            guide_limit=guide_limit,
        )

    raise ValueError(f"release mode not configured for site: {site_id}")
