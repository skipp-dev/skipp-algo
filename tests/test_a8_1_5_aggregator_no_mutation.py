"""A8.1.5 falsification test: input frames must not be mutated by aggregators.

Pre-refactor falsifier: if this test passes against the CURRENT code (which still
calls ``detail = close_*.copy()`` inside each aggregator), then pandas-CoW or the
explicit copy already protects callers, and the spec'd Series-Build refactor is
unnecessary. If it FAILS pre-refactor, the refactor would also fail this same
test (since it intentionally drops the copy and mutates a fresh dict instead),
which is the intended green path.

In short:
  - pre-refactor green => refactor is placebo, abort.
  - pre-refactor green AND post-refactor green => refactor is safe; ship for OOM win.
  - pre-refactor red => caller-leak bug exists today (independent of OOM); fix is mandatory.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

import databento_volatility_screener as dvs


def _make_close_trade_detail() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": ["2026-03-05", "2026-03-05", "2026-03-06"],
            "symbol": ["aapl", "msft", "aapl"],
            "timestamp": [
                "2026-03-05 20:59:58+00:00",
                "2026-03-05 20:59:59+00:00",
                "2026-03-06 20:59:58+00:00",
            ],
            "ts_recv": [
                "2026-03-05 20:59:58.001+00:00",
                "2026-03-05 20:59:59.001+00:00",
                "2026-03-06 20:59:58.001+00:00",
            ],
            "ts_event": [
                "2026-03-05 20:59:58.000+00:00",
                "2026-03-05 20:59:59.000+00:00",
                "2026-03-06 20:59:58.000+00:00",
            ],
            "size": [100, 200, 150],
            "price": [101.5, 305.2, 102.1],
            "flags": [0, 0, 0],
            "sequence": [1, 2, 3],
            "publisher_id": [1, 1, 2],
            "side": ["B", "S", "B"],
            "venue_class": ["lit_exchange", "off_exchange_trf", "lit_exchange"],
        }
    )


def _make_close_outcome_detail() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": ["2026-03-05", "2026-03-05"],
            "symbol": ["aapl", "msft"],
            "timestamp": [
                "2026-03-05 21:00:00+00:00",
                "2026-03-05 21:01:00+00:00",
            ],
            "volume": [1000, 2000],
            "close": [101.5, 305.2],
            "high": [101.7, 305.5],
            "low": [101.3, 304.9],
        }
    )


def _snapshot(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return df.copy(deep=True), df.dtypes.copy()


def test_close_trade_aggregator_does_not_mutate_input() -> None:
    fixture = _make_close_trade_detail()
    snapshot_df, snapshot_dtypes = _snapshot(fixture)

    _ = dvs._build_close_trade_aggregates(
        fixture,
        trading_days=[date(2026, 3, 5), date(2026, 3, 6)],
        display_timezone="America/New_York",
    )

    pd.testing.assert_series_equal(fixture.dtypes, snapshot_dtypes, check_names=False)
    pd.testing.assert_frame_equal(fixture, snapshot_df, check_dtype=True)


def test_close_outcome_aggregator_does_not_mutate_input() -> None:
    fixture = _make_close_outcome_detail()
    snapshot_df, snapshot_dtypes = _snapshot(fixture)

    _ = dvs._build_close_outcome_aggregates(fixture)

    pd.testing.assert_series_equal(fixture.dtypes, snapshot_dtypes, check_names=False)
    pd.testing.assert_frame_equal(fixture, snapshot_df, check_dtype=True)
