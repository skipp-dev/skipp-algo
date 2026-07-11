"""Truth-audit T1: _candle_ts must parse real FMP intraday date strings.

Real FMP intraday candles carry space-separated dates
(``"YYYY-MM-DD HH:MM:SS"``). The old ``if "T" in d`` gate sent those to a
``time.time()`` fallback, stamping every candle with serve-time and
collapsing the resampled bars onto a single bucket. These tests pin the
fix: distinct timestamps for distinct candles, in the correct order.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime

from smc_tv_bridge.smc_api import _candle_ts


def _expected(dt_str: str) -> int:
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def test_space_separated_intraday_date_parsed_not_serve_time() -> None:
    now = int(time.time())
    ts = _candle_ts({"date": "2026-06-15 09:45:00"})
    assert ts == _expected("2026-06-15 09:45:00")
    # Must NOT be the serve-time fallback.
    assert abs(ts - now) > 60


def test_intraday_candles_get_distinct_ordered_timestamps() -> None:
    dates = [
        "2026-06-15 09:30:00",
        "2026-06-15 09:31:00",
        "2026-06-15 09:32:00",
    ]
    stamps = [_candle_ts({"date": d}) for d in dates]
    # All distinct and strictly increasing — the property the resampler
    # relies on (the bug collapsed them to one identical serve-time value).
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == 3
    assert stamps[1] - stamps[0] == 60


def test_t_separated_date_still_parsed() -> None:
    assert _candle_ts({"date": "2026-03-27T09:30:00"}) == _expected(
        "2026-03-27T09:30:00"
    )


def test_bare_daily_date_parsed_as_utc_midnight() -> None:
    assert _candle_ts({"date": "2026-03-27"}) == _expected("2026-03-27")


def test_numeric_timestamp_field_preferred() -> None:
    assert _candle_ts({"timestamp": 1_700_000_000, "date": "2026-03-27"}) == (
        1_700_000_000
    )


def test_unparseable_date_falls_back_to_serve_time() -> None:
    now = int(time.time())
    ts = _candle_ts({"date": "not-a-date"})
    assert abs(ts - now) <= 2
