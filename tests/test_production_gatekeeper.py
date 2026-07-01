"""Production Gatekeeper tests — validates fail-open, no hard-gates,
determinism, and observability constraints.

Each test case follows Arrange / Act / Assert structure and targets a
specific production-readiness issue identified during the gatekeeper
review.
"""
from __future__ import annotations

import math
import threading
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_quote(**overrides) -> dict:
    """Build a minimal valid quote dict with sensible defaults."""
    base = {
        "symbol": "TEST",
        "price": 25.0,
        "previousClose": 24.0,
        "volume": 500_000,
        "avgVolume": 300_000,
        "open": 25.0,
        "gap_pct": 4.17,
        "gap_available": True,
        "gap_reason": "ok",
        "ext_hours_score": 0.95,
        "ext_volume_ratio": 0.1,
        "premarket_stale": False,
        "premarket_spread_bps": 15.0,
        "earnings_risk_window": False,
        "corporate_action_penalty": 0.0,
        "atr": 1.2,
        "momentum_z_score": 0.5,
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════
# 1) ATR missing → warn flag, NOT a hard block
# ═══════════════════════════════════════════════════════════════════

class TestAtrMissingWarnFlag:
    """When ATR is 0 or missing, the candidate must receive an
    ``atr_missing`` warn/no_trade_reason but ``long_allowed`` must
    remain True (fail-open: ATR is enrichment, not a gate)."""

    def test_v1_atr_missing_warn_flag_but_long_allowed(self):
        """Arrange: quote with atr=0. Act: rank_candidates. Assert:
        atr_missing in no_trade_reason, long_allowed=True."""
        from open_prep.screen import rank_candidates

        quote = _make_quote(atr=0.0)
        ranked = rank_candidates([quote], bias=0.2, top_n=5)

        assert len(ranked) == 1
        row = ranked[0]
        assert "atr_missing" in row["no_trade_reason"]
        # atr_missing is NOT in the hard-block set → long_allowed stays True
        assert row["long_allowed"] is True

    def test_v2_atr_missing_warn_flag_but_passed(self):
        """Arrange: quote with atr=0. Act: filter_candidate. Assert:
        atr_missing in filter_reasons, passed=True (fail-open)."""
        from open_prep.scorer import filter_candidate

        quote = _make_quote(atr=0.0)
        fr = filter_candidate(quote, bias=0.2)

        assert "atr_missing" in fr.filter_reasons
        # atr_missing is informational, not a hard block
        assert fr.passed is True
        assert fr.long_allowed is True

    def test_atr_missing_negative_value_treated_as_zero(self):
        """Arrange: atr=-1. Assert: treated same as atr=0 → atr_missing."""
        from open_prep.scorer import filter_candidate

        quote = _make_quote(atr=-1.0)
        fr = filter_candidate(quote, bias=0.2)
        assert "atr_missing" in fr.filter_reasons
        assert fr.passed is True


# ═══════════════════════════════════════════════════════════════════
# 2) Gap unavailable reasons — every reason must surface observably
# ═══════════════════════════════════════════════════════════════════

class TestGapUnavailableReasons:
    """When gap is unavailable, classify_long_gap should set
    warn_flags (not block) and propagate the gap_reason."""

    def test_gap_not_available_warn_flag(self):
        """Arrange: gap_available=False. Assert: warn_flags contains
        gap_not_available."""
        from open_prep.screen import classify_long_gap

        row = _make_quote(gap_available=False, gap_pct=0.0)
        result = classify_long_gap(row, bias=0.2)

        assert "gap_not_available" in result["warn_flags"]

    def test_premarket_unavailable_reason(self):
        """Arrange: gap_reason='premarket_unavailable'. Assert:
        premarket_unavailable warn flag set."""
        from open_prep.screen import classify_long_gap

        row = _make_quote(
            gap_available=False,
            gap_pct=0.0,
            gap_reason="premarket_unavailable",
        )
        result = classify_long_gap(row, bias=0.2)
        assert "premarket_unavailable" in result["warn_flags"]

    def test_missing_previous_close_reason(self):
        """Arrange: gap_reason='missing_previous_close'. Assert:
        data_missing_prev_close warn flag set."""
        from open_prep.screen import classify_long_gap

        row = _make_quote(
            gap_available=False,
            gap_pct=0.0,
            gap_reason="missing_previous_close",
        )
        result = classify_long_gap(row, bias=0.2)
        assert "data_missing_prev_close" in result["warn_flags"]

    def test_missing_quote_timestamp_reason(self):
        """Arrange: gap_reason='missing_quote_timestamp'. Assert:
        premarket_unavailable warn flag set."""
        from open_prep.screen import classify_long_gap

        row = _make_quote(
            gap_available=False,
            gap_pct=0.0,
            gap_reason="missing_quote_timestamp",
        )
        result = classify_long_gap(row, bias=0.2)
        assert "premarket_unavailable" in result["warn_flags"]

    def test_gap_unavailable_never_blocks_go(self):
        """Even when gap is unavailable, if gap_pct is above GO thresholds
        (e.g., from fallback changesPercentage), bucket should be GO or WATCH,
        never silently dropped."""
        from open_prep.screen import classify_long_gap

        row = _make_quote(
            gap_available=False,
            gap_pct=3.0,
            ext_hours_score=1.0,
            ext_volume_ratio=0.15,
        )
        result = classify_long_gap(row, bias=0.2)
        # Must not be silently dropped; bucket should be GO or WATCH
        assert result["bucket"] in {"GO", "WATCH"}


# ═══════════════════════════════════════════════════════════════════
# 3) Weekend/Holiday gap_scope — STRETCH_ONLY produces gaps only
#    on first session after stretch, DAILY produces every day.
# ═══════════════════════════════════════════════════════════════════

class TestWeekendHolidayGapScope:
    """Verify _is_gap_day logic for DAILY vs STRETCH_ONLY gap scopes."""

    def test_daily_scope_normal_weekday(self):
        """DAILY scope: any US trading day is a gap day."""
        from open_prep.run_open_prep import GAP_SCOPE_DAILY, _is_gap_day

        # 2025-06-16 is Monday — normal trading day
        assert _is_gap_day(date(2025, 6, 16), GAP_SCOPE_DAILY) is True

    def test_daily_scope_saturday(self):
        """DAILY scope: Saturday is not a trading day → no gap."""
        from open_prep.run_open_prep import GAP_SCOPE_DAILY, _is_gap_day

        assert _is_gap_day(date(2025, 6, 14), GAP_SCOPE_DAILY) is False

    def test_stretch_scope_monday_is_gap_day(self):
        """STRETCH_ONLY: Monday after a regular weekend is a stretch→ gap day."""
        from open_prep.run_open_prep import GAP_SCOPE_STRETCH_ONLY, _is_gap_day

        assert _is_gap_day(date(2025, 6, 16), GAP_SCOPE_STRETCH_ONLY) is True

    def test_stretch_scope_tuesday_is_not_gap_day(self):
        """STRETCH_ONLY: Tuesday (after a normal Monday) is NOT a stretch."""
        from open_prep.run_open_prep import GAP_SCOPE_STRETCH_ONLY, _is_gap_day

        assert _is_gap_day(date(2025, 6, 17), GAP_SCOPE_STRETCH_ONLY) is False

    def test_stretch_scope_post_holiday(self):
        """STRETCH_ONLY: Day after Independence Day (Jul 4 2025 = Fri) is
        the following Monday (Jul 7) — should be a stretch gap day."""
        from open_prep.run_open_prep import GAP_SCOPE_STRETCH_ONLY, _is_gap_day

        # After Jul 4 (Friday holiday) + weekend → Monday Jul 7 is stretch
        assert _is_gap_day(date(2025, 7, 7), GAP_SCOPE_STRETCH_ONLY) is True

    def test_holiday_set_contains_independence_day(self):
        """Verify holiday set includes Independence Day for 2025."""
        from newsstack_fmp._market_cal import (
            us_equity_market_holidays as _us_equity_market_holidays,
        )

        holidays = _us_equity_market_holidays(2025)
        assert date(2025, 7, 4) in holidays

    def test_holiday_set_contains_christmas(self):
        """Verify holiday set includes Christmas for 2025."""
        from newsstack_fmp._market_cal import (
            us_equity_market_holidays as _us_equity_market_holidays,
        )

        holidays = _us_equity_market_holidays(2025)
        assert date(2025, 12, 25) in holidays


# ═══════════════════════════════════════════════════════════════════
# 4) Premarket timestamp missing → gap_reason populated
# ═══════════════════════════════════════════════════════════════════

class TestPremarketTimestampMissing:
    """When premarket price is available but quote_timestamp is None,
    gap_reason must be 'missing_quote_timestamp' and gap_available=False."""

    def test_missing_timestamp_sets_gap_reason(self):
        """Arrange: quote with premarket price but no timestamp. Act:
        _compute_gap_for_quote. Assert: gap_reason='missing_quote_timestamp'."""
        from open_prep.run_open_prep import _compute_gap_for_quote

        quote = {
            "symbol": "TEST",
            "previousClose": 24.0,
            "preMarketPrice": 25.0,  # premarket available
            "price": 25.0,
            # No 'timestamp', 'earningsAnnouncement', etc. → quote_ts = None
        }
        run_dt = datetime(2025, 6, 16, 13, 0, tzinfo=UTC)  # Monday 9AM ET

        result = _compute_gap_for_quote(
            quote,
            run_dt_utc=run_dt,
            gap_mode="PREMARKET_INDICATIVE",
        )
        assert result["gap_available"] is False
        assert result["gap_reason"] == "missing_quote_timestamp"

    def test_spot_fallback_without_timestamp(self):
        """When only spot price is available with no premarket fields
        and no timestamp, gap_reason should indicate staleness."""
        from open_prep.run_open_prep import _compute_gap_for_quote

        quote = {
            "symbol": "TEST",
            "previousClose": 24.0,
            "price": 25.0,
            # No premarket fields, no timestamp
        }
        run_dt = datetime(2025, 6, 16, 13, 0, tzinfo=UTC)  # After 4am ET

        result = _compute_gap_for_quote(
            quote,
            run_dt_utc=run_dt,
            gap_mode="PREMARKET_INDICATIVE",
        )
        assert result["gap_available"] is False
        assert "stale" in result["gap_reason"] or "missing" in result["gap_reason"]


# ═══════════════════════════════════════════════════════════════════
# 5) SystemExit removal — fail-open for macro and quotes
# ═══════════════════════════════════════════════════════════════════

class TestNoSystemExit:
    """The pipeline must never raise SystemExit. All data-source
    failures must be degraded gracefully."""

    def test_macro_calendar_failure_returns_empty(self):
        """Arrange: client.get_macro_calendar raises RuntimeError.
        Act: _fetch_todays_events. Assert: returns ([], [])."""
        from open_prep.run_open_prep import _fetch_todays_events

        mock_client = MagicMock()
        mock_client.get_macro_calendar.side_effect = RuntimeError("API down")

        result = _fetch_todays_events(
            client=mock_client,
            today=date(2025, 6, 16),
            end_date=date(2025, 6, 19),
            pre_open_only=False,
            pre_open_cutoff_utc="16:00:00",
        )
        assert result == ([], [])

    def test_quote_fetch_failure_returns_empty(self):
        """Arrange: client.get_batch_quotes raises RuntimeError.
        Act: _fetch_quotes_with_atr. Assert: returns empty results,
        no SystemExit."""
        from open_prep.run_open_prep import _fetch_quotes_with_atr

        mock_client = MagicMock()
        mock_client.get_batch_quotes.side_effect = RuntimeError("API down")

        quotes, _atr_map, _mom_map, _vwap_map, errors, quote_diagnostics = _fetch_quotes_with_atr(
            client=mock_client,
            symbols=["AAPL"],
            run_dt_utc=datetime(2025, 6, 16, 13, 0, tzinfo=UTC),
            as_of=date(2025, 6, 16),
            gap_mode="PREMARKET_INDICATIVE",
            atr_lookback_days=250,
            atr_period=14,
            atr_parallel_workers=1,
        )
        assert quotes == []
        assert isinstance(errors, dict)
        assert "__batch__" in errors
        assert quote_diagnostics["failed_quote_symbol_count"] == 1

    def test_invalid_cutoff_does_not_crash(self, caplog):
        """Arrange: invalid cutoff format (Audit E-1 TQ-3, 2026-06-13).

        Assert fail-open *and* observability: returns unfiltered events
        instead of SystemExit and emits a clear ERROR log marker.
        """
        from open_prep.run_open_prep import _fetch_todays_events

        mock_client = MagicMock()
        mock_client.get_macro_calendar.return_value = [
            {"event": "test", "date": "2025-06-16", "country": "US"},
        ]

        with caplog.at_level("ERROR", logger="open_prep.run"):
            # Invalid cutoff should not crash
            result = _fetch_todays_events(
                client=mock_client,
                today=date(2025, 6, 16),
                end_date=date(2025, 6, 19),
                pre_open_only=True,
                pre_open_cutoff_utc="INVALID",
            )
        # Should return unfiltered today's events (fail-open), not just
        # "some list".
        todays, all_events = result
        assert isinstance(todays, list)
        assert isinstance(all_events, list)
        assert len(todays) == 1
        assert len(all_events) == 1
        assert todays[0]["event"] == "test"
        assert all_events[0]["event"] == "test"
        assert "Invalid --pre-open-cutoff-utc" in caplog.text


# ═══════════════════════════════════════════════════════════════════
# 6) _prev_trading_day safety bound
# ═══════════════════════════════════════════════════════════════════

class TestPrevTradingDaySafety:
    """_prev_trading_day must terminate even if holiday data is wrong."""

    def test_normal_weekday(self):
        """Monday → Friday prev day."""
        from open_prep.run_open_prep import _prev_trading_day

        # 2025-06-16 is Monday → prev = Friday 2025-06-13
        result = _prev_trading_day(date(2025, 6, 16))
        assert result == date(2025, 6, 13)

    def test_tuesday(self):
        """Tuesday → Monday."""
        from open_prep.run_open_prep import _prev_trading_day

        result = _prev_trading_day(date(2025, 6, 17))
        assert result == date(2025, 6, 16)

    def test_safety_bound_prevents_infinite_loop(self):
        """If every day were a holiday, the function must still return
        within 14 iterations (safety bound).  The fallback returns the
        last iterated date (NOT d-1 which could be a weekend)."""
        from open_prep.run_open_prep import _prev_trading_day

        # Patch is_us_equity_trading_day where prev_trading_day calls it
        with patch(
            "newsstack_fmp._market_cal.is_us_equity_trading_day",
            return_value=False,
        ):
            # Should not hang — safety bound returns last checked date
            # d=2025-06-16, iterates 14 times from d-1=Jun 15 through Jun 1,
            # then one more step to May 31 → returns May 31 (cur after loop)
            result = _prev_trading_day(date(2025, 6, 16))
            # Start at d-1 (Jun 15); after 14 backward iterations, cur is Jun 1.
            assert result == date(2025, 6, 1)

# ═══════════════════════════════════════════════════════════════════
# 7) Bare float() safety in realtime_signals._detect_signal
# ═══════════════════════════════════════════════════════════════════

class TestRealtimeSignalFloatSafety:
    """_detect_signal must not crash on non-numeric quote fields."""

    @staticmethod
    def _make_bare_engine():
        """Create a bare RealtimeEngine bypassing __init__ with all needed attrs."""
        from open_prep.realtime_signals import (
            DynamicCooldown,
            GateHysteresis,
            RealtimeEngine,
            TechnicalScorer,
            VolumeRegimeDetector,
        )
        engine = RealtimeEngine.__new__(RealtimeEngine)
        engine._last_prices = {}
        engine._price_history = {}
        engine._hysteresis = GateHysteresis()
        engine._dynamic_cooldown = DynamicCooldown()
        engine._volume_regime = VolumeRegimeDetector()
        engine._avg_vol_cache = {}
        engine._technical_scorer = TechnicalScorer()
        return engine

    def test_non_numeric_price_returns_none(self):
        """Arrange: quote with price='N/A'. Assert: returns None, no crash."""
        engine = self._make_bare_engine()

        signal = engine._detect_signal(
            "TEST",
            {"price": "N/A", "previousClose": 24.0, "volume": 100},
            {"avg_volume": 50000},
        )
        assert signal is None  # price=0 → early return

    def test_none_values_return_none(self):
        """Arrange: quote with all None values. Assert: returns None."""
        engine = self._make_bare_engine()

        signal = engine._detect_signal(
            "TEST",
            {"price": None, "previousClose": None, "volume": None},
            {},
        )
        assert signal is None

    def test_valid_quote_produces_signal(self):
        """Arrange: quote with strong breakout. Assert: signal produced."""
        engine = self._make_bare_engine()

        # Mock market-hours gate so the test works regardless of day/time
        with patch(
            "open_prep.realtime_signals._is_within_market_hours", return_value=True
        ):
            signal = engine._detect_signal(
                "TEST",
                {
                    "price": 30.0,
                    "previousClose": 24.0,
                    "volume": 1_500_000,
                    "avgVolume": 300_000,
                },
                {"atr_pct_computed": 3.5, "score": 8.5, "confidence_tier": "HIGH"},
            )
        # 25% change with 5x volume → A0 signal
        assert signal is not None
        assert signal.level == "A0"
        assert signal.direction == "LONG"


# ═══════════════════════════════════════════════════════════════════
# 8) classify_long_gap float() safety
# ═══════════════════════════════════════════════════════════════════

class TestClassifyLongGapFloatSafety:
    """classify_long_gap must not crash on non-numeric field values."""

    def test_non_numeric_gap_pct(self):
        """Arrange: gap_pct='bad'. Assert: no crash, treated as 0."""
        from open_prep.screen import classify_long_gap

        row = _make_quote(gap_pct="bad_value")
        result = classify_long_gap(row, bias=0.2)
        assert result["bucket"] in {"GO", "WATCH", "SKIP"}

    def test_non_numeric_spread_bps(self):
        """Arrange: premarket_spread_bps='N/A'. Assert: no crash."""
        from open_prep.screen import classify_long_gap

        row = _make_quote(premarket_spread_bps="N/A")
        result = classify_long_gap(row, bias=0.2)
        assert result["bucket"] in {"GO", "WATCH", "SKIP"}


# ═══════════════════════════════════════════════════════════════════
# 9) Determinism — same input → same output
# ═══════════════════════════════════════════════════════════════════

class TestDeterminism:
    """Same input must always produce the same ranked output."""

    def test_rank_candidates_deterministic(self):
        """Two calls with identical input → identical output."""
        from open_prep.screen import rank_candidates

        quotes = [
            _make_quote(symbol="AAA", gap_pct=3.0, price=20.0),
            _make_quote(symbol="BBB", gap_pct=3.0, price=20.0),
        ]
        r1 = rank_candidates(list(quotes), bias=0.2, top_n=10)
        r2 = rank_candidates(list(quotes), bias=0.2, top_n=10)

        assert [r["symbol"] for r in r1] == [r["symbol"] for r in r2]
        assert [r["score"] for r in r1] == [r["score"] for r in r2]

    def test_v2_scorer_deterministic(self):
        """filter_candidate + score_candidate is deterministic."""
        from open_prep.scorer import filter_candidate, score_candidate

        quote = _make_quote(symbol="DET", gap_pct=4.0)
        fr1 = filter_candidate(quote, bias=0.2)
        fr2 = filter_candidate(quote, bias=0.2)
        s1 = score_candidate(fr1, bias=0.2)
        s2 = score_candidate(fr2, bias=0.2)

        assert s1["score"] == s2["score"]
        assert s1["symbol"] == s2["symbol"]


# ═══════════════════════════════════════════════════════════════════
# 10) Realtime engine fail-open when client disabled
# ═══════════════════════════════════════════════════════════════════

class TestRealtimeFailOpen:
    """RealtimeEngine.poll_once must return [] when client is disabled,
    never crash."""

    def test_poll_once_disabled_returns_empty(self):
        """Arrange: engine with _client_disabled_reason set.
        Assert: poll_once returns [], no crash."""
        from open_prep.realtime_signals import RealtimeEngine

        engine = RealtimeEngine.__new__(RealtimeEngine)
        engine._lock = threading.Lock()  # set by __init__; required by poll_once
        engine._client_disabled_reason = "API key missing"
        engine._active_signals = []
        engine._watchlist = []
        engine._was_outside_market = False
        engine.poll_interval = 45

        # Mock _save_signals to avoid file I/O
        engine._save_signals = MagicMock()
        result = engine.poll_once()

        assert result == []
        engine._save_signals.assert_called_once_with(
            disabled_reason="API key missing",
        )


# ═══════════════════════════════════════════════════════════════════
# 11) P-1: detect_breakout — safe float conversion
# ═══════════════════════════════════════════════════════════════════

class TestDetectBreakoutSafeFloat:
    """detect_breakout must handle None/non-numeric bar data without
    crashing (P-1 fix)."""

    def test_none_close_in_bars(self):
        """Arrange: bar with close=None. Assert: no crash, returns result."""
        from open_prep.technical_analysis import detect_breakout

        bars = [
            {"open": 10, "high": 11, "low": 9, "close": None, "volume": 100}
        ] * 70
        result = detect_breakout(bars)
        assert isinstance(result, dict)
        assert "direction" in result

    def test_non_numeric_volume(self):
        """Arrange: bar with volume='N/A'. Assert: no crash."""
        from open_prep.technical_analysis import detect_breakout

        bars = [
            {"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": "N/A"}
        ] * 70
        result = detect_breakout(bars)
        assert isinstance(result, dict)

    def test_missing_close_key(self):
        """Arrange: bar without 'close' key. Assert: no crash, uses 0.0."""
        from open_prep.technical_analysis import detect_breakout

        bars = [
            {"open": 10, "high": 11, "low": 9, "volume": 100}
        ] * 70
        result = detect_breakout(bars)
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════
# 12) P-1: calculate_support_resistance_targets — safe float
# ═══════════════════════════════════════════════════════════════════

class TestSupportResistanceSafeFloat:
    """calculate_support_resistance_targets must handle None/non-numeric
    values in bars without crashing (P-1 fix, outer try/except exists)."""

    def test_none_highs_lows(self):
        """Arrange: bars with high=None. Assert: no crash, returns empty."""
        from open_prep.technical_analysis import calculate_support_resistance_targets

        bars = [
            {"open": 10, "high": None, "low": None, "close": 10, "volume": 100}
        ] * 60
        result = calculate_support_resistance_targets(bars, current_price=10.0)
        # Either returns empty result (from except) or computed result
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════
# 13) P-2: watchlist auto_add — None score/gap_pct
# ═══════════════════════════════════════════════════════════════════

class TestWatchlistAutoAddNoneValues:
    """auto_add_high_conviction must not crash when score or gap_pct
    is None (P-2 fix)."""

    def test_score_is_none(self, tmp_path, monkeypatch):
        """Arrange: ranked row with score=None. Assert: no TypeError."""
        import open_prep.watchlist as wl

        monkeypatch.setattr(wl, "WATCHLIST_PATH", tmp_path / "wl.json")
        monkeypatch.setattr(wl, "_LOCK_PATH", tmp_path / "wl.lock")

        ranked = [
            {"symbol": "TEST", "confidence_tier": "HIGH_CONVICTION",
             "score": None, "gap_pct": None},
        ]
        added = wl.auto_add_high_conviction(ranked)
        assert added == 1

        entries = wl.load_watchlist()
        assert entries[0]["symbol"] == "TEST"
        assert "N/A" in entries[0]["note"]

    def test_gap_pct_is_none_score_valid(self, tmp_path, monkeypatch):
        """Arrange: score=8.5, gap_pct=None. Assert: no crash, note correct."""
        import open_prep.watchlist as wl

        monkeypatch.setattr(wl, "WATCHLIST_PATH", tmp_path / "wl.json")
        monkeypatch.setattr(wl, "_LOCK_PATH", tmp_path / "wl.lock")

        ranked = [
            {"symbol": "FOO", "confidence_tier": "HIGH_CONVICTION",
             "score": 8.5, "gap_pct": None},
        ]
        added = wl.auto_add_high_conviction(ranked)
        assert added == 1

        entries = wl.load_watchlist()
        assert "8.50" in entries[0]["note"]
        assert "N/A%" in entries[0]["note"]

    def test_score_and_gap_valid(self, tmp_path, monkeypatch):
        """Arrange: both valid. Assert: old format preserved."""
        import open_prep.watchlist as wl

        monkeypatch.setattr(wl, "WATCHLIST_PATH", tmp_path / "wl.json")
        monkeypatch.setattr(wl, "_LOCK_PATH", tmp_path / "wl.lock")

        ranked = [
            {"symbol": "BAR", "confidence_tier": "HIGH_CONVICTION",
             "score": 7.2, "gap_pct": 3.5},
        ]
        added = wl.auto_add_high_conviction(ranked)
        assert added == 1

        entries = wl.load_watchlist()
        assert "7.20" in entries[0]["note"]
        assert "3.5%" in entries[0]["note"]


# ═══════════════════════════════════════════════════════════════════
# 14) P-3: insider trading safe float
# ═══════════════════════════════════════════════════════════════════

class TestInsiderTradingSafeFloat:
    """_fetch_insider_trading must not crash on non-numeric statistics fields
    returned from /stable/insider-trading/statistics (P-3 fix)."""

    def test_non_numeric_acquired_transactions(self):
        """Arrange: acquiredTransactions='N/A'. Assert: no crash, treated as 0."""
        from open_prep.run_open_prep import _fetch_insider_trading

        mock_client = MagicMock()
        mock_client.get_insider_trading_statistics.return_value = [
            {
                "symbol": "TEST",
                "year": 2026,
                "quarter": 1,
                "acquiredTransactions": "N/A",
                "disposedTransactions": 5,
                "totalAcquired": 0,
                "totalDisposed": 12345.0,
                "acquiredDisposedRatio": 0.0,
            },
        ]

        result = _fetch_insider_trading(
            client=mock_client, symbols=["TEST"]
        )
        assert "TEST" in result
        assert result["TEST"]["insider_buys"] == 0
        assert result["TEST"]["insider_total_bought_value"] == 0.0

    def test_none_total_disposed(self):
        """Arrange: totalDisposed=None. Assert: no crash, value=0."""
        from open_prep.run_open_prep import _fetch_insider_trading

        mock_client = MagicMock()
        mock_client.get_insider_trading_statistics.return_value = [
            {
                "symbol": "FOO",
                "year": 2026,
                "quarter": 1,
                "acquiredTransactions": 3,
                "disposedTransactions": 1,
                "totalAcquired": 1000.0,
                "totalDisposed": None,
            },
        ]

        result = _fetch_insider_trading(
            client=mock_client, symbols=["FOO"]
        )
        assert "FOO" in result
        assert result["FOO"]["insider_total_sold_value"] == 0.0
        assert result["FOO"]["insider_sentiment"] == "net_buy"


# ═══════════════════════════════════════════════════════════════════
# 14b) PR-D3: insider-statistics quarterly aggregates + acceleration
# ═══════════════════════════════════════════════════════════════════

class TestInsiderStatisticsQuarterly:
    """_fetch_insider_trading uses /stable/insider-trading/statistics (PR-D3)."""

    def test_latest_quarter_picked_when_unordered(self):
        """API may return rows out of order — code must sort desc by (year, quarter)."""
        from open_prep.run_open_prep import _fetch_insider_trading

        mock_client = MagicMock()
        mock_client.get_insider_trading_statistics.return_value = [
            {"symbol": "AAPL", "year": 2025, "quarter": 4,
             "acquiredTransactions": 2, "disposedTransactions": 50,
             "totalAcquired": 100.0, "totalDisposed": 999.0,
             "acquiredDisposedRatio": 0.04},
            {"symbol": "AAPL", "year": 2026, "quarter": 1,
             "acquiredTransactions": 10, "disposedTransactions": 3,
             "totalAcquired": 50000.0, "totalDisposed": 1500.0,
             "acquiredDisposedRatio": 3.33},
        ]
        result = _fetch_insider_trading(client=mock_client, symbols=["AAPL"])
        row = result["AAPL"]
        assert row["insider_buys"] == 10  # picked 2026Q1 not 2025Q4
        assert row["insider_sells"] == 3
        assert row["insider_sentiment"] == "net_buy"
        assert row["insider_quarter_label"] == "2026Q1"
        assert row["insider_acquired_disposed_ratio"] == 3.33
        # acceleration = current_quarter (10) - prev_quarter (2) = 8
        assert row["insider_buying_acceleration"] == 8

    def test_single_quarter_no_acceleration(self):
        from open_prep.run_open_prep import _fetch_insider_trading

        mock_client = MagicMock()
        mock_client.get_insider_trading_statistics.return_value = [
            {"symbol": "TSLA", "year": 2026, "quarter": 1,
             "acquiredTransactions": 5, "disposedTransactions": 5,
             "totalAcquired": 1000.0, "totalDisposed": 1000.0,
             "acquiredDisposedRatio": 1.0},
        ]
        result = _fetch_insider_trading(client=mock_client, symbols=["TSLA"])
        row = result["TSLA"]
        assert row["insider_sentiment"] == "neutral"
        assert row["insider_buying_acceleration"] == 5  # vs implicit 0 prev

    def test_universe_filter_caps_lookups(self):
        """Only first _MAX_INSIDER_STATS_LOOKUPS symbols are fetched."""
        from open_prep.run_open_prep import (
            _MAX_INSIDER_STATS_LOOKUPS,
            _fetch_insider_trading,
        )

        mock_client = MagicMock()
        mock_client.get_insider_trading_statistics.return_value = []
        many = [f"SYM{i}" for i in range(_MAX_INSIDER_STATS_LOOKUPS + 10)]
        _fetch_insider_trading(client=mock_client, symbols=many)
        assert mock_client.get_insider_trading_statistics.call_count == _MAX_INSIDER_STATS_LOOKUPS

    def test_per_symbol_failure_isolated(self):
        """One symbol failing must not poison the rest."""
        from open_prep.run_open_prep import _fetch_insider_trading

        def side_effect(sym):
            if sym == "BAD":
                raise RuntimeError("boom")
            return [{"symbol": sym, "year": 2026, "quarter": 1,
                     "acquiredTransactions": 1, "disposedTransactions": 0,
                     "totalAcquired": 100.0, "totalDisposed": 0.0,
                     "acquiredDisposedRatio": None}]

        mock_client = MagicMock()
        mock_client.get_insider_trading_statistics.side_effect = side_effect
        result = _fetch_insider_trading(client=mock_client, symbols=["AAPL", "BAD", "NVDA"])
        assert "AAPL" in result and "NVDA" in result
        assert "BAD" not in result

    def test_empty_universe_short_circuits(self):
        from open_prep.run_open_prep import _fetch_insider_trading

        mock_client = MagicMock()
        result = _fetch_insider_trading(client=mock_client, symbols=[])
        assert result == {}
        mock_client.get_insider_trading_statistics.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# 15) P-4: alerts — _mark_sent only on success
# ═══════════════════════════════════════════════════════════════════

class TestAlertMarkSentOnSuccess:
    """dispatch_alerts should only mark_sent when ≥1 webhook succeeded
    (P-4 fix)."""

    def test_all_webhooks_fail_does_not_mark_sent(self):
        """Arrange: all targets return 500. Assert: symbol NOT throttled."""
        from open_prep import alerts

        alerts._last_sent.clear()

        config = {
            "enabled": True,
            "min_confidence_tier": "HIGH_CONVICTION",
            "throttle_seconds": 600,
            "targets": [
                {"name": "test", "url": "https://example.com/hook", "type": "generic"},
            ],
        }
        ranked = [
            {"symbol": "FAIL", "confidence_tier": "HIGH_CONVICTION",
             "gap_pct": 3.0, "score": 8.0},
        ]

        with patch.object(alerts, "_send_webhook", return_value={"status": 500, "error": "fail"}):
            alerts.dispatch_alerts(ranked, regime="RISK_ON", config=config)

        # Symbol should NOT be throttled because webhook failed
        assert not alerts._is_throttled("FAIL", 600)

    def test_one_success_marks_sent(self):
        """Arrange: one target returns 200. Assert: symbol IS throttled."""
        from open_prep import alerts

        alerts._last_sent.clear()

        config = {
            "enabled": True,
            "min_confidence_tier": "HIGH_CONVICTION",
            "throttle_seconds": 600,
            "targets": [
                {"name": "test", "url": "https://example.com/hook", "type": "generic"},
            ],
        }
        ranked = [
            {"symbol": "OK", "confidence_tier": "HIGH_CONVICTION",
             "gap_pct": 3.0, "score": 8.0},
        ]

        with patch.object(alerts, "_send_webhook", return_value={"status": 200, "body": "ok"}):
            alerts.dispatch_alerts(ranked, regime="RISK_ON", config=config)

        assert alerts._is_throttled("OK", 600)


# ═══════════════════════════════════════════════════════════════════
# 16) P-5: alerts — _last_sent pruning
# ═══════════════════════════════════════════════════════════════════

class TestAlertThrottlePruning:
    """_prune_stale_entries must cap _last_sent growth (P-5 fix)."""

    def test_prune_removes_stale(self):
        """Arrange: 600 entries, all stale. Assert: pruned to near 0."""
        import time

        from open_prep import alerts

        alerts._last_sent.clear()
        now = time.time()
        # Add 600 stale entries (older than 600s)
        for i in range(600):
            alerts._last_sent[f"SYM{i}"] = now - 700

        alerts._prune_stale_entries(throttle_seconds=600)
        assert len(alerts._last_sent) == 0

    def test_prune_keeps_fresh(self):
        """Arrange: 600 entries, half fresh. Assert: only stale removed."""
        import time

        from open_prep import alerts

        alerts._last_sent.clear()
        now = time.time()
        for i in range(300):
            alerts._last_sent[f"STALE{i}"] = now - 700
        for i in range(300):
            alerts._last_sent[f"FRESH{i}"] = now - 10

        alerts._prune_stale_entries(throttle_seconds=600)
        assert len(alerts._last_sent) == 300
        assert all(k.startswith("FRESH") for k in alerts._last_sent)


# ═══════════════════════════════════════════════════════════════════
# 17) P-7: diff.py — score 0.0 not coerced
# ═══════════════════════════════════════════════════════════════════

class TestDiffScoreZeroNotCoerced:
    """A legitimate score of 0.0 must not be treated as None (P-7 fix)."""

    def test_score_zero_shows_change(self):
        """Arrange: prev score=5.0, curr score=0.0. Assert: delta=-5.0."""
        from open_prep.diff import compute_diff

        previous = {
            "regime": "RISK_ON",
            "candidates": [
                {"symbol": "TEST", "score": 5.0, "gap_pct": 1.0, "confidence_tier": "STANDARD"},
            ],
        }
        current = {
            "regime": "RISK_ON",
            "candidates": [
                {"symbol": "TEST", "score": 0.0, "gap_pct": 1.0, "confidence_tier": "STANDARD"},
            ],
        }
        diff = compute_diff(previous, current)
        assert len(diff["score_changes"]) == 1
        assert diff["score_changes"][0]["curr_score"] == 0.0
        assert diff["score_changes"][0]["delta"] == -5.0

    def test_score_none_treated_as_zero(self):
        """Arrange: prev score=None. Assert: treated as 0 (to_float default)."""
        from open_prep.diff import compute_diff

        previous = {
            "regime": "RISK_ON",
            "candidates": [
                {"symbol": "TEST", "score": None, "gap_pct": 1.0, "confidence_tier": "STANDARD"},
            ],
        }
        current = {
            "regime": "RISK_ON",
            "candidates": [
                {"symbol": "TEST", "score": 3.0, "gap_pct": 1.0, "confidence_tier": "STANDARD"},
            ],
        }
        diff = compute_diff(previous, current)
        assert len(diff["score_changes"]) == 1
        assert diff["score_changes"][0]["prev_score"] == 0.0
        assert diff["score_changes"][0]["curr_score"] == 3.0


# ═══════════════════════════════════════════════════════════════════
# G-1: to_float NaN guard
# ═══════════════════════════════════════════════════════════════════

class TestToFloatNanGuard:
    """to_float must return default for NaN, not propagate it."""

    def test_nan_returns_default(self):
        """Arrange: pass float('nan'). Assert: returns 0.0 (default)."""
        from open_prep.utils import to_float

        result = to_float(float("nan"))
        assert result == 0.0
        assert not math.isnan(result)

    def test_nan_returns_custom_default(self):
        """Arrange: pass NaN with default=-1. Assert: returns -1."""
        from open_prep.utils import to_float

        result = to_float(float("nan"), default=-1.0)
        assert result == -1.0

    def test_nan_string_returns_default(self):
        """Arrange: pass 'nan' string. Assert: returns 0.0 (NaN guard)."""
        from open_prep.utils import to_float

        result = to_float("nan")
        assert result == 0.0
        assert not math.isnan(result)

    def test_inf_returns_default(self):
        """Arrange: pass float('inf'). Assert: returns 0.0 (non-finite guard)."""
        from open_prep.utils import to_float

        result = to_float(float("inf"))
        assert result == 0.0

    def test_inf_returns_custom_default(self):
        """Arrange: pass infinity with default=-1. Assert: returns -1."""
        from open_prep.utils import to_float

        result = to_float(float("-inf"), default=-1.0)
        assert result == -1.0

    def test_normal_values_unaffected(self):
        """Arrange: normal numeric values. Assert: unchanged."""
        from open_prep.utils import to_float

        assert to_float(42) == 42.0
        assert to_float("3.14") == 3.14
        assert to_float(0) == 0.0
        assert to_float(0.0) == 0.0

    def test_none_returns_default(self):
        """Arrange: None. Assert: returns default."""
        from open_prep.utils import to_float

        assert to_float(None) == 0.0
        assert to_float(None, default=5.0) == 5.0

    def test_non_numeric_returns_default(self):
        """Arrange: non-numeric string. Assert: returns default."""
        from open_prep.utils import to_float

        assert to_float("abc") == 0.0
        assert to_float("") == 0.0


# ═══════════════════════════════════════════════════════════════════
# G-2: _prev_trading_day fallback returns last checked, not d-1
# ═══════════════════════════════════════════════════════════════════

class TestPrevTradingDayFallback:
    """_prev_trading_day fallback should not return a weekend/holiday."""

    def test_normal_weekday(self):
        """Arrange: Monday. Assert: returns previous Friday."""
        from open_prep.run_open_prep import _prev_trading_day

        monday = date(2025, 1, 6)  # Monday
        result = _prev_trading_day(monday)
        assert result == date(2025, 1, 3)  # Friday
        assert result.weekday() == 4  # Friday

    def test_after_long_weekend(self):
        """Arrange: Tuesday after MLK Day. Assert: returns Friday before."""
        from open_prep.run_open_prep import _prev_trading_day

        # MLK Day 2025 is Monday Jan 20
        tuesday = date(2025, 1, 21)
        result = _prev_trading_day(tuesday)
        assert result == date(2025, 1, 17)  # Friday before MLK

    def test_fallback_exhausted_does_not_return_weekend(self):
        """Arrange: mock _is_us_equity_trading_day to always return False.
        Assert: fallback returns the last iterated date (not d-1 which might be Sunday)."""
        from open_prep.run_open_prep import _prev_trading_day

        # If we call on a Monday and all days are non-trading,
        # fallback should still return a date that's at most 15 days back
        with patch("newsstack_fmp._market_cal.is_us_equity_trading_day", return_value=False):
            monday = date(2025, 1, 6)
            result = _prev_trading_day(monday)
            # Should NOT return d-1 (Sunday Jan 5)
            assert result != monday - timedelta(days=1)
            # Should return the last checked date: Jan 6 - 15 = Dec 22
            expected_last_checked = monday - timedelta(days=15)
            assert result == expected_last_checked


# ═══════════════════════════════════════════════════════════════════
# G-3: ATR cache atomic write
# ═══════════════════════════════════════════════════════════════════

class TestAtrCacheAtomicWrite:
    """ATR cache must use atomic write to prevent corruption."""

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """Arrange: save ATR cache. Act: load it. Assert: data matches."""
        from open_prep.run_open_prep import (
            _load_atr_cache,
            _save_atr_cache,
        )

        monkeypatch.setattr("open_prep.run_open_prep.ATR_CACHE_DIR", tmp_path)
        test_date = date(2025, 6, 15)
        atr_map = {"AAPL": 2.5, "MSFT": 1.8}
        momentum_map = {"AAPL": 0.3, "MSFT": -0.1}
        prev_close_map = {"AAPL": 150.0, "MSFT": 300.0}

        _save_atr_cache(
            as_of=test_date,
            period=14,
            atr_map=atr_map,
            momentum_map=momentum_map,
            prev_close_map=prev_close_map,
        )

        loaded_atr, loaded_momentum, loaded_close = _load_atr_cache(test_date, 14)
        assert loaded_atr["AAPL"] == 2.5
        assert loaded_atr["MSFT"] == 1.8
        assert loaded_momentum["AAPL"] == 0.3
        assert loaded_close["AAPL"] == 150.0

    def test_save_no_tmp_files_left(self, tmp_path, monkeypatch):
        """Assert: no .tmp files remain after successful save."""
        from open_prep.run_open_prep import _save_atr_cache

        monkeypatch.setattr("open_prep.run_open_prep.ATR_CACHE_DIR", tmp_path)
        _save_atr_cache(
            as_of=date(2025, 6, 15),
            period=14,
            atr_map={"AAPL": 2.5},
            momentum_map={"AAPL": 0.3},
            prev_close_map={"AAPL": 150.0},
        )
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


# ═══════════════════════════════════════════════════════════════════
# G-4: Insider trading NaN in price/quantity → 0.0 (via G-1 fix)
# ═══════════════════════════════════════════════════════════════════

class TestInsiderTradingNanSafety:
    """Insider trading sums must not produce NaN when API data has NaN."""

    def test_nan_price_yields_zero_value(self):
        """Arrange: insider trade with NaN price. Assert: value is 0."""
        from open_prep.utils import to_float

        # Simulates: _to_float(r.get("price")) where price is NaN
        price = to_float(float("nan"))
        quantity = to_float(100)
        total = price * quantity
        assert total == 0.0
        assert not math.isnan(total)

    def test_nan_quantity_yields_zero_value(self):
        """Arrange: insider trade with NaN quantity. Assert: value is 0."""
        from open_prep.utils import to_float

        price = to_float(50.0)
        quantity = to_float(float("nan"))
        total = price * quantity
        assert total == 0.0


# ═══════════════════════════════════════════════════════════════════
# G-5: Weekend/holiday gap_scope DAILY vs STRETCH_ONLY
# ═══════════════════════════════════════════════════════════════════

class TestGapScopeWeekendHoliday:
    """gap_scope STRETCH_ONLY must only fire after non-trading stretch."""

    def test_daily_scope_fires_every_trading_day(self):
        """Arrange: 5 consecutive weekdays. Assert: all are gap days."""
        from open_prep.run_open_prep import GAP_SCOPE_DAILY, _is_gap_day

        # Mon-Fri of a regular week
        monday = date(2025, 1, 6)
        for i in range(5):
            d = monday + timedelta(days=i)
            assert _is_gap_day(d, GAP_SCOPE_DAILY) is True

    def test_stretch_only_fires_after_weekend(self):
        """Arrange: Monday after normal weekend. Assert: is a gap day."""
        from open_prep.run_open_prep import GAP_SCOPE_STRETCH_ONLY, _is_gap_day

        monday = date(2025, 1, 6)
        assert _is_gap_day(monday, GAP_SCOPE_STRETCH_ONLY) is True

    def test_stretch_only_skips_mid_week(self):
        """Arrange: Tuesday in a normal week. Assert: NOT a gap day."""
        from open_prep.run_open_prep import GAP_SCOPE_STRETCH_ONLY, _is_gap_day

        tuesday = date(2025, 1, 7)
        assert _is_gap_day(tuesday, GAP_SCOPE_STRETCH_ONLY) is False

    def test_stretch_only_fires_after_holiday(self):
        """Arrange: day after MLK Day. Assert: is a gap day."""
        from open_prep.run_open_prep import GAP_SCOPE_STRETCH_ONLY, _is_gap_day

        # MLK Day 2025 is Monday Jan 20; Tuesday Jan 21 is after a 3-day stretch
        tuesday_after_mlk = date(2025, 1, 21)
        assert _is_gap_day(tuesday_after_mlk, GAP_SCOPE_STRETCH_ONLY) is True

    def test_daily_scope_weekend_is_not_gap_day(self):
        """Arrange: Saturday. Assert: NOT a gap day even in DAILY mode."""
        from open_prep.run_open_prep import GAP_SCOPE_DAILY, _is_gap_day

        saturday = date(2025, 1, 4)
        assert _is_gap_day(saturday, GAP_SCOPE_DAILY) is False


# ═══════════════════════════════════════════════════════════════════
# G-6: Premarket timestamp missing → gap_reason
# ═══════════════════════════════════════════════════════════════════

class TestPremarketTimestampMissingGapReason:
    """When premarket data has no timestamp, gap_reason must explain why."""

    def test_missing_timestamp_premarket_source(self):
        """Arrange: premarket price available but no timestamp.
        Assert: gap_reason='missing_quote_timestamp'."""
        from open_prep.run_open_prep import GAP_MODE_PREMARKET_INDICATIVE, _compute_gap_for_quote

        quote = {
            "symbol": "TEST",
            "previousClose": 100.0,
            "preMarketPrice": 105.0,
        }
        # Run during premarket hours (08:00 NY)
        run_dt = datetime(2025, 1, 6, 13, 0, tzinfo=UTC)  # 08:00 ET
        result = _compute_gap_for_quote(
            quote,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        assert result["gap_available"] is False
        assert result["gap_reason"] == "missing_quote_timestamp"

    def test_missing_timestamp_spot_source(self):
        """Arrange: only spot price, no timestamp.
        Assert: gap_reason='stale_quote_unknown_timestamp'."""
        from open_prep.run_open_prep import GAP_MODE_PREMARKET_INDICATIVE, _compute_gap_for_quote

        quote = {
            "symbol": "TEST",
            "previousClose": 100.0,
            "price": 102.0,
        }
        run_dt = datetime(2025, 1, 6, 13, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(
            quote,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        assert result["gap_available"] is False
        assert result["gap_reason"] == "stale_quote_unknown_timestamp"

    def test_valid_timestamp_produces_gap(self):
        """Arrange: premarket price + valid timestamp. Assert: gap computed."""
        from open_prep.run_open_prep import GAP_MODE_PREMARKET_INDICATIVE, _compute_gap_for_quote

        quote = {
            "symbol": "TEST",
            "previousClose": 100.0,
            "preMarketPrice": 105.0,
            "timestamp": 1736150400,  # epoch seconds for 2025-01-06T08:00:00 UTC
        }
        run_dt = datetime(2025, 1, 6, 13, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(
            quote,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        assert result["gap_available"] is True
        assert result["gap_reason"] == "ok"
        assert result["gap_pct"] == pytest.approx(5.0, abs=0.01)


# ═══════════════════════════════════════════════════════════════════
# G-7: _compute_gap_for_quote — all gap_reason paths
# ═══════════════════════════════════════════════════════════════════

class TestComputeGapAllReasonPaths:
    """Every gap_reason code from _compute_gap_for_quote must be reachable
    and return correct metadata."""

    def test_mode_off_returns_mode_off_reason(self):
        """gap_mode=OFF → gap_reason='mode_off', gap_available=False."""
        from open_prep.run_open_prep import GAP_MODE_OFF, _compute_gap_for_quote

        quote = {"symbol": "X", "previousClose": 100.0, "price": 105.0}
        run_dt = datetime(2025, 1, 6, 13, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(quote, run_dt_utc=run_dt, gap_mode=GAP_MODE_OFF)
        assert result["gap_reason"] == "mode_off"
        assert result["gap_available"] is False
        assert result["gap_pct"] == 0.0

    def test_not_trading_day_saturday(self):
        """Saturday → gap_reason='not_trading_day'."""
        from open_prep.run_open_prep import GAP_MODE_PREMARKET_INDICATIVE, _compute_gap_for_quote

        quote = {"symbol": "X", "previousClose": 100.0, "preMarketPrice": 105.0, "timestamp": 1}
        # Saturday 2025-01-04
        run_dt = datetime(2025, 1, 4, 13, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(
            quote, run_dt_utc=run_dt, gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        assert result["gap_reason"] == "not_trading_day"
        assert result["gap_available"] is False

    def test_scope_stretch_only_mid_week(self):
        """STRETCH_ONLY scope on a mid-week day → gap_reason='scope_stretch_only'."""
        from open_prep.run_open_prep import (
            GAP_MODE_PREMARKET_INDICATIVE,
            GAP_SCOPE_STRETCH_ONLY,
            _compute_gap_for_quote,
        )

        quote = {"symbol": "X", "previousClose": 100.0, "preMarketPrice": 105.0, "timestamp": 1}
        # Tuesday 2025-01-07 (normal mid-week, not after a stretch)
        run_dt = datetime(2025, 1, 7, 13, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(
            quote,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
            gap_scope=GAP_SCOPE_STRETCH_ONLY,
        )
        assert result["gap_reason"] == "scope_stretch_only"
        assert result["gap_available"] is False

    def test_rth_open_unavailable_before_930(self):
        """RTH_OPEN mode before 9:30 ET → gap_reason='rth_open_unavailable'."""
        from open_prep.run_open_prep import GAP_MODE_RTH_OPEN, _compute_gap_for_quote

        quote = {"symbol": "X", "previousClose": 100.0, "open": 105.0}
        # 8:00 ET = 13:00 UTC on a Monday
        run_dt = datetime(2025, 1, 6, 13, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(
            quote, run_dt_utc=run_dt, gap_mode=GAP_MODE_RTH_OPEN,
        )
        assert result["gap_reason"] == "rth_open_unavailable"
        assert result["gap_available"] is False

    def test_rth_open_available_after_930(self):
        """RTH_OPEN mode after 9:30 ET → gap computed."""
        from open_prep.run_open_prep import GAP_MODE_RTH_OPEN, _compute_gap_for_quote

        quote = {"symbol": "X", "previousClose": 100.0, "open": 103.0}
        # 10:00 ET = 15:00 UTC
        run_dt = datetime(2025, 1, 6, 15, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(
            quote, run_dt_utc=run_dt, gap_mode=GAP_MODE_RTH_OPEN,
        )
        assert result["gap_reason"] == "ok"
        assert result["gap_available"] is True
        assert result["gap_pct"] == pytest.approx(3.0, abs=0.01)

    def test_premarket_before_4am_et(self):
        """Before 4am ET, no premarket window → gap_reason='premarket_unavailable'."""
        from open_prep.run_open_prep import GAP_MODE_PREMARKET_INDICATIVE, _compute_gap_for_quote

        quote = {
            "symbol": "X",
            "previousClose": 100.0,
            "preMarketPrice": 105.0,
            "timestamp": 1736132400,
        }
        # 3:00 ET = 08:00 UTC on Monday
        run_dt = datetime(2025, 1, 6, 8, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(
            quote, run_dt_utc=run_dt, gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
        )
        assert result["gap_reason"] == "premarket_unavailable"
        assert result["gap_available"] is False

    def test_stretch_scope_monday_computes_gap(self):
        """STRETCH_ONLY scope on Monday after weekend → gap is computed."""
        from open_prep.run_open_prep import (
            GAP_MODE_PREMARKET_INDICATIVE,
            GAP_SCOPE_STRETCH_ONLY,
            _compute_gap_for_quote,
        )

        quote = {
            "symbol": "X",
            "previousClose": 100.0,
            "preMarketPrice": 107.0,
            "timestamp": 1736150400,
        }
        # Monday 2025-01-06 at 8am ET = 13:00 UTC
        run_dt = datetime(2025, 1, 6, 13, 0, tzinfo=UTC)
        result = _compute_gap_for_quote(
            quote,
            run_dt_utc=run_dt,
            gap_mode=GAP_MODE_PREMARKET_INDICATIVE,
            gap_scope=GAP_SCOPE_STRETCH_ONLY,
        )
        assert result["gap_available"] is True
        assert result["gap_reason"] == "ok"
        assert result["gap_pct"] == pytest.approx(7.0, abs=0.01)
        assert result["is_stretch_session"] is True


# ═══════════════════════════════════════════════════════════════════
# G-8: detect_consolidation — bb_squeeze_threshold=0 guard
# ═══════════════════════════════════════════════════════════════════

class TestDetectConsolidationZeroThreshold:
    """detect_consolidation must not crash on bb_squeeze_threshold=0."""

    def test_zero_threshold_no_crash(self):
        """bb_squeeze_threshold=0 → clamped to 0.001, no ZeroDivisionError."""
        from open_prep.technical_analysis import detect_consolidation

        result = detect_consolidation(
            bb_width_pct=0.5, adx=15.0, bb_squeeze_threshold=0.0,
        )
        assert isinstance(result, dict)
        assert "is_consolidating" in result

    def test_negative_threshold_no_crash(self):
        """Negative threshold is also clamped, no crash."""
        from open_prep.technical_analysis import detect_consolidation

        result = detect_consolidation(
            bb_width_pct=5.0, adx=10.0, bb_squeeze_threshold=-1.0,
        )
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════
# G-9: v2 pipeline does not silently drop SKIP-bucket candidates
# ═══════════════════════════════════════════════════════════════════

class TestV2PipelineNoSilentDrops:
    """rank_candidates_v2 must operate on ALL quotes including those
    that v1 classify_long_gap would bucket as SKIP."""

    def test_skip_bucket_candidate_still_scored(self):
        """A quote with tiny gap + low ext_hours (v1 SKIP) is still scored
        by rank_candidates_v2."""
        from open_prep.scorer import rank_candidates_v2

        quote = _make_quote(
            symbol="SKIP_ME",
            gap_pct=0.1,
            ext_hours_score=0.0,
            ext_volume_ratio=0.0,
            atr=1.2,
        )
        ranked, filtered_out = rank_candidates_v2(
            [quote], bias=0.2, top_n=10,
        )
        # Must appear in ranked (passed hard filters) — NOT silently dropped
        all_symbols = [r["symbol"] for r in ranked] + [f["symbol"] for f in filtered_out]
        assert "SKIP_ME" in all_symbols

    def test_multiple_quotes_all_processed(self):
        """All symbols in quote list appear in output (ranked or filtered_out)."""
        from open_prep.scorer import rank_candidates_v2

        quotes = [
            _make_quote(symbol="AAA", gap_pct=5.0, atr=1.2),
            _make_quote(symbol="BBB", gap_pct=0.1, atr=1.2),
            _make_quote(symbol="CCC", gap_pct=-1.0, atr=1.2),
        ]
        ranked, filtered_out = rank_candidates_v2(quotes, bias=0.2, top_n=10)
        output_symbols = {r["symbol"] for r in ranked} | {f["symbol"] for f in filtered_out}
        assert output_symbols == {"AAA", "BBB", "CCC"}


# ═══════════════════════════════════════════════════════════════════
# G-10: Holiday edge cases — Good Friday, Juneteenth
# ═══════════════════════════════════════════════════════════════════

class TestHolidayEdgeCases:
    """Verify less common holidays are correctly included."""

    def test_good_friday_2025(self):
        """Good Friday 2025-04-18 is a market holiday."""
        from newsstack_fmp._market_cal import (
            us_equity_market_holidays as _us_equity_market_holidays,
        )

        holidays = _us_equity_market_holidays(2025)
        assert date(2025, 4, 18) in holidays

    def test_juneteenth_2025(self):
        """Juneteenth 2025-06-19 is a market holiday."""
        from newsstack_fmp._market_cal import (
            us_equity_market_holidays as _us_equity_market_holidays,
        )

        holidays = _us_equity_market_holidays(2025)
        assert date(2025, 6, 19) in holidays

    def test_mlk_day_2026(self):
        """MLK Day 2026 is Jan 19 (third Monday)."""
        from newsstack_fmp._market_cal import (
            us_equity_market_holidays as _us_equity_market_holidays,
        )

        holidays = _us_equity_market_holidays(2026)
        assert date(2026, 1, 19) in holidays

    def test_christmas_on_sunday_observed_monday_2022(self):
        """Christmas 2022 fell on Sunday → observed Monday Dec 26."""
        from newsstack_fmp._market_cal import (
            us_equity_market_holidays as _us_equity_market_holidays,
        )

        holidays = _us_equity_market_holidays(2022)
        assert date(2022, 12, 26) in holidays  # Observed Monday

    def test_new_year_on_saturday_observed_friday_2022(self):
        """New Year 2022 fell on Saturday → observed Friday Dec 31 2021.
        The cross-year observed holiday MUST be recognized as a non-trading day."""
        from newsstack_fmp._market_cal import (
            is_us_equity_trading_day as _is_us_equity_trading_day,
        )
        from newsstack_fmp._market_cal import (
            us_equity_market_holidays as _us_equity_market_holidays,
        )

        # The observed Dec 31 holiday lives in the 2022 holiday set
        holidays_2022 = _us_equity_market_holidays(2022)
        assert date(2021, 12, 31) in holidays_2022

        # Crucially: _is_us_equity_trading_day must return False for Dec 31, 2021
        assert _is_us_equity_trading_day(date(2021, 12, 31)) is False

    def test_prev_trading_day_skips_good_friday(self):
        """Monday after Good Friday 2025 → prev = Thursday Apr 17."""
        from open_prep.run_open_prep import _prev_trading_day

        # Good Friday 2025 = April 18. Monday after = April 21.
        result = _prev_trading_day(date(2025, 4, 21))
        assert result == date(2025, 4, 17)

    def test_prev_trading_day_skips_cross_year_dec31(self):
        """Jan 2, 2028 → prev = Dec 30, 2027 (Dec 31 is observed New Year)."""
        from open_prep.run_open_prep import _is_us_equity_trading_day, _prev_trading_day

        # Jan 1 2028 = Saturday → observed Dec 31 2027 (Friday, closed)
        assert _is_us_equity_trading_day(date(2027, 12, 31)) is False
        # Jan 2 2028 is Sunday, Jan 3 2028 is Monday
        result = _prev_trading_day(date(2028, 1, 3))
        assert result == date(2027, 12, 30)  # Thursday

    def test_stretch_scope_after_good_friday(self):
        """Monday after Good Friday (3-day stretch) is a gap day."""
        from open_prep.run_open_prep import GAP_SCOPE_STRETCH_ONLY, _is_gap_day

        assert _is_gap_day(date(2025, 4, 21), GAP_SCOPE_STRETCH_ONLY) is True


# ═══════════════════════════════════════════════════════════════════
# G-11: _pick_indicative_price cascading fallback
# ═══════════════════════════════════════════════════════════════════

class TestPickIndicativePriceCascade:
    """_pick_indicative_price must cascade through price sources correctly."""

    def test_premarket_price_preferred(self):
        """preMarketPrice is preferred over extendedPrice and price."""
        from open_prep.run_open_prep import _pick_indicative_price

        quote = {"preMarketPrice": 105.0, "extendedPrice": 102.0, "price": 100.0}
        px, source = _pick_indicative_price(quote)
        assert px == 105.0
        assert source == "premarket"

    def test_extended_fallback(self):
        """When premarket is absent, fall back to extendedPrice."""
        from open_prep.run_open_prep import _pick_indicative_price

        quote = {"extendedPrice": 102.0, "price": 100.0}
        px, source = _pick_indicative_price(quote)
        assert px == 102.0
        assert source == "extended"

    def test_spot_fallback(self):
        """When premarket and extended are absent, fall back to price."""
        from open_prep.run_open_prep import _pick_indicative_price

        quote = {"price": 100.0}
        px, source = _pick_indicative_price(quote)
        assert px == 100.0
        assert source == "spot"

    def test_all_missing_returns_zero(self):
        """When all price fields are absent, returns (0.0, 'spot')."""
        from open_prep.run_open_prep import _pick_indicative_price

        px, _source = _pick_indicative_price({})
        assert px == 0.0

    def test_zero_premarket_falls_through(self):
        """preMarketPrice=0 should fall through to next source."""
        from open_prep.run_open_prep import _pick_indicative_price

        quote = {"preMarketPrice": 0.0, "extendedPrice": 0.0, "price": 99.0}
        px, source = _pick_indicative_price(quote)
        assert px == 99.0
        assert source == "spot"


# ═══════════════════════════════════════════════════════════════════
# 16) PR-D1: beneficial-ownership enrichment (SC 13D / 13G)
# ═══════════════════════════════════════════════════════════════════

class TestBeneficialOwnershipEnrichment:
    """_fetch_beneficial_ownership aggregates SC 13D/G filings and flags
    fresh ones inside the configured window."""

    def test_recent_filing_within_window_is_flagged(self):
        from open_prep.run_open_prep import _fetch_beneficial_ownership

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_acquisition_of_beneficial_ownership.return_value = [
            {
                "symbol": "AAPL",
                "filingDate": "2026-04-20",
                "nameOfReportingPerson": "Acme Capital",
                "percentOfClass": "5.6",
                "url": "https://sec.gov/...",
            },
            {
                "symbol": "AAPL",
                "filingDate": "2024-02-14",
                "nameOfReportingPerson": "Stale LLC",
                "percentOfClass": "5.1",
            },
        ]
        result = _fetch_beneficial_ownership(
            client=mock_client, symbols=["AAPL"], today=today
        )
        assert "AAPL" in result
        row = result["AAPL"]
        assert row["beneficial_owner_count"] == 2
        assert row["beneficial_owner_recent"] is True
        assert row["beneficial_owner_recent_count"] == 1
        assert row["beneficial_owner_latest_filer"] == "Acme Capital"
        assert row["beneficial_owner_latest_pct"] == 5.6
        assert row["beneficial_owner_latest_date"] == "2026-04-20"

    def test_only_stale_filings_not_flagged(self):
        from open_prep.run_open_prep import _fetch_beneficial_ownership

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_acquisition_of_beneficial_ownership.return_value = [
            {
                "symbol": "TSLA",
                "filingDate": "2022-03-11",
                "nameOfReportingPerson": "BlackRock, Inc.",
                "percentOfClass": "5.3",
            },
        ]
        result = _fetch_beneficial_ownership(
            client=mock_client, symbols=["TSLA"], today=today
        )
        assert result["TSLA"]["beneficial_owner_recent"] is False
        assert result["TSLA"]["beneficial_owner_recent_count"] == 0
        assert result["TSLA"]["beneficial_owner_latest_pct"] == 5.3

    def test_empty_or_failed_lookup_returns_no_entry(self):
        from open_prep.run_open_prep import _fetch_beneficial_ownership

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_acquisition_of_beneficial_ownership.side_effect = [
            [],  # GME — no filings
            RuntimeError("boom"),  # FOO — provider fail
        ]
        result = _fetch_beneficial_ownership(
            client=mock_client, symbols=["GME", "FOO"], today=today
        )
        assert "GME" not in result
        assert "FOO" not in result

    def test_non_numeric_percent_does_not_crash(self):
        from open_prep.run_open_prep import _fetch_beneficial_ownership

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_acquisition_of_beneficial_ownership.return_value = [
            {
                "symbol": "NVDA",
                "filingDate": "2026-04-25",
                "nameOfReportingPerson": "Mystery LP",
                "percentOfClass": "N/A",
            },
        ]
        result = _fetch_beneficial_ownership(
            client=mock_client, symbols=["NVDA"], today=today
        )
        assert result["NVDA"]["beneficial_owner_latest_pct"] is None
        assert result["NVDA"]["beneficial_owner_recent"] is True

    def test_lookup_cap_respected(self):
        from open_prep.run_open_prep import (
            _MAX_BENEFICIAL_OWNERSHIP_LOOKUPS,
            _fetch_beneficial_ownership,
        )

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_acquisition_of_beneficial_ownership.return_value = []
        symbols = [f"S{i}" for i in range(_MAX_BENEFICIAL_OWNERSHIP_LOOKUPS + 10)]
        _fetch_beneficial_ownership(
            client=mock_client, symbols=symbols, today=today
        )
        assert (
            mock_client.get_acquisition_of_beneficial_ownership.call_count
            == _MAX_BENEFICIAL_OWNERSHIP_LOOKUPS
        )


# ═══════════════════════════════════════════════════════════════════
# 17) PR-D2: political-trades enrichment (Senate + House)
# ═══════════════════════════════════════════════════════════════════

class TestPoliticalTradesEnrichment:
    """_fetch_political_trades aggregates Senate + House disclosures, scoped
    to the universe and the freshness window."""

    def test_fresh_senate_buy_aggregates_correctly(self):
        from open_prep.run_open_prep import _fetch_political_trades

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_senate_trades_latest.return_value = [
            {
                "symbol": "AAPL",
                "disclosureDate": "2026-04-20",
                "transactionDate": "2026-04-15",
                "type": "Purchase",
                "office": "John Boozman",
            },
            {
                "symbol": "AAPL",
                "disclosureDate": "2026-04-22",
                "type": "Sale (Partial)",
                "office": "Tommy Tuberville",
            },
            {
                "symbol": "OUTSIDE",
                "disclosureDate": "2026-04-25",
                "type": "Purchase",
                "office": "X",
            },
        ]
        mock_client.get_house_trades_latest.return_value = []
        result = _fetch_political_trades(
            client=mock_client, symbols=["AAPL", "MSFT"], today=today
        )
        assert "AAPL" in result
        assert "OUTSIDE" not in result  # not in universe
        assert "MSFT" not in result  # no disclosures
        row = result["AAPL"]
        assert row["politician_buy_count"] == 1
        assert row["politician_sell_count"] == 1
        assert row["politician_net"] == 0
        assert row["politician_sentiment"] == "neutral"
        assert row["politician_senate_count"] == 2
        assert row["politician_house_count"] == 0
        assert row["politician_recent"] is True
        assert "John Boozman" in row["politician_recent_filers"]
        assert row["politician_latest_disclosure_date"] == "2026-04-22"

    def test_house_and_senate_combine(self):
        from open_prep.run_open_prep import _fetch_political_trades

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_senate_trades_latest.return_value = [
            {"symbol": "NVDA", "disclosureDate": "2026-04-20",
             "type": "Purchase", "office": "Senator A"},
        ]
        mock_client.get_house_trades_latest.return_value = [
            {"symbol": "NVDA", "disclosureDate": "2026-04-21",
             "type": "Purchase", "office": "Rep. B"},
            {"symbol": "NVDA", "disclosureDate": "2026-04-22",
             "type": "Purchase", "office": "Rep. C"},
        ]
        result = _fetch_political_trades(
            client=mock_client, symbols=["NVDA"], today=today
        )
        row = result["NVDA"]
        assert row["politician_senate_count"] == 1
        assert row["politician_house_count"] == 2
        assert row["politician_buy_count"] == 3
        assert row["politician_net"] == 3
        assert row["politician_sentiment"] == "net_buy"
        assert row["politician_emoji"] == "🟢"

    def test_stale_disclosure_filtered_out(self):
        from open_prep.run_open_prep import _fetch_political_trades

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_senate_trades_latest.return_value = [
            {"symbol": "TSLA", "disclosureDate": "2025-12-01",
             "type": "Purchase", "office": "Old Senator"},
        ]
        mock_client.get_house_trades_latest.return_value = []
        result = _fetch_political_trades(
            client=mock_client, symbols=["TSLA"], today=today
        )
        assert "TSLA" not in result  # stale, filtered

    def test_provider_failure_returns_partial(self):
        from open_prep.run_open_prep import _fetch_political_trades

        today = date(2026, 4, 27)
        mock_client = MagicMock()
        mock_client.get_senate_trades_latest.side_effect = RuntimeError("boom")
        mock_client.get_house_trades_latest.return_value = [
            {"symbol": "GME", "disclosureDate": "2026-04-25",
             "type": "Purchase", "office": "Rep. X"},
        ]
        result = _fetch_political_trades(
            client=mock_client, symbols=["GME"], today=today
        )
        assert "GME" in result
        assert result["GME"]["politician_house_count"] == 1
        assert result["GME"]["politician_senate_count"] == 0

    def test_empty_universe_short_circuits(self):
        from open_prep.run_open_prep import _fetch_political_trades

        mock_client = MagicMock()
        result = _fetch_political_trades(
            client=mock_client, symbols=[], today=date(2026, 4, 27)
        )
        assert result == {}
        mock_client.get_senate_trades_latest.assert_not_called()
        mock_client.get_house_trades_latest.assert_not_called()
