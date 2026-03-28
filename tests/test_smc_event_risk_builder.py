"""Tests for the v5 Event Risk Layer builder.

Covers:
- no event (all defaults)
- incoming macro event (PRE_EVENT / ACTIVE window states)
- active cooldown
- symbol earnings block
- manual override merge
- edge cases (missing calendar, missing news, combined scenarios)
"""
from __future__ import annotations

from datetime import datetime, UTC

import pytest

from scripts.smc_event_risk_builder import (
    DEFAULTS,
    build_event_risk,
    _compute_window_state,
    _merge_ticker_lists,
    _parse_event_time,
)


# ── 1. No event (all defaults) ─────────────────────────────────────


class TestNoEvent:
    def test_empty_inputs_return_defaults(self):
        result = build_event_risk()
        for key, default_value in DEFAULTS.items():
            if key == "EVENT_PROVIDER_STATUS":
                continue  # provider status depends on input presence
            assert result[key] == default_value, f"{key} mismatch"

    def test_empty_calendar_and_news_return_defaults(self):
        result = build_event_risk(calendar={}, news={})
        assert result["EVENT_WINDOW_STATE"] == "CLEAR"
        assert result["EVENT_RISK_LEVEL"] == "NONE"
        assert result["MARKET_EVENT_BLOCKED"] is False
        assert result["SYMBOL_EVENT_BLOCKED"] is False
        assert result["EVENT_COOLDOWN_ACTIVE"] is False

    def test_no_data_provider_status(self):
        result = build_event_risk(calendar=None, news=None)
        assert result["EVENT_PROVIDER_STATUS"] == "no_data"

    def test_calendar_missing_provider_status(self):
        result = build_event_risk(
            calendar=None,
            news={"bearish_tickers": [], "news_heat_global": 0.1},
        )
        assert result["EVENT_PROVIDER_STATUS"] == "calendar_missing"

    def test_news_missing_provider_status(self):
        result = build_event_risk(
            calendar={"high_impact_macro_today": False},
            news=None,
        )
        assert result["EVENT_PROVIDER_STATUS"] == "news_missing"

    def test_all_fields_present(self):
        """Every field from DEFAULTS must appear in the output."""
        result = build_event_risk()
        for key in DEFAULTS:
            assert key in result, f"missing field: {key}"


# ── 2. Incoming macro event ─────────────────────────────────────────


class TestMacroEvent:
    @pytest.fixture()
    def fomc_calendar(self):
        return {
            "high_impact_macro_today": True,
            "macro_event_name": "FOMC Rate Decision",
            "macro_event_time": "14:00",
        }

    def test_macro_event_sets_class_and_name(self, fomc_calendar):
        result = build_event_risk(
            calendar=fomc_calendar,
            now=datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
        )
        assert result["NEXT_EVENT_CLASS"] == "MACRO"
        assert result["NEXT_EVENT_NAME"] == "FOMC Rate Decision"
        assert result["NEXT_EVENT_TIME"] == "14:00"
        assert result["NEXT_EVENT_IMPACT"] == "HIGH"

    def test_macro_event_risk_level_high(self, fomc_calendar):
        result = build_event_risk(
            calendar=fomc_calendar,
            now=datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
        )
        assert result["EVENT_RISK_LEVEL"] == "HIGH"

    def test_macro_event_restrict_minutes(self, fomc_calendar):
        result = build_event_risk(
            calendar=fomc_calendar,
            now=datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
        )
        assert result["EVENT_RESTRICT_BEFORE_MIN"] == 30
        assert result["EVENT_RESTRICT_AFTER_MIN"] == 15

    def test_pre_event_window_when_approaching(self, fomc_calendar):
        # 20 minutes before 14:00 → within 30-min pre-restrict window
        result = build_event_risk(
            calendar=fomc_calendar,
            now=datetime(2026, 3, 28, 13, 40, tzinfo=UTC),
        )
        assert result["EVENT_WINDOW_STATE"] == "PRE_EVENT"
        assert result["MARKET_EVENT_BLOCKED"] is False

    def test_active_window_when_event_just_passed(self, fomc_calendar):
        # 5 minutes after 14:00 → within 15-min cooldown
        result = build_event_risk(
            calendar=fomc_calendar,
            now=datetime(2026, 3, 28, 14, 5, tzinfo=UTC),
        )
        assert result["EVENT_WINDOW_STATE"] == "COOLDOWN"
        assert result["EVENT_COOLDOWN_ACTIVE"] is True

    def test_clear_when_well_before_event(self, fomc_calendar):
        # 3 hours before → CLEAR
        result = build_event_risk(
            calendar=fomc_calendar,
            now=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
        )
        assert result["EVENT_WINDOW_STATE"] == "CLEAR"
        assert result["MARKET_EVENT_BLOCKED"] is False


# ── 3. Active cooldown ──────────────────────────────────────────────


class TestActiveCooldown:
    def test_cooldown_active_after_event(self):
        result = build_event_risk(
            calendar={
                "high_impact_macro_today": True,
                "macro_event_name": "CPI Release",
                "macro_event_time": "08:30",
            },
            now=datetime(2026, 3, 28, 8, 40, tzinfo=UTC),
        )
        assert result["EVENT_COOLDOWN_ACTIVE"] is True
        assert result["EVENT_WINDOW_STATE"] == "COOLDOWN"

    def test_cooldown_expires_after_restrict_window(self):
        result = build_event_risk(
            calendar={
                "high_impact_macro_today": True,
                "macro_event_name": "CPI Release",
                "macro_event_time": "08:30",
            },
            now=datetime(2026, 3, 28, 9, 0, tzinfo=UTC),
        )
        # 30 min after 08:30 → cooldown window (15 min) expired → CLEAR
        assert result["EVENT_COOLDOWN_ACTIVE"] is False
        assert result["EVENT_WINDOW_STATE"] == "CLEAR"


# ── 4. Symbol earnings block ───────────────────────────────────────


class TestSymbolEarningsBlock:
    def test_earnings_today_sets_symbol_blocked(self):
        result = build_event_risk(
            calendar={"earnings_today_tickers": "AAPL,MSFT"},
        )
        assert result["SYMBOL_EVENT_BLOCKED"] is True
        assert "AAPL" in result["EARNINGS_SOON_TICKERS"]
        assert "MSFT" in result["EARNINGS_SOON_TICKERS"]

    def test_earnings_tomorrow_included(self):
        result = build_event_risk(
            calendar={"earnings_tomorrow_tickers": "GOOG"},
        )
        assert result["SYMBOL_EVENT_BLOCKED"] is True
        assert "GOOG" in result["EARNINGS_SOON_TICKERS"]

    def test_earnings_bmo_amc_merged(self):
        result = build_event_risk(
            calendar={
                "earnings_bmo_tickers": "TSLA",
                "earnings_amc_tickers": "NVDA",
            },
        )
        assert "TSLA" in result["EARNINGS_SOON_TICKERS"]
        assert "NVDA" in result["EARNINGS_SOON_TICKERS"]

    def test_earnings_promotes_event_class_when_no_macro(self):
        result = build_event_risk(
            calendar={"earnings_today_tickers": "AAPL"},
        )
        assert result["NEXT_EVENT_CLASS"] == "EARNINGS"
        assert result["NEXT_EVENT_IMPACT"] == "MEDIUM"
        assert result["EVENT_RISK_LEVEL"] == "ELEVATED"

    def test_earnings_does_not_override_macro_class(self):
        result = build_event_risk(
            calendar={
                "high_impact_macro_today": True,
                "macro_event_name": "NFP",
                "macro_event_time": "08:30",
                "earnings_today_tickers": "AAPL",
            },
            now=datetime(2026, 3, 28, 7, 0, tzinfo=UTC),
        )
        assert result["NEXT_EVENT_CLASS"] == "MACRO"
        assert result["SYMBOL_EVENT_BLOCKED"] is True

    def test_earnings_tickers_deduplicated(self):
        result = build_event_risk(
            calendar={
                "earnings_today_tickers": "AAPL,MSFT",
                "earnings_tomorrow_tickers": "AAPL,GOOG",
            },
        )
        tickers = result["EARNINGS_SOON_TICKERS"].split(",")
        assert len(tickers) == len(set(tickers))
        assert sorted(tickers) == tickers

    def test_high_risk_event_tickers_includes_earnings_and_bearish(self):
        result = build_event_risk(
            calendar={"earnings_today_tickers": "AAPL"},
            news={"bearish_tickers": ["TSLA", "META"]},
        )
        high_risk = result["HIGH_RISK_EVENT_TICKERS"].split(",")
        assert "AAPL" in high_risk
        assert "TSLA" in high_risk
        assert "META" in high_risk


# ── 5. Manual override merge ───────────────────────────────────────


class TestManualOverrideMerge:
    def test_override_replaces_derived_value(self):
        result = build_event_risk(
            calendar={"high_impact_macro_today": True, "macro_event_name": "FOMC", "macro_event_time": "14:00"},
            overrides={"EVENT_RISK_LEVEL": "LOW", "MARKET_EVENT_BLOCKED": False},
            now=datetime(2026, 3, 28, 13, 50, tzinfo=UTC),
        )
        assert result["EVENT_RISK_LEVEL"] == "LOW"
        assert result["MARKET_EVENT_BLOCKED"] is False

    def test_override_adds_custom_tickers(self):
        result = build_event_risk(
            overrides={"HIGH_RISK_EVENT_TICKERS": "XYZ,ABC"},
        )
        assert result["HIGH_RISK_EVENT_TICKERS"] == "XYZ,ABC"

    def test_unknown_override_key_ignored(self):
        result = build_event_risk(
            overrides={"NONEXISTENT_FIELD": 42},
        )
        assert "NONEXISTENT_FIELD" not in result

    def test_override_preserves_other_derived_fields(self):
        result = build_event_risk(
            calendar={"earnings_today_tickers": "AAPL"},
            overrides={"EVENT_RISK_LEVEL": "NONE"},
        )
        assert result["EVENT_RISK_LEVEL"] == "NONE"
        assert result["SYMBOL_EVENT_BLOCKED"] is True  # not overridden


# ── 6. Edge cases and helpers ──────────────────────────────────────


class TestHelpers:
    def test_merge_ticker_lists_dedup_and_sorted(self):
        assert _merge_ticker_lists("AAPL,MSFT", "MSFT,GOOG") == "AAPL,GOOG,MSFT"

    def test_merge_ticker_lists_empty(self):
        assert _merge_ticker_lists("", "", "") == ""

    def test_merge_ticker_lists_whitespace(self):
        assert _merge_ticker_lists(" aapl , msft ") == "AAPL,MSFT"

    def test_parse_event_time_hhmm(self):
        t = _parse_event_time("14:00")
        assert t is not None
        assert t.hour == 14 and t.minute == 0

    def test_parse_event_time_hhmmss(self):
        t = _parse_event_time("08:30:00")
        assert t is not None
        assert t.hour == 8 and t.minute == 30

    def test_parse_event_time_invalid(self):
        assert _parse_event_time("not-a-time") is None
        assert _parse_event_time("") is None

    def test_compute_window_clear_when_far_ahead(self):
        state = _compute_window_state("14:00", datetime(2026, 3, 28, 10, 0, tzinfo=UTC), 30, 15)
        assert state == "CLEAR"

    def test_compute_window_pre_event(self):
        state = _compute_window_state("14:00", datetime(2026, 3, 28, 13, 40, tzinfo=UTC), 30, 15)
        assert state == "PRE_EVENT"

    def test_compute_window_cooldown(self):
        state = _compute_window_state("14:00", datetime(2026, 3, 28, 14, 10, tzinfo=UTC), 30, 15)
        assert state == "COOLDOWN"

    def test_compute_window_clear_after_cooldown(self):
        state = _compute_window_state("14:00", datetime(2026, 3, 28, 14, 20, tzinfo=UTC), 30, 15)
        assert state == "CLEAR"

    def test_compute_window_unparseable_time_safe_default(self):
        state = _compute_window_state("TBD", datetime(2026, 3, 28, 12, 0, tzinfo=UTC), 30, 15)
        assert state == "PRE_EVENT"  # safe: restrict when unknown


class TestCombinedScenarios:
    def test_macro_plus_earnings_both_active(self):
        """Both macro and earnings present — macro takes NEXT_EVENT_CLASS, earnings set SYMBOL_EVENT_BLOCKED."""
        result = build_event_risk(
            calendar={
                "high_impact_macro_today": True,
                "macro_event_name": "FOMC",
                "macro_event_time": "14:00",
                "earnings_today_tickers": "AAPL",
            },
            news={"bearish_tickers": ["TSLA"]},
            now=datetime(2026, 3, 28, 13, 50, tzinfo=UTC),
        )
        assert result["NEXT_EVENT_CLASS"] == "MACRO"
        assert result["SYMBOL_EVENT_BLOCKED"] is True
        assert "AAPL" in result["EARNINGS_SOON_TICKERS"]
        assert "AAPL" in result["HIGH_RISK_EVENT_TICKERS"]
        assert "TSLA" in result["HIGH_RISK_EVENT_TICKERS"]
        assert result["EVENT_RISK_LEVEL"] == "HIGH"

    def test_high_news_heat_elevates_risk(self):
        """News heat > 0.8 bumps EVENT_RISK_LEVEL to ELEVATED."""
        result = build_event_risk(
            news={"bearish_tickers": ["AAPL"], "news_heat_global": 0.9},
        )
        assert result["EVENT_RISK_LEVEL"] == "ELEVATED"

    def test_news_heat_does_not_override_market_blocked(self):
        """News heat does not set MARKET_EVENT_BLOCKED when already blocked by macro."""
        result = build_event_risk(
            calendar={
                "high_impact_macro_today": True,
                "macro_event_name": "GDP",
                "macro_event_time": "08:30",
            },
            news={"news_heat_global": 0.95},
            now=datetime(2026, 3, 28, 8, 25, tzinfo=UTC),
        )
        assert result["MARKET_EVENT_BLOCKED"] is False  # PRE_EVENT, not ACTIVE
        assert result["EVENT_WINDOW_STATE"] == "PRE_EVENT"

    def test_deterministic_with_fixed_now(self):
        """Same inputs + fixed now → identical output."""
        fixed = datetime(2026, 3, 28, 13, 0, tzinfo=UTC)
        cal = {"high_impact_macro_today": True, "macro_event_name": "FOMC", "macro_event_time": "14:00"}
        r1 = build_event_risk(calendar=cal, now=fixed)
        r2 = build_event_risk(calendar=cal, now=fixed)
        assert r1 == r2
