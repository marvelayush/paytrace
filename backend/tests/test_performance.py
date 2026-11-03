"""Brief's hard part: 1 lakh rows matched in under a minute. Slow: run with `pytest -m slow`."""

import pytest

from app.benchmark import run_benchmark


@pytest.mark.slow
def test_one_lakh_orders_end_to_end_under_a_minute(db, tmp_path):
    result = run_benchmark(db, tmp_path, n_orders=100_000)
    assert result.orders == 100_000
    assert result.end_to_end_s < 60, f"took {result.end_to_end_s:.1f} s"
    assert result.caught == result.injected
    assert result.false_alarms == 0
    assert result.auto_matched_pct >= 98
