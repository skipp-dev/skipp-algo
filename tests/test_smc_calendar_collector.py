"""Tests for scripts/smc_calendar_collector.py."""
from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timezone
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


class _FakeDateTime(datetime):
    """``datetime`` subclass that returns a pinned UTC instant from ``now()``."""

    _PINNED_UTC = datetime(2026, 4, 28, 2, 30, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return cls._PINNED_UTC.replace(tzinfo=None)
        return cls._PINNED_UTC.astimezone(tz)


class TestUSEasternAnchoring:
    """Re-pin the ET-anchoring contract from PR #364 / Audit v3.

    PR #369's weekend-skip fix re-introduced ``date.today()`` for the
    ``today`` reference, undoing the v3 ET-anchor. These tests pin the
    contract again so on-call doesn't get woken up by spurious
    ``earnings_today↔earnings_tomorrow`` flips around UTC midnight.
    """

    def test_today_anchored_on_us_eastern(self, monkeypatch: object) -> None:
        # 2026-04-28 02:30 UTC == 2026-04-27 22:30 ET (EDT, UTC-4).
        # On a UTC server, ``date.today()`` would advance to 2026-04-28
        # and silently push AAPL's AMC earnings into tomorrow.
        import smc_calendar_collector as mod

        monkeypatch.setattr(mod, "datetime", _FakeDateTime)  # type: ignore[attr-defined]
        result = collect_earnings_and_macro(
            symbols=["AAPL"],
            earnings_data=[
                {"symbol": "AAPL", "date": "2026-04-27", "timing": "amc"},
            ],
            macro_events=[],
        )
        assert "AAPL" in result["earnings_today_tickers"].split(","), (
            "Earnings on 2026-04-27 (US/Eastern today) must land in "
            "earnings_today_tickers, not earnings_tomorrow_tickers."
        )

    def test_macro_event_anchored_on_us_eastern(self, monkeypatch: object) -> None:
        """Copilot PR #364 follow-up: ``evt_dt.date()`` must be taken
        AFTER ``.astimezone(_ET)`` so an event at 00:30 UTC (= 20:30 ET
        previous day) doesn't masquerade as today's event.
        """
        import smc_calendar_collector as mod

        # Pin "now" to 2026-04-28 14:00 UTC (= 10:00 ET 2026-04-28).
        class _PinnedDT(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                pinned = datetime(2026, 4, 28, 14, 0, tzinfo=UTC)
                return pinned.astimezone(tz) if tz else pinned.replace(tzinfo=None)

        monkeypatch.setattr(mod, "datetime", _PinnedDT)  # type: ignore[attr-defined]
        # Event at 00:30 UTC on 2026-04-28 == 2026-04-27 20:30 ET.
        # In trading terms that's YESTERDAY — must NOT match today.
        events = [
            {
                "name": "FOMC Statement",
                "time_utc": "2026-04-28T00:30:00+00:00",
                "impact": "high",
            },
        ]
        result = collect_earnings_and_macro(
            symbols=["AAPL"], macro_events=events
        )
        assert result["high_impact_macro_today"] is False, (
            "00:30 UTC == 20:30 ET previous day must NOT be classified "
            "as a today-event (evt_dt must be ET-anchored before .date())."
        )

    def test_macro_event_at_us_market_close_still_today(
        self, monkeypatch: object
    ) -> None:
        """Inverse case: an event at 23:00 UTC (19:00 ET) on the
        anchor's ET date must still be classified as today's event."""
        import smc_calendar_collector as mod

        class _PinnedDT(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                pinned = datetime(2026, 4, 28, 14, 0, tzinfo=UTC)
                return pinned.astimezone(tz) if tz else pinned.replace(tzinfo=None)

        monkeypatch.setattr(mod, "datetime", _PinnedDT)  # type: ignore[attr-defined]
        events = [
            {
                "name": "FOMC Press Conference",
                "time_utc": "2026-04-28T23:00:00+00:00",
                "impact": "high",
            },
        ]
        result = collect_earnings_and_macro(
            symbols=["AAPL"], macro_events=events
        )
        assert result["high_impact_macro_today"] is True
        assert "FOMC" in result["macro_event_name"]
