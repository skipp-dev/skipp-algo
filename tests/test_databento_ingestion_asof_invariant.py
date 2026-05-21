"""Contract pin: Databento request-end clamping is `asof`-safe.

Audit "SkippALGO Quant Audit 2026-05-21" claim #2 (Databento cache leakage)
asserted that cache ingestion lacks timestamp validation. The actual mitigation
lives in ``databento_client._clamp_request_end`` + ``_daily_request_end_exclusive``,
which bound every Databento request end to the schema's published
``available_end`` BEFORE the network call. This file pins that invariant so the
clamp cannot silently regress to "fetch future bars" behavior.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from databento_client import (
    _clamp_request_end,
    _daily_request_end_exclusive,
    _exclusive_ohlcv_1s_end,
)


class TestClampRequestEndAsofInvariant:
    def test_clamp_never_exceeds_available_end(self) -> None:
        available = pd.Timestamp("2026-05-20T20:00:00Z")
        requested_future = pd.Timestamp("2026-05-21T20:00:00Z")
        clamped = _clamp_request_end(requested_future, available)
        assert clamped <= available
        assert clamped == available

    def test_clamp_passes_through_when_requested_within_available(self) -> None:
        available = pd.Timestamp("2026-05-20T20:00:00Z")
        requested_past = pd.Timestamp("2026-05-19T16:00:00Z")
        assert _clamp_request_end(requested_past, available) == requested_past

    def test_clamp_passes_through_when_available_unknown(self) -> None:
        requested = pd.Timestamp("2026-05-21T20:00:00Z")
        assert _clamp_request_end(requested, None) == requested

    def test_clamp_equal_endpoints_yields_either(self) -> None:
        ts = pd.Timestamp("2026-05-20T20:00:00Z")
        assert _clamp_request_end(ts, ts) == ts


class TestDailyRequestEndExclusiveAsofInvariant:
    def test_daily_end_clamped_to_available_end(self) -> None:
        last_trading_day = date(2026, 5, 21)
        available = pd.Timestamp("2026-05-20T20:00:00Z")
        end_date = _daily_request_end_exclusive(last_trading_day, available)
        assert end_date <= date(2026, 5, 21)

    def test_daily_end_unbounded_when_available_unknown(self) -> None:
        last_trading_day = date(2026, 5, 21)
        end_date = _daily_request_end_exclusive(last_trading_day, None)
        assert end_date == date(2026, 5, 22)


class TestOhlcv1sExclusiveEndAsofInvariant:
    def test_naive_input_is_localized_to_utc(self) -> None:
        result = _exclusive_ohlcv_1s_end(pd.Timestamp("2026-05-20T20:00:00"))
        assert result.tzinfo is not None
        assert result == pd.Timestamp("2026-05-20T20:00:01Z")

    def test_aware_input_is_preserved(self) -> None:
        ts = pd.Timestamp("2026-05-20T20:00:00Z")
        assert _exclusive_ohlcv_1s_end(ts) == ts + pd.Timedelta(seconds=1)
