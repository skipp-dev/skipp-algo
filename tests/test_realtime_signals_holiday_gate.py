"""WP-4: holiday gate in the realtime-signals market-hours check.

Without this gate the realtime engine treats NYSE full-day holidays as normal
trading days. FMP quotes carry the *previous* session's prints on a holiday, so
the engine would fire false A0/A1 breakouts across the whole watchlist (e.g. on
2026-07-03, the observed Independence Day closure). ``_is_within_market_hours``
must return ``False`` on a full-day NYSE holiday even during regular hours.
"""

from __future__ import annotations

import datetime as _dt

import open_prep.realtime_signals as rs


class _FrozenDatetime(_dt.datetime):
    """datetime subclass whose ``now(tz)`` returns a fixed instant."""

    _fixed: _dt.datetime

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is not None:
            return cls._fixed.astimezone(tz)
        return cls._fixed


def _freeze(monkeypatch, fixed_et: _dt.datetime) -> None:
    frozen = type("Frozen", (_FrozenDatetime,), {"_fixed": fixed_et})
    monkeypatch.setattr(rs, "datetime", frozen)


def _et(y: int, m: int, d: int, hh: int, mm: int) -> _dt.datetime:
    from zoneinfo import ZoneInfo

    return _dt.datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York"))


def test_market_hours_false_on_observed_holiday(monkeypatch) -> None:
    # 2026-07-04 is a Saturday → NYSE observes Independence Day on Fri 2026-07-03.
    _freeze(monkeypatch, _et(2026, 7, 3, 10, 0))
    assert rs.is_us_equity_trading_day(_dt.date(2026, 7, 3)) is False
    assert rs._is_within_market_hours() is False


def test_market_hours_true_on_regular_trading_day(monkeypatch) -> None:
    # 2026-07-06 is a Monday and a regular trading day, 10:00 ET is in-session.
    _freeze(monkeypatch, _et(2026, 7, 6, 10, 0))
    assert rs.is_us_equity_trading_day(_dt.date(2026, 7, 6)) is True
    assert rs._is_within_market_hours() is True


def test_market_hours_false_on_weekend(monkeypatch) -> None:
    _freeze(monkeypatch, _et(2026, 7, 4, 12, 0))  # Saturday
    assert rs._is_within_market_hours() is False


def test_market_hours_false_before_premarket_on_trading_day(monkeypatch) -> None:
    _freeze(monkeypatch, _et(2026, 7, 6, 3, 30))  # 03:30 ET, before 04:00
    assert rs._is_within_market_hours() is False
