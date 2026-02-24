"""Production Gatekeeper tests — validates fail-open, no hard-gates,
determinism, and observability constraints.

Each test case follows Arrange / Act / Assert structure and targets a
specific production-readiness issue identified during the gatekeeper
review.
"""
from __future__ import annotations

import math
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
        from open_prep.run_open_prep import _is_gap_day, GAP_SCOPE_DAILY

        # 2025-06-16 is Monday — normal trading day
        assert _is_gap_day(date(2025, 6, 16), GAP_SCOPE_DAILY) is True

    def test_daily_scope_saturday(self):
        """DAILY scope: Saturday is not a trading day → no gap."""
        from open_prep.run_open_prep import _is_gap_day, GAP_SCOPE_DAILY

        assert _is_gap_day(date(2025, 6, 14), GAP_SCOPE_DAILY) is False

    def test_stretch_scope_monday_is_gap_day(self):
        """STRETCH_ONLY: Monday after a regular weekend is a stretch→ gap day."""
        from open_prep.run_open_prep import _is_gap_day, GAP_SCOPE_STRETCH_ONLY

        assert _is_gap_day(date(2025, 6, 16), GAP_SCOPE_STRETCH_ONLY) is True

    def test_stretch_scope_tuesday_is_not_gap_day(self):
        """STRETCH_ONLY: Tuesday (after a normal Monday) is NOT a stretch."""
        from open_prep.run_open_prep import _is_gap_day, GAP_SCOPE_STRETCH_ONLY

        assert _is_gap_day(date(2025, 6, 17), GAP_SCOPE_STRETCH_ONLY) is False

    def test_stretch_scope_post_holiday(self):
        """STRETCH_ONLY: Day after Independence Day (Jul 4 2025 = Fri) is
        the following Monday (Jul 7) — should be a stretch gap day."""
        from open_prep.run_open_prep import _is_gap_day, GAP_SCOPE_STRETCH_ONLY

        # After Jul 4 (Friday holiday) + weekend → Monday Jul 7 is stretch
        assert _is_gap_day(date(2025, 7, 7), GAP_SCOPE_STRETCH_ONLY) is True

    def test_holiday_set_contains_independence_day(self):
        """Verify holiday set includes Independence Day for 2025."""
        from open_prep.run_open_prep import _us_equity_market_holidays

        holidays = _us_equity_market_holidays(2025)
        assert date(2025, 7, 4) in holidays

    def test_holiday_set_contains_christmas(self):
        """Verify holiday set includes Christmas for 2025."""
        from open_prep.run_open_prep import _us_equity_market_holidays

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

        quotes, atr_map, mom_map, vwap_map, errors = _fetch_quotes_with_atr(
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

    def test_invalid_cutoff_does_not_crash(self):
        """Arrange: invalid cutoff format. Assert: returns unfiltered
        events instead of SystemExit."""
        from open_prep.run_open_prep import _fetch_todays_events

        mock_client = MagicMock()
        mock_client.get_macro_calendar.return_value = [
            {"event": "test", "date": "2025-06-16", "country": "US"},
        ]

        # Invalid cutoff should not crash
        result = _fetch_todays_events(
            client=mock_client,
            today=date(2025, 6, 16),
            end_date=date(2025, 6, 19),
            pre_open_only=True,
            pre_open_cutoff_utc="INVALID",
        )
        # Should return results (possibly unfiltered) rather than crash
        todays, all_events = result
        assert isinstance(todays, list)
        assert isinstance(all_events, list)


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
        within 14 iterations (safety bound)."""
        from open_prep.run_open_prep import _prev_trading_day

        # Patch _is_us_equity_trading_day to always return False
        with patch(
            "open_prep.run_open_prep._is_us_equity_trading_day",
            return_value=False,
        ):
            # Should not hang — safety bound returns d-1
            result = _prev_trading_day(date(2025, 6, 16))
            assert result == date(2025, 6, 15)


# ═══════════════════════════════════════════════════════════════════
# 7) Bare float() safety in realtime_signals._detect_signal
# ═══════════════════════════════════════════════════════════════════

class TestRealtimeSignalFloatSafety:
    """_detect_signal must not crash on non-numeric quote fields."""

    def test_non_numeric_price_returns_none(self):
        """Arrange: quote with price='N/A'. Assert: returns None, no crash."""
        from open_prep.realtime_signals import RealtimeEngine

        engine = RealtimeEngine.__new__(RealtimeEngine)
        engine._last_prices = {}

        signal = engine._detect_signal(
            "TEST",
            {"price": "N/A", "previousClose": 24.0, "volume": 100},
            {"avg_volume": 50000},
        )
        assert signal is None  # price=0 → early return

    def test_none_values_return_none(self):
        """Arrange: quote with all None values. Assert: returns None."""
        from open_prep.realtime_signals import RealtimeEngine

        engine = RealtimeEngine.__new__(RealtimeEngine)
        engine._last_prices = {}

        signal = engine._detect_signal(
            "TEST",
            {"price": None, "previousClose": None, "volume": None},
            {},
        )
        assert signal is None

    def test_valid_quote_produces_signal(self):
        """Arrange: quote with strong breakout. Assert: signal produced."""
        from open_prep.realtime_signals import RealtimeEngine

        engine = RealtimeEngine.__new__(RealtimeEngine)
        engine._last_prices = {}

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
        engine._client_disabled_reason = "API key missing"
        engine._active_signals = []
        engine._watchlist = []
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
    """_fetch_insider_trading must not crash on non-numeric
    securitiesTransacted or price (P-3 fix)."""

    def test_non_numeric_securities_transacted(self):
        """Arrange: securitiesTransacted='N/A'. Assert: no crash."""
        from open_prep.run_open_prep import _fetch_insider_trading

        mock_client = MagicMock()
        mock_client.get_insider_trading_latest.return_value = [
            {
                "symbol": "TEST",
                "transactionType": "P-Purchase",
                "securitiesTransacted": "N/A",
                "price": 50.0,
            },
        ]

        result = _fetch_insider_trading(
            client=mock_client, symbols=["TEST"]
        )
        assert "TEST" in result
        assert result["TEST"]["insider_total_bought_value"] == 0.0

    def test_none_price(self):
        """Arrange: price=None. Assert: no crash, value=0."""
        from open_prep.run_open_prep import _fetch_insider_trading

        mock_client = MagicMock()
        mock_client.get_insider_trading_latest.return_value = [
            {
                "symbol": "FOO",
                "transactionType": "P-Purchase",
                "securitiesTransacted": 1000,
                "price": None,
            },
        ]

        result = _fetch_insider_trading(
            client=mock_client, symbols=["FOO"]
        )
        assert "FOO" in result
        assert result["FOO"]["insider_total_bought_value"] == 0.0


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
        from open_prep import alerts
        import time

        alerts._last_sent.clear()
        now = time.time()
        # Add 600 stale entries (older than 600s)
        for i in range(600):
            alerts._last_sent[f"SYM{i}"] = now - 700

        alerts._prune_stale_entries(throttle_seconds=600)
        assert len(alerts._last_sent) == 0

    def test_prune_keeps_fresh(self):
        """Arrange: 600 entries, half fresh. Assert: only stale removed."""
        from open_prep import alerts
        import time

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
