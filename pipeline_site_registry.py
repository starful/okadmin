"""Per-site pipeline step definitions and dispatch."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pipeline_ensure import ensure_site_topic_bank
from pipeline_limits import (
    DEFAULT_CONTENT_LIMIT,
    DEFAULT_GUIDE_LIMIT,
    DEFAULT_KRCAMPUS_SCHOOL_LIMIT,
    DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT,
    MAX_CONTENT_LIMIT,
    MAX_GUIDE_LIMIT,
    int_env_allow_zero,
)
from pipeline_runner import (
    PostStep,
    Step,
    execute_pipeline,
    filter_pipeline_steps,
    pipeline_post_steps,
    run_ok_site_pipeline,
    starful_gcs_normalize,
)


def guide_cli_limit(env: dict[str, str], site_id: str) -> str:
    """Topic count for guide CLIs. 0 means skip guides (must not fall back to default)."""
    topics = int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
    topics = min(topics, MAX_GUIDE_LIMIT)
    if site_id == "okonsen":
        return str(topics * 2)
    return str(topics)


def insight_generator_argv(env: dict[str, str]) -> list[str]:
    return [
        "python3",
        "script/insight_generator.py",
        "--batch-missing",
        env["CONTENT_LIMIT"],
    ]


def guide_generator_argv(env: dict[str, str], site_id: str) -> list[str]:
    glimit = guide_cli_limit(env, site_id)
    if site_id in ("okramen", "statfacts"):
        return ["python3", "script/guide_generator.py", "--batch-missing", glimit]
    return ["python3", "script/guide_generator.py", glimit]


def content_limit_n(env: dict[str, str]) -> int:
    return min(int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT), MAX_CONTENT_LIMIT)


def guide_limit_n(env: dict[str, str]) -> int:
    return min(int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT), MAX_GUIDE_LIMIT)


def ok_series_content_steps(
    env: dict[str, str],
    site_id: str,
    *,
    item_step: Step,
    guide_first: bool = True,
    image_step: Step | None = None,
) -> list[Step]:
    head: list[Step] = []
    if guide_limit_n(env) > 0:
        head.append(("guides", "guide_generator", guide_generator_argv(env, site_id), 3600))
    if content_limit_n(env) > 0:
        item_head = [item_step]
    else:
        item_head = []
    if guide_first:
        ordered = head + item_head
    else:
        ordered = item_head + head
    if image_step is None:
        image_step = ("images", "fetch_images", ["python3", "script/fetch_images.py"], 2400)
    return ordered + [
        image_step,
        ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
        ("build", "build_data", ["python3", "script/build_data.py"], 600),
    ]


def _ensure(site_id: str):
    def fn(repo_p: Path, logf, env=None):
        return ensure_site_topic_bank(site_id, repo_p, logf, env=env)

    return fn


def pipeline_for_site(site_id: str, repo: Path, env: dict[str, str]) -> dict[str, Any]:
    """Run the content pipeline for one site (steps from registry)."""
    optional: list[Step] = []
    steps: list[Step] = []
    post_steps: list[PostStep] = list(pipeline_post_steps(site_id, env))
    ensure_fn: Callable | None = _ensure(site_id)

    if site_id == "okramen":
        limit = env["CONTENT_LIMIT"]
        if content_limit_n(env) > 0:
            steps.append(
                ("items", "ramen_generator", ["python3", "script/ramen_generator.py", limit], 3600)
            )
        if guide_limit_n(env) > 0:
            steps.append(("guides", "guide_generator", guide_generator_argv(env, site_id), 3600))
        steps.extend(
            [
                ("images_places", "fetch_images", ["python3", "script/fetch_images.py"], 2400),
                ("images", "generate_images", ["python3", "script/generate_images.py"], 2400),
                ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
                ("build", "build_data", ["python3", "script/build_data.py"], 600),
            ]
        )
        return run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure_fn, steps=steps)

    if site_id == "okonsen":
        limit = env["CONTENT_LIMIT"]
        steps = ok_series_content_steps(
            env,
            site_id,
            item_step=("items", "onsen_generator", ["python3", "script/onsen_generator.py", limit], 3600),
            guide_first=False,
        )
        return run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure_fn, steps=steps)

    if site_id == "okcaddie":
        limit = env["CONTENT_LIMIT"]
        steps = ok_series_content_steps(
            env,
            site_id,
            item_step=("items", "course_generator", ["python3", "script/course_generator.py", limit], 3600),
            guide_first=False,
        )
        return run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure_fn, steps=steps)

    if site_id == "statfacts":
        if content_limit_n(env) > 0:
            steps.append(("items", "insight_generator", insight_generator_argv(env), 3600))
        if guide_limit_n(env) > 0:
            steps.append(("guides", "guide_generator", guide_generator_argv(env, site_id), 3600))
        steps.extend(
            [
                ("images", "fetch_images", ["python3", "script/fetch_images.py"], 2400),
                ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
                ("build", "build_data", ["python3", "script/build_data.py"], 600),
            ]
        )
        return run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure_fn, steps=steps)

    if site_id == "krcare":
        # TourAPI medical clinics → images → nearby Stay/Food cache → optimize → build
        steps = [
            ("items", "collect_medical_clinics", ["python3", "script/collect_medical_clinics.py", "--skip-detail"], 3600),
            ("images", "fetch_images", ["python3", "script/fetch_images.py"], 2400),
            ("nearby", "fetch_nearby_pois", ["python3", "script/fetch_nearby_pois.py", "--replace", "--stay", "2", "--food", "2"], 1200),
            ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return execute_pipeline(
            site_id,
            repo,
            ensure_fn=None,
            steps=filter_pipeline_steps(steps, env),
            env=env,
            post_steps=post_steps,
        )

    if site_id == "starful.biz":
        steps = [
            ("guides", "generate_md_guides", ["python3", "scripts/generate_md_guides.py"], 3600),
            ("images", "generate_images", ["python3", "scripts/generate_images.py"], 600),
            ("images_opt", "resize_images", ["python3", "scripts/resize_images.py"], 900),
            ("img_names", "normalize_image_names", ["python3", "scripts/normalize_image_names.py"], 300),
            ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
        ]
        if pipeline_post_steps(site_id, env):
            post_steps = [("gcs_normalize", lambda repo, logf: starful_gcs_normalize(repo, logf))] + post_steps
        return execute_pipeline(
            site_id,
            repo,
            ensure_fn=ensure_fn,
            steps=filter_pipeline_steps(steps, env),
            env=env,
            post_steps=post_steps,
        )

    if site_id == "okpy":
        py_n = int_env_allow_zero(env, "PYTHON_LIMIT", DEFAULT_CONTENT_LIMIT)
        cloud_n = int_env_allow_zero(env, "CLOUD_LIMIT", DEFAULT_CONTENT_LIMIT)
        tf_n = int_env_allow_zero(env, "TERRAFORM_LIMIT", DEFAULT_CONTENT_LIMIT)
        # Fall back to CONTENT_LIMIT when specific limits unset via merge
        if "PYTHON_LIMIT" not in env:
            py_n = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        if "CLOUD_LIMIT" not in env:
            cloud_n = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        if "TERRAFORM_LIMIT" not in env:
            tf_n = int_env_allow_zero(env, "CONTENT_LIMIT", DEFAULT_CONTENT_LIMIT)
        if py_n > 0:
            steps.append(
                ("python", "python posts", ["python3", "scripts/generate_posts.py", "python"], 3600)
            )
        if cloud_n > 0:
            steps.append(
                ("cloud", "cloud posts", ["python3", "scripts/generate_posts.py", "cloud"], 3600)
            )
        if tf_n > 0:
            steps.append(
                (
                    "terraform",
                    "terraform posts",
                    ["python3", "scripts/generate_posts.py", "terraform"],
                    3600,
                )
            )
        return execute_pipeline(
            site_id,
            repo,
            ensure_fn=ensure_fn,
            steps=filter_pipeline_steps(steps, env),
            env=env,
            post_steps=post_steps,
        )

    if site_id == "jpcampus":
        guide_n = int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
        university_n = int_env_allow_zero(env, "UNIVERSITY_LIMIT", DEFAULT_CONTENT_LIMIT)
        if guide_n > 0:
            steps.append(("guides", "AI guides", ["python3", "scripts/2.generate_ai_guides.py"], 3600))
        if university_n > 0:
            steps.append(
                ("universities", "universities", ["python3", "scripts/1.collect_universities.py"], 3600)
            )
        steps.extend(
            [
                ("korean", "Korean content", ["python3", "scripts/3.create_korean_content.py"], 3600),
                ("featured", "featured articles", ["python3", "scripts/auto_generate_featured.py"], 1800),
                ("stay_images", "ensure_stay_images", ["python3", "scripts/ensure_stay_images.py"], 300),
                ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
            ]
        )
        optional = [("seo", "seo_guard", ["python3", "scripts/seo_guard.py"], 300)]
        return execute_pipeline(
            site_id,
            repo,
            ensure_fn=ensure_fn,
            steps=filter_pipeline_steps(steps, env),
            env=env,
            optional_steps=optional,
            post_steps=post_steps,
        )

    if site_id == "krcampus":
        guide_n = int_env_allow_zero(env, "GUIDE_LIMIT", DEFAULT_GUIDE_LIMIT)
        school_n = int_env_allow_zero(env, "SCHOOL_LIMIT", DEFAULT_KRCAMPUS_SCHOOL_LIMIT)
        university_n = int_env_allow_zero(env, "UNIVERSITY_LIMIT", DEFAULT_KRCAMPUS_UNIVERSITY_LIMIT)
        if guide_n > 0:
            steps.append(("guides", "AI guides", ["python3", "scripts/2.generate_ai_guides.py"], 3600))
        if school_n > 0:
            steps.append(
                ("schools", "language schools", ["python3", "scripts/1.collect_language_schools.py"], 3600)
            )
        if university_n > 0:
            steps.append(
                ("universities", "universities", ["python3", "scripts/1.collect_universities.py"], 3600)
            )
        with_ja = env.get("CONTENT_PIPELINE_WITH_JA", "0").strip().lower() in ("1", "true", "yes")
        post_en = [
            ("featured", "featured articles", ["python3", "scripts/auto_generate_featured.py"], 1800),
            (
                "images",
                "fetch_images",
                ["python3", "scripts/fetch_images.py", "--missing"],
                2400,
            ),
            ("images_opt", "optimize_images", ["python3", "scripts/optimize_images.py"], 900),
            ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
        ]
        if with_ja:
            steps.append(
                ("japanese", "Japanese translate", ["python3", "scripts/3.generate_japanese_native.py"], 3600)
            )
        steps.extend(post_en)
        optional = [("seo", "seo_guard", ["python3", "scripts/seo_guard.py"], 300)]
        return execute_pipeline(
            site_id,
            repo,
            ensure_fn=ensure_fn,
            steps=filter_pipeline_steps(steps, env),
            env=env,
            optional_steps=optional,
            post_steps=post_steps,
        )

    return {"ok": False, "error": f"no pipeline definition for {site_id}"}
