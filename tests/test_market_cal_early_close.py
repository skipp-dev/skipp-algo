from __future__ import annotations

from datetime import date

from newsstack_fmp._market_cal import (
    is_us_equity_early_close_day,
    regular_session_close_minutes,
)


def test_day_after_thanksgiving_is_early_close() -> None:
    # 2026-11-26 Thanksgiving -> 2026-11-27 Friday early close.
    d = date(2026, 11, 27)
    assert is_us_equity_early_close_day(d) is True
    assert regular_session_close_minutes(d) == 13 * 60


def test_regular_trading_day_uses_1600_close() -> None:
    d = date(2026, 11, 30)
    assert is_us_equity_early_close_day(d) is False
    assert regular_session_close_minutes(d) == 16 * 60


def test_non_trading_day_is_not_marked_early_close() -> None:
    # 2026-07-03 is full observed Independence Day closure.
    d = date(2026, 7, 3)
    assert is_us_equity_early_close_day(d) is False
    assert regular_session_close_minutes(d) == 16 * 60
