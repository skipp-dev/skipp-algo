"""Unit tests for the 20-day ATS baseline builder (WP-J).

Every test is network-free: the live builder is exercised with an injected
fake ``fetch`` callable, and the pure reduction is tested directly.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from scripts.build_ats_20d_baseline import (
    MEAN_KEY,
    N_DAYS_KEY,
    STD_KEY,
    build_and_write,
    build_baseline_for_symbols,
    compute_ats_baseline,
)


def _const_fetch(value: float | None):
    """A fake microstructure fetch returning a constant ATS for every day."""

    def _fetch(symbol, dataset, start, end, *, client=None, stype_in="raw_symbol"):
        return {"avg_trade_size": value} if value is not None else {}

    return _fetch


def test_compute_ats_baseline_mean_and_sample_std() -> None:
    """Mean and SAMPLE stdev are computed over the positive samples."""
    result = compute_ats_baseline([100.0, 200.0, 300.0])
    assert result[MEAN_KEY] == pytest.approx(200.0)
    assert result[STD_KEY] == pytest.approx(100.0)  # sample stdev of 100/200/300
    assert result[N_DAYS_KEY] == 3


def test_compute_ats_baseline_single_sample_zero_std() -> None:
    """A single sample has an undefined sample stdev -> defined as 0.0."""
    result = compute_ats_baseline([42.0])
    assert result[MEAN_KEY] == pytest.approx(42.0)
    assert result[STD_KEY] == 0.0
    assert result[N_DAYS_KEY] == 1


def test_compute_ats_baseline_empty_defaults() -> None:
    """An empty series yields zeroed defaults (no samples)."""
    assert compute_ats_baseline([]) == {MEAN_KEY: 0.0, STD_KEY: 0.0, N_DAYS_KEY: 0}


def test_compute_ats_baseline_drops_non_positive_and_nan() -> None:
    """Zero / negative / NaN / None days are excluded from the statistics."""
    result = compute_ats_baseline([100.0, 0.0, -5.0, float("nan"), 300.0, None])
    assert result[N_DAYS_KEY] == 2  # only 100 and 300 survive
    assert result[MEAN_KEY] == pytest.approx(200.0)


def test_compute_ats_baseline_rounds_to_six_dp() -> None:
    """Mean and std are rounded to six decimal places."""
    result = compute_ats_baseline([1.0, 2.0, 4.0])
    assert result[MEAN_KEY] == round(result[MEAN_KEY], 6)
    assert result[STD_KEY] == round(result[STD_KEY], 6)


def test_compute_ats_baseline_deterministic() -> None:
    """Repeated reduction of the same series is byte-stable."""
    series = [123.45, 678.9, 12.3, 456.7]
    assert compute_ats_baseline(series) == compute_ats_baseline(series)


def test_build_baseline_for_symbols_injected_fetch() -> None:
    """A constant daily ATS yields that mean with zero variance over N days."""
    result = build_baseline_for_symbols(
        ["AAPL"],
        "XNAS.ITCH",
        end_date=date(2024, 1, 22),
        lookback_days=5,
        fetch=_const_fetch(150.0),
    )
    assert result["AAPL"][N_DAYS_KEY] == 5
    assert result["AAPL"][MEAN_KEY] == pytest.approx(150.0)
    assert result["AAPL"][STD_KEY] == 0.0


def test_build_baseline_skips_empty_fetches() -> None:
    """Days with no usable trades are skipped -> zeroed baseline."""
    result = build_baseline_for_symbols(
        ["AAPL"],
        "XNAS.ITCH",
        end_date=date(2024, 1, 22),
        lookback_days=5,
        fetch=_const_fetch(None),
    )
    assert result["AAPL"] == {MEAN_KEY: 0.0, STD_KEY: 0.0, N_DAYS_KEY: 0}


def test_build_baseline_handles_fetch_errors() -> None:
    """A raising fetch is caught per-day and the symbol degrades to zeroes."""

    def _boom(symbol, dataset, start, end, *, client=None, stype_in="raw_symbol"):
        raise RuntimeError("databento down")

    result = build_baseline_for_symbols(
        ["AAPL"],
        "XNAS.ITCH",
        end_date=date(2024, 1, 22),
        lookback_days=5,
        fetch=_boom,
    )
    assert result["AAPL"][N_DAYS_KEY] == 0


def test_build_and_write_emits_committed_schema(tmp_path) -> None:
    """``build_and_write`` writes the payload it returns, with WP-K key names."""
    out = tmp_path / "ats_baseline_20d.json"
    payload = build_and_write(
        ["AAPL", "MSFT"],
        "XNAS.ITCH",
        end_date=date(2024, 1, 22),
        lookback_days=3,
        output_path=out,
        fetch=_const_fetch(100.0),
    )

    assert out.is_file()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == payload
    assert on_disk["lookback_days"] == 3
    assert on_disk["dataset"] == "XNAS.ITCH"
    assert set(on_disk["symbols"]) == {"AAPL", "MSFT"}
    assert on_disk["symbols"]["AAPL"][MEAN_KEY] == pytest.approx(100.0)
    # Output keys must match the WP-K flow-qualifier inputs.
    assert MEAN_KEY == "avg_trade_size_20d_mean"
    assert STD_KEY == "avg_trade_size_20d_std"
