"""Per-run limit wiring: UI counts must reach generators as-is (0 = skip)."""

from pipeline_site_registry import (
    content_limit_n,
    guide_cli_limit,
    guide_generator_argv,
    guide_limit_n,
    ok_series_content_steps,
)


def test_guide_cli_limit_zero_stays_zero():
    env = {"GUIDE_LIMIT": "0", "CONTENT_LIMIT": "1"}
    assert guide_cli_limit(env, "okramen") == "0"
    assert guide_cli_limit(env, "okcaddie") == "0"
    assert guide_cli_limit(env, "okonsen") == "0"


def test_guide_cli_limit_respects_user_count():
    env = {"GUIDE_LIMIT": "1", "CONTENT_LIMIT": "2"}
    assert guide_cli_limit(env, "okramen") == "1"
    assert guide_cli_limit(env, "okonsen") == "2"  # en+ko budget


def test_zero_limits_skip_item_and_guide_steps():
    env = {"CONTENT_LIMIT": "0", "GUIDE_LIMIT": "0"}
    steps = ok_series_content_steps(
        env,
        "okcaddie",
        item_step=("items", "course_generator", ["python3", "script/course_generator.py", "0"], 3600),
        guide_first=False,
    )
    ids = [s[0] for s in steps]
    assert "items" not in ids
    assert "guides" not in ids
    assert "build" in ids


def test_user_counts_include_items_and_guides():
    env = {"CONTENT_LIMIT": "1", "GUIDE_LIMIT": "1"}
    assert content_limit_n(env) == 1
    assert guide_limit_n(env) == 1
    steps = ok_series_content_steps(
        env,
        "okcaddie",
        item_step=("items", "course_generator", ["python3", "script/course_generator.py", "1"], 3600),
        guide_first=False,
    )
    ids = [s[0] for s in steps]
    assert ids.index("items") < ids.index("guides")
    assert guide_generator_argv(env, "okramen")[-1] == "1"


def test_default_profile_skips_image_steps():
    from pipeline_runner import filter_pipeline_steps

    env = {"CONTENT_PIPELINE_WITH_IMAGES": "0", "CONTENT_LIMIT": "1", "GUIDE_LIMIT": "1"}
    steps = ok_series_content_steps(
        env,
        "okcaddie",
        item_step=("items", "course_generator", ["python3", "script/course_generator.py", "1"], 3600),
        guide_first=False,
    )
    filtered = filter_pipeline_steps(steps, env)
    ids = [s[0] for s in filtered]
    assert "images" not in ids
    assert "images_opt" not in ids
    assert "build" in ids
    assert "items" in ids


def test_images_on_keeps_image_steps():
    from pipeline_runner import filter_pipeline_steps

    env = {"CONTENT_PIPELINE_WITH_IMAGES": "1", "CONTENT_LIMIT": "1", "GUIDE_LIMIT": "1"}
    steps = ok_series_content_steps(
        env,
        "okcaddie",
        item_step=("items", "course_generator", ["python3", "script/course_generator.py", "1"], 3600),
        guide_first=False,
    )
    filtered = filter_pipeline_steps(steps, env)
    ids = [s[0] for s in filtered]
    assert "images" in ids
    assert "images_opt" in ids
    assert "build" in ids


def test_image_steps_are_soft_continue():
    from pipeline_runner import _SOFT_CONTINUE_STEPS

    assert "images" in _SOFT_CONTINUE_STEPS
    assert "images_opt" in _SOFT_CONTINUE_STEPS
    assert "images_places" in _SOFT_CONTINUE_STEPS