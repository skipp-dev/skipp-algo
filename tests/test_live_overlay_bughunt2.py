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
            b: dict[str, Any] = {"close": 100.0, "low": 90.0 + i}
            if i != 5:
                b["high"] = 110.0 + i
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
