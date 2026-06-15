"""Unit tests for `_run_fmp_intraday_bridge` (Step 6c).

Covers:
- Empty result when FMP key is absent.
- Graceful empty result when FMP raises a connection error.
- Correct window metrics computed from mocked 1-min bars.
- Bridge skipped when today already present in Databento intraday result.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.databento_production_export import _run_fmp_intraday_bridge

_TODAY = date(2026, 6, 15)

_SAMPLE_BARS = [
    # Newest-first order (FMP default) – bridge must sort ascending.
    {"date": "2026-06-15 09:45:00", "open": 102.0, "high": 103.0, "low": 101.5, "close": 102.5, "volume": 3000},
    {"date": "2026-06-15 09:31:00", "open": 100.5, "high": 101.0, "low": 100.0, "close": 101.0, "volume": 2000},
    {"date": "2026-06-15 09:30:00", "open": 100.0, "high": 101.0, "low": 99.5,  "close": 100.5, "volume": 1000},
    # Pre-market bar (before 09:30 ET).
    {"date": "2026-06-15 09:10:00", "open": 99.0,  "high": 99.5,  "low": 98.8,  "close": 99.2,  "volume": 500},
]

_DAILY_BARS = pd.DataFrame([
    {"trade_date": _TODAY, "symbol": "AAPL", "previous_close": 98.0, "close": 100.5},
])


def _make_mock_client(bars: list[dict[str, Any]] | Exception = _SAMPLE_BARS) -> MagicMock:
    client = MagicMock()
    if isinstance(bars, Exception):
        client.get_intraday_chart.side_effect = bars
    else:
        client.get_intraday_chart.return_value = bars
    return client


# ---------------------------------------------------------------------------
# Graceful-degradation tests
# ---------------------------------------------------------------------------

def test_empty_result_when_no_api_key():
    result = _run_fmp_intraday_bridge(
        "",
        today=_TODAY,
        universe_symbols={"AAPL"},
        window_start=time(9, 20),
        window_end=time(10, 0),
        daily_bars=_DAILY_BARS,
    )
    assert result.empty


def test_empty_result_when_fmp_raises():
    with patch(
        "scripts.databento_production_export._make_export_fmp_client",
        side_effect=RuntimeError("connection refused"),
    ):
        result = _run_fmp_intraday_bridge(
            "dummy_key",
            today=_TODAY,
            universe_symbols={"AAPL"},
            window_start=time(9, 20),
            window_end=time(10, 0),
            daily_bars=_DAILY_BARS,
        )
    assert result.empty


def test_empty_result_when_get_intraday_chart_raises():
    mock_client = _make_mock_client(RuntimeError("timeout"))
    with patch(
        "scripts.databento_production_export._make_export_fmp_client",
        return_value=mock_client,
    ):
        result = _run_fmp_intraday_bridge(
            "dummy_key",
            today=_TODAY,
            universe_symbols={"AAPL"},
            window_start=time(9, 20),
            window_end=time(10, 0),
            daily_bars=_DAILY_BARS,
        )
    assert result.empty


def test_empty_result_when_window_not_yet_open():
    """window_end <= window_start → bridge returns empty without calling FMP."""
    mock_client = _make_mock_client()
    with patch(
        "scripts.databento_production_export._make_export_fmp_client",
        return_value=mock_client,
    ):
        result = _run_fmp_intraday_bridge(
            "dummy_key",
            today=_TODAY,
            universe_symbols={"AAPL"},
            window_start=time(9, 30),
            window_end=time(9, 20),  # end < start
            daily_bars=_DAILY_BARS,
        )
    assert result.empty


# ---------------------------------------------------------------------------
# Metric-correctness tests
# ---------------------------------------------------------------------------

def test_window_metrics_computed_correctly():
    mock_client = _make_mock_client(_SAMPLE_BARS)
    with patch(
        "scripts.databento_production_export._make_export_fmp_client",
        return_value=mock_client,
    ):
        result = _run_fmp_intraday_bridge(
            "dummy_key",
            today=_TODAY,
            universe_symbols={"AAPL"},
            window_start=time(9, 20),
            window_end=time(10, 0),
            daily_bars=_DAILY_BARS,
        )

    assert not result.empty
    row = result.iloc[0]
    assert row["symbol"] == "AAPL"
    assert row["trade_date"] == _TODAY

    # Bars in window [09:20, 10:00]: 09:30, 09:31, 09:45 (3 bars).
    assert row["window_start_price"] == pytest.approx(100.0)   # first open
    assert row["current_price"]      == pytest.approx(102.5)   # last close
    assert row["window_high"]        == pytest.approx(103.0)
    assert row["window_low"]         == pytest.approx(99.5)
    assert row["window_volume"]      == pytest.approx(6000.0)
    assert row["seconds_in_window"]  == 3 * 60

    # Premarket price = last pre-market bar close (09:10 → 99.2).
    assert row["premarket_price"] == pytest.approx(99.2)
    assert bool(row["has_premarket_data"]) is True

    # Market-open price = bar at 09:30 open = 100.0.
    assert row["market_open_price"] == pytest.approx(100.0)

    # prev_close from daily_bars → 98.0.
    assert row["previous_close"] == pytest.approx(98.0)

    # current_price_timestamp must be a UTC-aware pd.Timestamp so the column
    # stays homogeneous after pd.concat with Databento rows (which carry UTC
    # Timestamps); a naive ET string would cause a 4-5h timezone error when
    # the pipeline later normalises via pd.to_datetime(..., utc=True).
    ts = row["current_price_timestamp"]
    assert isinstance(ts, pd.Timestamp), f"expected pd.Timestamp, got {type(ts)}"
    assert ts.tzinfo is not None and ts.utcoffset().total_seconds() == 0, (
        f"current_price_timestamp must be tz-aware UTC, got tzinfo={ts.tzinfo!r}"
    )


def test_schema_columns_match_intraday_frame():
    """Bridge output must contain all columns expected by run_intraday_screen."""
    expected_columns = {
        "trade_date", "symbol", "previous_close", "premarket_price",
        "market_open_price", "window_start_price", "current_price",
        "current_price_timestamp", "window_high", "window_low",
        "window_volume", "seconds_in_window", "window_return_pct",
        "window_range_pct", "realized_vol_pct", "has_premarket_data",
        "prev_close_to_premarket_abs", "prev_close_to_premarket_pct",
        "premarket_to_open_abs", "premarket_to_open_pct",
        "open_to_current_abs", "open_to_current_pct",
    }
    mock_client = _make_mock_client(_SAMPLE_BARS)
    with patch(
        "scripts.databento_production_export._make_export_fmp_client",
        return_value=mock_client,
    ):
        result = _run_fmp_intraday_bridge(
            "dummy_key",
            today=_TODAY,
            universe_symbols={"AAPL"},
            window_start=time(9, 20),
            window_end=time(10, 0),
            daily_bars=_DAILY_BARS,
        )
    assert expected_columns.issubset(set(result.columns))


# ---------------------------------------------------------------------------
# Step 6c integration: bridge skipped when today already in Databento result
# ---------------------------------------------------------------------------

def test_today_present_in_intraday_dates_set(monkeypatch):
    """Verifies the date-membership helper used by the Step 6c guard.

    The Step 6c guard in run_production_export_pipeline skips the bridge when
    ``today_et in intraday_dates``.  This test checks only that the dates-set
    construction logic (pd.to_datetime + .dt.date) correctly detects today’s
    presence — NOT that the guard itself is wired (end-to-end integration only).
    """
    intraday_with_today = pd.DataFrame([{"trade_date": _TODAY, "symbol": "AAPL", "current_price": 105.0}])
    intraday_dates = set(
        pd.to_datetime(intraday_with_today["trade_date"], errors="coerce").dt.date
    )
    assert _TODAY in intraday_dates  # confirms guard would skip the bridge call


def test_weekend_date_absent_from_trading_days():
    """Documents the weekend/holiday path for the Step 6c guard.

    The guard in run_production_export_pipeline uses ``today_et not in
    trading_days`` to skip the bridge on non-trading days.  This test
    verifies only the set-membership property (a Saturday is not in a
    Mon–Thu trading_days list) — NOT that the guard itself is wired
    (end-to-end integration only).
    """
    # Simulate a Saturday: today is not a trading day.
    saturday = date(2026, 6, 13)  # Saturday (2026-06-14 was a Sunday — fixed)
    trading_days = [date(2026, 6, 9), date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]  # Mon–Thu, Fri=not included so Sat is out
    assert saturday not in set(trading_days)  # guard prevents bridge call


# ---------------------------------------------------------------------------
# F1 edge-case coverage: empty daily_bars / symbol not in daily_bars
# ---------------------------------------------------------------------------

def test_empty_daily_bars_returns_none_prev_close():
    """Bridge must not raise when daily_bars is empty (prev_close falls back to None).

    When called for a symbol on a day where daily_bars has no matching row
    (e.g. first run before daily bars are finalized, or a symbol added
    mid-session), the bridge should still return a valid row with
    ``previous_close=None`` and None for all prev-close-derived columns.
    """
    mock_client = _make_mock_client(_SAMPLE_BARS)
    with patch(
        "scripts.databento_production_export._make_export_fmp_client",
        return_value=mock_client,
    ):
        result = _run_fmp_intraday_bridge(
            "dummy_key",
            today=_TODAY,
            universe_symbols={"AAPL"},
            window_start=time(9, 20),
            window_end=time(10, 0),
            daily_bars=pd.DataFrame(),  # empty — no previous_close available
        )
    assert not result.empty, "bridge should return a row even without daily_bars"
    row = result.iloc[0]
    assert row["previous_close"] is None or pd.isna(row["previous_close"]), (
        f"expected None/NaN for previous_close, got {row['previous_close']!r}"
    )
    # Transition columns that depend on prev_close must also be None/NaN, not raise.
    for col in ("prev_close_to_premarket_abs", "prev_close_to_premarket_pct"):
        assert row[col] is None or pd.isna(row[col]), (
            f"{col} should be None/NaN when prev_close is missing, got {row[col]!r}"
        )


def test_symbol_absent_from_daily_bars_prev_close_is_none():
    """Symbol in universe_symbols but absent from daily_bars.previous_close → None.

    Verifies the ``prev_close_map.get(sym)`` fallback: the row is still
    produced with all price metrics intact; only the previous-close-derived
    columns are None.  Exercises a different code path from the empty-frame
    case because the DataFrame is non-empty but the symbol is missing.
    """
    daily_bars_other_symbol = pd.DataFrame([
        {"trade_date": _TODAY, "symbol": "MSFT", "previous_close": 420.0, "close": 422.0},
    ])
    mock_client = _make_mock_client(_SAMPLE_BARS)
    with patch(
        "scripts.databento_production_export._make_export_fmp_client",
        return_value=mock_client,
    ):
        result = _run_fmp_intraday_bridge(
            "dummy_key",
            today=_TODAY,
            universe_symbols={"AAPL"},
            window_start=time(9, 20),
            window_end=time(10, 0),
            daily_bars=daily_bars_other_symbol,  # AAPL missing
        )
    assert not result.empty
    row = result.iloc[0]
    assert row["previous_close"] is None or pd.isna(row["previous_close"])
    # Price columns from intraday bars should still be populated.
    assert row["current_price"] == pytest.approx(102.5)
    assert row["window_start_price"] == pytest.approx(100.0)

