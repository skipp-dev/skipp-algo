"""C-sprint deep-review C1 regression tests for FeatureImportanceCollector.

Pins the new ``reset_count`` observability counter so callers/tests can
detect ring-buffer churn (e.g., repeated hot-restarts wiping samples
before any meaningful aggregation).
"""

from __future__ import annotations

from datetime import date

from open_prep.outcomes import FeatureImportanceCollector


def test_reset_count_starts_at_zero() -> None:
    c = FeatureImportanceCollector()
    assert c.reset_count == 0
    assert c.sample_count == 0


def test_reset_count_unchanged_when_buffer_empty(tmp_path, monkeypatch) -> None:
    """``flush_to_disk`` short-circuits on empty buffer; counter must
    not advance because no flush actually happened."""

    monkeypatch.setattr(
        "open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path
    )
    c = FeatureImportanceCollector()
    out = c.flush_to_disk(run_date=date(2024, 1, 1))
    assert out is None
    assert c.reset_count == 0


def test_reset_count_increments_on_successful_flush(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "open_prep.outcomes.FEATURE_IMPORTANCE_DIR", tmp_path
    )
    c = FeatureImportanceCollector()
    c.record(
        "AAPL",
        {"daily_change_score": 1.0},
        total_score=1.0,
        run_date="2024-01-01",
    )
    assert c.sample_count == 1
    out = c.flush_to_disk(run_date=date(2024, 1, 1))
    assert out is not None and out.exists()
    assert c.reset_count == 1
    assert c.sample_count == 0
    # Second cycle increments again.
    c.record(
        "MSFT",
        {"daily_change_score": 0.5},
        total_score=0.5,
        run_date="2024-01-02",
    )
    c.flush_to_disk(run_date=date(2024, 1, 2))
    assert c.reset_count == 2
