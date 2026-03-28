"""Tests for scripts/smc_calendar_collector.py."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_calendar_collector import collect_earnings_and_macro

TODAY = date(2026, 3, 28)
TOMORROW = date(2026, 3, 29)


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
        earnings = [{"symbol": "AAPL", "date": "2026-03-28", "timing": "bmo"}]
        result = collect_earnings_and_macro(
            ["AAPL", "MSFT"], earnings_data=earnings, reference_date=TODAY
        )
        assert "AAPL" in result["earnings_today_tickers"]
        assert "AAPL" in result["earnings_bmo_tickers"]
        assert result["earnings_amc_tickers"] == ""

    def test_earnings_today_amc(self) -> None:
        earnings = [{"symbol": "GOOG", "date": "2026-03-28", "timing": "amc"}]
        result = collect_earnings_and_macro(
            ["GOOG"], earnings_data=earnings, reference_date=TODAY
        )
        assert "GOOG" in result["earnings_today_tickers"]
        assert "GOOG" in result["earnings_amc_tickers"]
        assert result["earnings_bmo_tickers"] == ""


class TestEarningsTomorrow:

    def test_earnings_tomorrow(self) -> None:
        earnings = [{"symbol": "MSFT", "date": "2026-03-29", "timing": "bmo"}]
        result = collect_earnings_and_macro(
            ["MSFT"], earnings_data=earnings, reference_date=TODAY
        )
        assert "MSFT" in result["earnings_tomorrow_tickers"]
        assert result["earnings_today_tickers"] == ""


class TestMacroFOMCToday:

    def test_macro_fomc_today(self) -> None:
        events = [
            {"name": "FOMC Minutes", "time_utc": "2026-03-28T18:00:00+00:00", "impact": "high"},
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
            {"name": "Redbook Index", "time_utc": "2026-03-28T14:00:00+00:00", "impact": "low"},
        ]
        result = collect_earnings_and_macro(
            ["AAPL"], macro_events=events, reference_date=TODAY
        )
        assert result["high_impact_macro_today"] is False


class TestSymbolFilter:

    def test_symbol_filter(self) -> None:
        earnings = [
            {"symbol": "AAPL", "date": "2026-03-28", "timing": "bmo"},
            {"symbol": "XYZ", "date": "2026-03-28", "timing": "bmo"},
        ]
        result = collect_earnings_and_macro(
            ["AAPL"], earnings_data=earnings, reference_date=TODAY
        )
        assert "AAPL" in result["earnings_today_tickers"]
        assert "XYZ" not in result["earnings_today_tickers"]


class TestMultipleMacroPicksNearest:

    def test_picks_earliest(self) -> None:
        events = [
            {"name": "CPI Release", "time_utc": "2026-03-28T12:30:00+00:00"},
            {"name": "FOMC Decision", "time_utc": "2026-03-28T18:00:00+00:00"},
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
