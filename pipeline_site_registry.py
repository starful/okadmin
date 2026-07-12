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
    bounded_limit,
    int_env_allow_zero,
)
from pipeline_runner import (
    PostStep,
    Step,
    execute_pipeline,
    pipeline_post_steps,
    run_ok_site_pipeline,
    starful_gcs_normalize,
)


def guide_cli_limit(env: dict[str, str], site_id: str) -> str:
    topics = bounded_limit(env, "GUIDE_LIMIT", default=DEFAULT_GUIDE_LIMIT, ceiling=20)
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
    if site_id in ("okramen", "okstats"):
        return ["python3", "script/guide_generator.py", "--batch-missing", glimit]
    return ["python3", "script/guide_generator.py", glimit]


def ok_series_content_steps(
    env: dict[str, str],
    site_id: str,
    *,
    item_step: Step,
    guide_first: bool = True,
    image_step: Step | None = None,
) -> list[Step]:
    guide_step: Step = ("guides", "guide_generator", guide_generator_argv(env, site_id), 3600)
    head: list[Step] = [guide_step, item_step] if guide_first else [item_step, guide_step]
    if image_step is None:
        image_step = ("images", "fetch_images", ["python3", "script/fetch_images.py"], 2400)
    return head + [
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
    post_steps: list[PostStep] = list(pipeline_post_steps(site_id))
    ensure_fn: Callable | None = _ensure(site_id)

    if site_id == "okramen":
        limit = env["CONTENT_LIMIT"]
        steps = [
            ("items", "ramen_generator", ["python3", "script/ramen_generator.py", limit], 3600),
            ("guides", "guide_generator", guide_generator_argv(env, site_id), 3600),
            ("images_places", "fetch_images", ["python3", "script/fetch_images.py"], 2400),
            ("images", "generate_images", ["python3", "script/generate_images.py"], 2400),
            ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
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

    if site_id == "okstats":
        steps = [
            ("items", "insight_generator", insight_generator_argv(env), 3600),
            ("guides", "guide_generator", guide_generator_argv(env, site_id), 3600),
            ("images", "fetch_images", ["python3", "script/fetch_images.py"], 2400),
            ("images_opt", "optimize_images", ["python3", "script/optimize_images.py"], 900),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return run_ok_site_pipeline(site_id, repo, env, ensure_fn=ensure_fn, steps=steps)

    if site_id == "starful.biz":
        steps = [
            ("guides", "generate_md_guides", ["python3", "scripts/generate_md_guides.py"], 3600),
            ("images", "generate_images", ["python3", "scripts/generate_images.py"], 600),
            ("images_opt", "resize_images", ["python3", "scripts/resize_images.py"], 900),
            ("img_names", "normalize_image_names", ["python3", "scripts/normalize_image_names.py"], 300),
            ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
        ]
        post_steps = [("gcs_normalize", lambda repo, logf: starful_gcs_normalize(repo, logf))] + post_steps
        return execute_pipeline(
            site_id,
            repo,
            ensure_fn=ensure_fn,
            steps=steps,
            env=env,
            post_steps=post_steps,
        )

    if site_id == "hatena":
        max_posts = env["HATENA_MAX_POSTS"]
        steps = [
            ("py", "unified_poster py", ["python3", "unified_poster.py", "py", "--max_posts", max_posts], 3600),
            ("cloud", "unified_poster cloud", ["python3", "unified_poster.py", "cloud", "--max_posts", max_posts], 3600),
        ]
        return execute_pipeline(site_id, repo, ensure_fn=ensure_fn, steps=steps, env=env)

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
            steps=steps,
            env=env,
            optional_steps=optional,
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
            steps=steps,
            env=env,
            optional_steps=optional,
            post_steps=post_steps,
        )

    return {"ok": False, "error": f"no pipeline definition for {site_id}"}
