"""OKPy per-bank release respects PYTHON/CLOUD/TERRAFORM limits."""

from topic_bank import release_site


def test_okpy_bank_caps_zero_skips_bank():
    # Pure unit: release_site with bank_caps should zero cloud/terraform when caps say so.
    # Uses real banks only if present; otherwise just verifies API accepts bank_caps.
    result = release_site(
        "okpy",
        content_limit=0,
        guide_limit=0,
        bank_caps={"python": 1, "cloud": 0, "terraform": 0},
    )
    by_bank = result.get("by_bank") or {}
    assert by_bank.get("cloud", 0) == 0
    assert by_bank.get("terraform", 0) == 0
    assert by_bank.get("python", 0) <= 1
