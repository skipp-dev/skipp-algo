"""Tests for scripts/smc_calendar_collector.py."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_calendar_collector import collect_earnings_and_macro

TODAY = date(2026, 3, 27)  # Friday
TOMORROW = date(2026, 3, 30)  # Monday — next US-equity trading day after Fri 03-27


class TestNoEarnings:

    def test_no_earnings(self) -> None:
        result = collect_earnings_and_macro(["AAPL"], reference_date=TODAY)
        assert result["earnings_today_tickers"] == ""
        assert result["earnings_tomorrow_tickers"] == ""
        assert result["earnings_bmo_tickers"] == ""
        assert result["earnings_amc_tickers"] == ""
        assert result["high_impact_macro_today"] is False
        assert result["macro_event_name"] == ""
        assert result["macro_event_time"] == ""


class TestEarningsTodayBMO:

    def test_earnings_today_bmo(self) -> None:
        earnings = [{"symbol": "AAPL", "date": "2026-03-27", "timing": "bmo"}]
        result = collect_earnings_and_macro(
            ["AAPL", "MSFT"], earnings_data=earnings, reference_date=TODAY
        )
        assert "AAPL" in result["earnings_today_tickers"]
        assert "AAPL" in result["earnings_bmo_tickers"]
        assert result["earnings_amc_tickers"] == ""

    def test_earnings_today_amc(self) -> None:
        earnings = [{"symbol": "GOOG", "date": "2026-03-27", "timing": "amc"}]
        result = collect_earnings_and_macro(
            ["GOOG"], earnings_data=earnings, reference_date=TODAY
        )
        assert "GOOG" in result["earnings_today_tickers"]
        assert "GOOG" in result["earnings_amc_tickers"]
        assert result["earnings_bmo_tickers"] == ""


class TestEarningsTomorrow:

    def test_earnings_tomorrow(self) -> None:
        # MSFT reports Mon 03-30 — the next trading day after Fri 03-27 (skipping the weekend).
        earnings = [{"symbol": "MSFT", "date": "2026-03-30", "timing": "bmo"}]
        result = collect_earnings_and_macro(
            ["MSFT"], earnings_data=earnings, reference_date=TODAY
        )
        assert "MSFT" in result["earnings_tomorrow_tickers"]
        assert result["earnings_today_tickers"] == ""


class TestMacroFOMCToday:

    def test_macro_fomc_today(self) -> None:
        events = [
            {"name": "FOMC Minutes", "time_utc": "2026-03-27T18:00:00+00:00", "impact": "high"},
        ]
        result = collect_earnings_and_macro(
            ["AAPL"], macro_events=events, reference_date=TODAY
        )
        assert result["high_impact_macro_today"] is True
        assert "FOMC" in result["macro_event_name"]
        assert "ET" in result["macro_event_time"]


class TestNoMacro:

    def test_no_macro(self) -> None:
        result = collect_earnings_and_macro(["AAPL"], reference_date=TODAY)
        assert result["high_impact_macro_today"] is False
        assert result["macro_event_name"] == ""

    def test_low_impact_ignored(self) -> None:
        events = [
            {"name": "Redbook Index", "time_utc": "2026-03-27T14:00:00+00:00", "impact": "low"},
        ]
        result = collect_earnings_and_macro(
            ["AAPL"], macro_events=events, reference_date=TODAY
        )
        assert result["high_impact_macro_today"] is False


class TestSymbolFilter:

    def test_symbol_filter(self) -> None:
        earnings = [
            {"symbol": "AAPL", "date": "2026-03-27", "timing": "bmo"},
            {"symbol": "XYZ", "date": "2026-03-27", "timing": "bmo"},
        ]
        result = collect_earnings_and_macro(
            ["AAPL"], earnings_data=earnings, reference_date=TODAY
        )
        assert "AAPL" in result["earnings_today_tickers"]
        assert "XYZ" not in result["earnings_today_tickers"]


class TestMultipleMacroPicksNearest:

    def test_picks_earliest(self) -> None:
        events = [
            {"name": "CPI Release", "time_utc": "2026-03-27T12:30:00+00:00"},
            {"name": "FOMC Decision", "time_utc": "2026-03-27T18:00:00+00:00"},
        ]
        result = collect_earnings_and_macro(
            ["AAPL"], macro_events=events, reference_date=TODAY
        )
        assert result["high_impact_macro_today"] is True
        assert "CPI" in result["macro_event_name"]


class TestReturnShape:

    def test_return_keys(self) -> None:
        result = collect_earnings_and_macro([], reference_date=TODAY)
        assert set(result.keys()) == {
            "earnings_today_tickers", "earnings_tomorrow_tickers",
            "earnings_bmo_tickers", "earnings_amc_tickers",
            "high_impact_macro_today", "macro_event_name", "macro_event_time",
        }


class TestWeekendSkip:
    """Lane 6 — ``tomorrow`` must skip weekends and US-equity holidays."""

    def test_friday_tomorrow_is_monday_not_saturday(self) -> None:
        # Friday → Saturday earnings should NOT be classified as "tomorrow".
        earnings = [{"symbol": "MSFT", "date": "2026-03-28", "timing": "bmo"}]
        result = collect_earnings_and_macro(
            ["MSFT"], earnings_data=earnings, reference_date=TODAY
        )
        assert result["earnings_tomorrow_tickers"] == ""

    def test_friday_monday_earnings_classified_as_tomorrow(self) -> None:
        earnings = [{"symbol": "MSFT", "date": "2026-03-30", "timing": "bmo"}]
        result = collect_earnings_and_macro(
            ["MSFT"], earnings_data=earnings, reference_date=TODAY
        )
        assert "MSFT" in result["earnings_tomorrow_tickers"]

    def test_explicit_next_trading_date_override(self) -> None:
        earnings = [{"symbol": "TSLA", "date": "2026-04-02", "timing": "amc"}]
        result = collect_earnings_and_macro(
            ["TSLA"],
            earnings_data=earnings,
            reference_date=date(2026, 4, 1),
            next_trading_date=date(2026, 4, 2),
        )
        assert "TSLA" in result["earnings_tomorrow_tickers"]
