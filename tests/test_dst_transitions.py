"""DST-transition contract tests for US-equity timezone handling.

Locks the behaviour around the spring-forward (2nd Sunday of March)
and fall-back (1st Sunday of November) boundaries so a future
regression to fixed-offset arithmetic is caught immediately.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from newsstack_fmp._market_cal import is_us_equity_trading_day

_ET = ZoneInfo("America/New_York")

# Spring forward 2026 = Sunday March 8. Fall back 2026 = Sunday November 1.
# In 2027: spring March 14, fall November 7.

class TestSpringForward:
    def test_friday_before_spring_forward_2026_is_trading_day(self):
        assert is_us_equity_trading_day(date(2026, 3, 6)) is True
    def test_spring_forward_sunday_2026_is_not_trading_day(self):
        assert is_us_equity_trading_day(date(2026, 3, 8)) is False
    def test_monday_after_spring_forward_2026_is_trading_day(self):
        assert is_us_equity_trading_day(date(2026, 3, 9)) is True
    def test_et_offset_changes_across_spring_forward_2026(self):
        pre = datetime(2026, 3, 7, 12, 0, tzinfo=_ET).utcoffset()
        post = datetime(2026, 3, 9, 12, 0, tzinfo=_ET).utcoffset()
        assert pre == timedelta(hours=-5)   # EST
        assert post == timedelta(hours=-4)  # EDT

class TestFallBack:
    def test_friday_before_fall_back_2026_is_trading_day(self):
        assert is_us_equity_trading_day(date(2026, 10, 30)) is True
    def test_fall_back_sunday_2026_is_not_trading_day(self):
        assert is_us_equity_trading_day(date(2026, 11, 1)) is False
    def test_monday_after_fall_back_2026_is_trading_day(self):
        assert is_us_equity_trading_day(date(2026, 11, 2)) is True
    def test_et_offset_changes_across_fall_back_2026(self):
        pre = datetime(2026, 10, 31, 12, 0, tzinfo=_ET).utcoffset()
        post = datetime(2026, 11, 2, 12, 0, tzinfo=_ET).utcoffset()
        assert pre == timedelta(hours=-4)   # EDT
        assert post == timedelta(hours=-5)  # EST

class TestSpringForward2027:
    def test_spring_forward_sunday_2027_is_not_trading_day(self):
        assert is_us_equity_trading_day(date(2027, 3, 14)) is False
    def test_monday_after_spring_forward_2027_is_trading_day(self):
        assert is_us_equity_trading_day(date(2027, 3, 15)) is True

class TestFixedOffsetForbidden:
    """Pin the contract: production code must use ZoneInfo, not timedelta-offsets."""
    def test_smc_calendar_collector_uses_zoneinfo(self):
        import scripts.smc_calendar_collector as mod
        with open(mod.__file__, encoding="utf-8") as _f:
            src = _f.read()
        assert "timedelta(hours=-4)" not in src, \
            "smc_calendar_collector.py must not hard-code EDT offset"
        assert "timedelta(hours=-5)" not in src, \
            "smc_calendar_collector.py must not hard-code EST offset"
