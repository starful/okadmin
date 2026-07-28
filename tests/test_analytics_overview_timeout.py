"""Overview parallel job runner must not block past timeout."""

import time

from analytics_api import run_parallel_analytics_jobs
from analytics_cache import is_transient_analytics_error


def test_run_parallel_jobs_returns_on_hang():
    def ok():
        return {"ok": True}

    def hang():
        # Keep short: ThreadPoolExecutor atexit still joins workers.
        time.sleep(3)
        return {"ok": False}

    t0 = time.monotonic()
    out = run_parallel_analytics_jobs(
        {"fast": ok, "slow": hang},
        timeout_sec=1,
    )
    elapsed = time.monotonic() - t0
    assert out["fast"] == {"ok": True}
    assert out["slow"] == {"error": "조회 시간 초과"}
    # Must return near timeout, not after hang() finishes.
    assert elapsed < 2.0


def test_조회_시간_초과_is_transient():
    assert is_transient_analytics_error("조회 시간 초과")
    assert is_transient_analytics_error("Deadline Exceeded")
