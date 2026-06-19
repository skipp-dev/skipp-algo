"""
Regression tests — Round 2 bug-hunt.

Confirmed bugs found and fixed:

  B19 – compute_ats_fields: same B15 volume-alignment bug.
        volumes[-1] was one bar stale when bars[-1] had no volume field.
        Fix: anchor last_vol to bars[-1].get("volume"). If None → return None.

  B20 – compute_ats_fields: cross-bar price_delta.
        closes/opens filtered independently; when bars[-1] was missing open
        or close, closes[-1] / opens[-1] came from different bars.
        Fix: anchor both last_open and last_close to bars[-1]; fall back to
        "neutral" (not cross-bar) when either is absent.

  B22 – compute_squeeze_on: cross-bar True Range.
        highs, lows, closes filtered independently. When any bar in the
        window was missing a field, the period-slice started at different
        bars, so TR[i] = highs[i] - lows[i+1] (cross-bar).
        Fix: build aligned (close, high, low) triples — only bars with
        all three fields present — so TR is always same-bar.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _compute():
    import services.live_overlay_daemon.compute as m
    importlib.reload(m)
    return m


# ============================================================
# B19 – compute_ats_fields: last-bar volume misalignment
# ============================================================

class TestAtsFieldsVolumeAlignment:
    """B19: ats_zscore/ats_state must be None when bars[-1] has no volume."""

    def _bars_last_no_volume(self) -> list[dict[str, Any]]:
        return [
            {"open": 100.0, "close": 100.5, "high": 101.0, "low": 99.5, "volume": 100},
            {"open": 101.0, "close": 101.5, "high": 102.0, "low": 100.5, "volume": 200},
            {"open": 102.0, "close": 102.5, "high": 103.0, "low": 101.5, "volume": 300},
            {"open": 103.0, "close": 103.5, "high": 104.0, "low": 102.5, "volume": 400},
            {"open": 104.0, "close": 104.5, "high": 105.0, "low": 103.5, "volume": 500},
            # bars[-1]: no volume field
            {"open": 105.0, "close": 106.0, "high": 107.0, "low": 104.0},
        ]

    def test_ats_zscore_is_none_when_last_bar_has_no_volume(self):
        compute = _compute()
        result = compute.compute_ats_fields(self._bars_last_no_volume())
        assert result["ats_zscore"] is None, (
            f"B19: ats_zscore={result['ats_zscore']!r} was computed even though "
            "bars[-1] has no volume — zscore is one bar stale"
        )

    def test_ats_state_is_none_when_last_bar_has_no_volume(self):
        compute = _compute()
        result = compute.compute_ats_fields(self._bars_last_no_volume())
        assert result["ats_state"] is None, (
            f"B19: ats_state={result['ats_state']!r} was produced even though "
            "bars[-1] has no volume"
        )

    def test_ats_fields_computed_when_all_bars_have_volume(self):
        """Regression guard: normal case must still work after the fix."""
        compute = _compute()
        bars = [
            {"open": 100.0, "close": 100.5, "high": 101.0, "low": 99.5, "volume": 100},
            {"open": 101.0, "close": 101.5, "high": 102.0, "low": 100.5, "volume": 200},
            {"open": 102.0, "close": 102.5, "high": 103.0, "low": 101.5, "volume": 300},
            {"open": 103.0, "close": 103.5, "high": 104.0, "low": 102.5, "volume": 400},
            # Last bar: high volume + bullish close > open → accumulation
            {"open": 104.0, "close": 106.0, "high": 107.0, "low": 103.5, "volume": 2000},
        ]
        result = compute.compute_ats_fields(bars)
        assert result["ats_zscore"] is not None
        assert result["ats_zscore"] > 2.0, f"Zscore too low: {result['ats_zscore']}"
        assert result["ats_state"] == "accumulation"

    def test_ats_returns_none_when_fewer_than_5_volumes(self):
        """Guard the minimum-bars threshold (4 prior + 1 current)."""
        compute = _compute()
        bars = [
            {"open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0, "volume": 100},
            {"open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0, "volume": 200},
            {"open": 102.0, "close": 103.0, "high": 104.0, "low": 101.0, "volume": 300},
            # Only 3 bars with volume + 1 bar without → 3 prior vols < 4 required
            {"open": 103.0, "close": 104.0, "high": 105.0, "low": 102.0},
        ]
        result = compute.compute_ats_fields(bars)
        assert result["ats_zscore"] is None
        assert result["ats_state"] is None

    def test_ats_empty_bars_returns_none(self):
        compute = _compute()
        result = compute.compute_ats_fields([])
        assert result == {"ats_state": None, "ats_zscore": None}


# ============================================================
# B20 – compute_ats_fields: cross-bar price_delta
# ============================================================

class TestAtsFieldsPriceDeltaAlignment:
    """B20: price_delta must use bars[-1]'s own close and open."""

    def test_state_is_neutral_when_last_bar_has_no_open(self):
        compute = _compute()
        bars = [
            {"open": 90.0, "close": 91.0, "high": 92.0, "low": 89.0, "volume": 100},
            {"open": 91.0, "close": 92.0, "high": 93.0, "low": 90.0, "volume": 200},
            {"open": 92.0, "close": 93.0, "high": 94.0, "low": 91.0, "volume": 300},
            {"open": 93.0, "close": 94.0, "high": 95.0, "low": 92.0, "volume": 400},
            {"open": 94.0, "close": 120.0, "high": 121.0, "low": 93.0, "volume": 500},
            # bars[-1]: no open — pre-fix: used opens[-1]=94 (bars[-2].open)
            {"close": 80.0, "high": 121.0, "low": 79.0, "volume": 2000},
        ]
        result = compute.compute_ats_fields(bars)
        assert result["ats_state"] in (None, "neutral"), (
            f"B20: ats_state={result['ats_state']!r} must be neutral/None when "
            "bars[-1] has no open — not a cross-bar 'distribution'"
        )

    def test_state_is_neutral_when_last_bar_has_no_close(self):
        compute = _compute()
        bars = [
            {"open": 90.0, "close": 91.0, "high": 92.0, "low": 89.0, "volume": 100},
            {"open": 91.0, "close": 92.0, "high": 93.0, "low": 90.0, "volume": 200},
            {"open": 92.0, "close": 93.0, "high": 94.0, "low": 91.0, "volume": 300},
            {"open": 93.0, "close": 94.0, "high": 95.0, "low": 92.0, "volume": 400},
            {"open": 94.0, "close": 50.0, "high": 95.0, "low": 49.0, "volume": 500},
            # bars[-1]: no close — pre-fix: used closes[-1]=50 (bars[-2].close)
            {"open": 150.0, "high": 155.0, "low": 149.0, "volume": 2000},
        ]
        result = compute.compute_ats_fields(bars)
        assert result["ats_state"] in (None, "neutral"), (
            f"B20: ats_state={result['ats_state']!r} must be neutral/None when "
            "bars[-1] has no close"
        )

    def test_state_uses_last_bar_own_open_and_close(self):
        """Positive case: bars[-1] has both open and close → correct direction."""
        compute = _compute()
        bars = [
            {"open": 90.0, "close": 91.0, "high": 92.0, "low": 89.0, "volume": 100},
            {"open": 91.0, "close": 92.0, "high": 93.0, "low": 90.0, "volume": 200},
            {"open": 92.0, "close": 93.0, "high": 94.0, "low": 91.0, "volume": 300},
            {"open": 93.0, "close": 94.0, "high": 95.0, "low": 92.0, "volume": 400},
            # Last bar: bullish, very high volume
            {"open": 94.0, "close": 110.0, "high": 111.0, "low": 93.5, "volume": 5000},
        ]
        result = compute.compute_ats_fields(bars)
        assert result["ats_state"] == "accumulation", (
            f"Expected 'accumulation' (bullish + high z-score), got {result['ats_state']!r}"
        )


# ============================================================
# B22 – compute_squeeze_on: cross-bar TR from independent filtering
# ============================================================

class TestSqueezeAlignedWindow:
    """B22: TR must always use high and low from the same bar."""

    def test_squeeze_on_rejects_negative_true_range_bar(self):
        """B10: malformed bar with high<low must not emit squeeze=True."""
        compute = _compute()
        bars = [
            {
                "open": 100.0 + i * 0.1,
                "close": 100.0 + i * 0.1,
                "high": 101.0 + i * 0.1,
                "low": 99.0 + i * 0.1,
                "volume": 100,
            }
            for i in range(19)
        ]
        bars.append(
            {
                "open": 100.0,
                "close": 100.0,
                "high": 99.0,
                "low": 101.0,
                "volume": 100,
            }
        )

        result = compute.compute_squeeze_on(bars, period=20)
        assert result is not True, (
            "B10: malformed bar with high<low must not create a squeeze signal"
        )

    def test_result_is_correct_when_bar_in_window_missing_high(self):
        """
        25 bars; bar[5] has no high. After fix, bar[5] is excluded from
        the aligned triples. The remaining 24 complete bars all have
        close=100 (std=0, BB_width=0) and high-low=20 (ATR=20, KC_width=40).
        0 < 40 → squeeze=True.

        Pre-fix: bar[4].high paired with bar[5].low → phantom TR=19,
        corrupting ATR and potentially flipping the squeeze signal.
        """
        compute = _compute()
        bars = []
        for i in range(25):
            b: dict[str, Any] = {"close": 100.0, "low": 90.0}
            if i != 5:
                b["high"] = 110.0
            bars.append(b)

        result = compute.compute_squeeze_on(bars, period=20)
        assert result is True, (
            f"B22: Expected squeeze=True (std=0, ATR=20, BB_width=0 < KC_width=40). "
            f"Got: {result!r}"
        )

    def test_result_when_missing_high_in_oldest_bar(self):
        """Missing field in oldest bar (outside window) must not affect result."""
        compute = _compute()
        bars = []
        for i in range(25):
            b: dict[str, Any] = {"close": 100.0, "low": 90.0, "high": 110.0}
            if i == 0:
                del b["high"]  # Only bar[0] is missing high — outside [-20:] window
            bars.append(b)

        result = compute.compute_squeeze_on(bars, period=20)
        # bar[0] excluded → 24 complete bars. triples[-20:] = bars[4:25] (all complete).
        # close=100 (std=0), high-low=20 (ATR=20). 0 < 40 → True.
        assert result is True

    def test_insufficient_complete_bars_returns_none(self):
        """If fewer than `period` bars have all three fields → None."""
        compute = _compute()
        # 25 bars but 10 are missing `high` → only 15 complete bars < period=20
        bars = []
        for i in range(25):
            b: dict[str, Any] = {"close": 100.0, "low": 90.0}
            if i % 2 == 0:  # 13 bars have high (indices 0,2,4,...,24)
                b["high"] = 110.0
            bars.append(b)

        result = compute.compute_squeeze_on(bars, period=20)
        assert result is None, (
            f"Expected None (only 13 complete bars < period=20), got {result!r}"
        )

    def test_all_complete_bars_non_squeeze(self):
        """Normal case: wide BB > KC → squeeze=False."""
        compute = _compute()
        # high std_c (wide BB) with small ATR → not in squeeze
        import math
        closes = [100.0 + (10.0 * math.sin(i)) for i in range(20)]
        bars = [
            {"close": c, "high": c + 0.5, "low": c - 0.5}
            for c in closes
        ]
        # ATR ≈ 1.0 per bar → KC_width=2.0. BB_width=4*std_c >> 2.0.
        result = compute.compute_squeeze_on(bars, period=20)
        assert result is False, (
            f"Expected squeeze=False (wide BB, narrow KC). Got: {result!r}"
        )

    def test_squeeze_result_is_bool_not_int(self):
        """compute_squeeze_on must return a Python bool, not an int."""
        compute = _compute()
        bars = [
            {"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(20)
        ]
        result = compute.compute_squeeze_on(bars, period=20)
        assert isinstance(result, bool) or result is None, (
            f"Expected bool or None, got {type(result)!r}"
        )


# ============================================================
# B23 – compute_flow_fields / compute_ats_fields: string-volume TypeError
# ============================================================

class TestStringVolumeCoercion:
    """B23: volume fields arriving as numeric strings must not crash compute functions.

    Root cause: b.get("volume") is not None passes string values through the filter,
    but sum(["100", "110", ...]) raises TypeError because int + str is not supported.
    Fix: _coerce_volume() converts numeric strings to float and returns None for
    non-numeric values so callers can skip the bar gracefully.
    """

    def test_all_string_volumes_no_crash(self):
        """compute_flow_fields must not raise when all volumes are numeric strings."""
        compute = _compute()
        bars = [
            {"open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
             "close": 100.5 + i, "volume": str(100 + i * 10)}
            for i in range(5)
        ]
        result = compute.compute_flow_fields(bars)
        assert isinstance(result, dict)
        # Numeric strings are valid volumes: ratio should be computed.
        assert result["flow_rel_vol"] is not None

    def test_ats_fields_string_volumes_no_crash(self):
        """compute_ats_fields must not raise when all volumes are numeric strings."""
        compute = _compute()
        bars = [
            {"open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
             "close": 100.5 + i, "volume": str(100 + i * 10)}
            for i in range(5)
        ]
        result = compute.compute_ats_fields(bars)
        assert isinstance(result, dict)

    def test_garbage_volume_treated_as_missing(self):
        """Non-numeric volume strings (e.g. 'N/A') must yield None fields, not crash."""
        compute = _compute()
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.5, "volume": "N/A"}
            for _ in range(5)
        ]
        result = compute.compute_flow_fields(bars)
        assert result["flow_rel_vol"] is None

    def test_mixed_none_int_string_volume(self):
        """Mixed volume types in a bar list: None/int/string must not crash."""
        compute = _compute()
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": None},
            {"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 200},
            {"open": 102.0, "high": 103.0, "low": 101.0, "close": 102.5, "volume": "300"},
            {"open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5, "volume": 400},
            {"open": 104.0, "high": 105.0, "low": 103.0, "close": 104.5, "volume": 500},
        ]
        # Must not crash
        r_flow = compute.compute_flow_fields(bars)
        r_ats = compute.compute_ats_fields(bars)
        assert isinstance(r_flow, dict)
        assert isinstance(r_ats, dict)

    def test_last_bar_string_volume_treated_as_valid(self):
        """A numeric-string volume on bars[-1] is coerced and used, not skipped."""
        compute = _compute()
        bars = [
            {"open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
             "close": 100.5 + i,
             "volume": "500" if i == 4 else (100 + i * 10)}
            for i in range(5)
        ]
        result = compute.compute_flow_fields(bars)
        # last_vol=500 (coerced), prior_vols=[100,110,120,130], avg=115
        # rel_vol = 500/115 ≈ 4.3478
        assert result["flow_rel_vol"] is not None
        assert result["flow_rel_vol"] > 1.0

    def test_nan_string_volume_treated_as_missing(self):
        """Non-finite numeric string volume ('NaN') must be rejected as missing."""
        compute = _compute()
        bars = [
            {"open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
             "close": 100.5 + i,
             "volume": "NaN" if i == 4 else (100 + i * 10)}
            for i in range(5)
        ]

        flow = compute.compute_flow_fields(bars)
        ats = compute.compute_ats_fields(bars)

        assert flow["flow_rel_vol"] is None
        assert ats["ats_zscore"] is None
        assert ats["ats_state"] is None

    def test_negative_last_volume_treated_as_missing(self):
        """Negative last-bar volume must be rejected and not produce negative rel-vol."""
        compute = _compute()
        bars = [
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 100},
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 110},
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 120},
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 130},
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": -500},
        ]

        flow = compute.compute_flow_fields(bars)
        ats = compute.compute_ats_fields(bars)

        assert flow["flow_rel_vol"] is None
        assert ats["ats_zscore"] is None
        assert ats["ats_state"] is None

    def test_negative_prior_volumes_are_filtered(self):
        """Negative prior volumes must be ignored in avg/zscore baselines."""
        compute = _compute()
        bars = [
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": -100},
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 110},
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 120},
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 130},
            {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 500},
        ]

        flow = compute.compute_flow_fields(bars)
        # prior valid vols = [110,120,130] => avg=120 => rel_vol=4.1667
        assert flow["flow_rel_vol"] == 4.1667


class TestNewsScoreFiniteCoercion:
    """Non-finite news scores must be treated as invalid/missing, not propagated."""

    def test_nan_sentiment_score_is_treated_as_missing(self):
        compute = _compute()
        compute._load_news_snapshot = lambda: {
            "stories": [{"tickers": ["AAPL"], "sentiment_score": float("nan")}]
        }

        fields = compute._get_news_fields("AAPL")

        assert fields["news_strength"] is None
        assert fields["news_bias"] is None

    def test_inf_news_score_is_treated_as_missing(self):
        compute = _compute()
        compute._load_news_snapshot = lambda: {
            "stories": [{"tickers": ["AAPL"], "news_score": "inf"}]
        }

        fields = compute._get_news_fields("AAPL")

        assert fields["news_strength"] is None
        assert fields["news_bias"] is None

    def test_global_news_fields_reject_non_finite_scores(self):
        compute = _compute()
        compute._load_news_snapshot = lambda: {
            "stories": [
                {"sentiment_score": float("nan")},
                {"news_score": "-inf"},
            ]
        }

        fields = compute._get_global_news_fields()

        assert fields["tone"] == "NEUTRAL"
        assert fields["global_heat"] is None

    def test_mixed_finite_and_non_finite_scores_keep_only_finite_samples(self):
        compute = _compute()
        compute._load_news_snapshot = lambda: {
            "stories": [
                {"tickers": ["AAPL"], "sentiment_score": "nan"},
                {"tickers": ["AAPL"], "news_score": 0.6},
                {"tickers": ["AAPL"], "news_score": "-inf"},
            ]
        }

        sym = compute._get_news_fields("AAPL")
        glob = compute._get_global_news_fields()

        assert sym["news_strength"] == 0.6
        assert sym["news_bias"] == "BULLISH"
        assert glob["tone"] == "BULLISH"
        assert glob["global_heat"] == 0.6

    def test_inf_string_volume_treated_as_missing(self):
        """Non-finite numeric string volume ('inf') must be rejected as missing."""
        compute = _compute()
        bars = [
            {"open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
             "close": 100.5 + i,
             "volume": "inf" if i == 4 else (100 + i * 10)}
            for i in range(5)
        ]

        flow = compute.compute_flow_fields(bars)
        ats = compute.compute_ats_fields(bars)

        assert flow["flow_rel_vol"] is None
        assert ats["ats_zscore"] is None
        assert ats["ats_state"] is None

    def test_invalid_sentiment_falls_back_to_valid_news_score(self):
        """Regression: malformed sentiment_score must not mask valid news_score."""
        compute = _compute()
        compute._load_news_snapshot = lambda: {
            "stories": [
                {
                    "tickers": ["AAPL"],
                    "sentiment_score": "nan",
                    "news_score": 0.9,
                }
            ]
        }

        sym = compute._get_news_fields("AAPL")
        glob = compute._get_global_news_fields()

        assert sym["news_strength"] == 0.9
        assert sym["news_bias"] == "BULLISH"
        assert glob["global_heat"] == 0.9
        assert glob["tone"] == "BULLISH"


class TestMalformedOhlcValues:
    """Malformed OHLC values should degrade gracefully, not raise TypeError."""

    def test_compute_flow_fields_ignores_non_numeric_open(self):
        compute = _compute()
        bars = [
            {
                "open": "bad",
                "high": 2.0,
                "low": 0.8,
                "close": 1.2,
                "volume": 100,
            }
        ]

        result = compute.compute_flow_fields(bars)
        assert result["flow_delta_proxy_pct"] is None
        assert result["flow_rel_vol"] is None

    def test_compute_ats_fields_non_numeric_last_open_returns_neutral_state(self):
        compute = _compute()
        bars = [
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 100},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 120},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 130},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 140},
            {"open": "bad", "close": 2.0, "high": 2.1, "low": 1.9, "volume": 500},
        ]

        result = compute.compute_ats_fields(bars)
        assert result["ats_state"] == "neutral"
        assert result["ats_zscore"] is not None

    def test_compute_squeeze_on_skips_non_numeric_ohlc(self):
        compute = _compute()
        bars = [
            {"close": "bad", "high": 101.0, "low": 99.0}
            for _ in range(20)
        ]

        result = compute.compute_squeeze_on(bars, period=20)
        assert result is None

    def test_compute_flow_fields_rejects_boolean_open_close(self):
        """Replay: bool OHLC values must not become synthetic 1.0/0.0 prices."""
        compute = _compute()
        bars = [{"open": True, "close": False, "high": 2.0, "low": 0.5, "volume": 100}]

        result = compute.compute_flow_fields(bars)

        assert result["flow_delta_proxy_pct"] is None

    def test_compute_ats_fields_rejects_boolean_open_close(self):
        """Replay: bool OHLC values must not produce fake bearish/distribution signals."""
        compute = _compute()
        bars = [
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 100},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 110},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 120},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 130},
            {"open": True, "close": False, "high": 1.2, "low": 0.9, "volume": 500},
        ]

        result = compute.compute_ats_fields(bars)

        assert result["ats_state"] == "neutral"
        assert result["ats_zscore"] is not None


class TestBoundaryThresholdAndOverlayPatch:
    """Boundary semantics and cache patch robustness regressions."""

    def test_ats_state_uses_inclusive_zscore_threshold(self):
        """zscore exactly 0.5 should classify as accumulation/distribution, not neutral."""
        compute = _compute()
        bars = [
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 100},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 110},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 120},
            {"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9, "volume": 130},
            {"open": 1.0, "close": 1.2, "high": 1.3, "low": 0.9, "volume": 121.90915243299638},
        ]

        result = compute.compute_ats_fields(bars)

        assert result["ats_zscore"] is not None
        assert result["ats_zscore"] >= 0.5
        assert result["ats_state"] == "accumulation"

    def test_patch_overlay_rejects_non_finite_updates(self):
        import services.live_overlay_daemon.cache as cache_mod

        cache_mod.set_overlay({"AAPL": {"vix_level": 20.0, "flow_rel_vol": 1.5}})

        cache_mod.patch_overlay(
            "AAPL",
            {"vix_level": float("inf"), "flow_rel_vol": float("nan")},
        )

        payload = cache_mod.get_overlay("AAPL")

        assert payload is not None
        assert payload["vix_level"] == 20.0
        assert payload["flow_rel_vol"] == 1.5

