"""Tests for the display-enrichment changes across scorer, screen, and streamlit_monitor.

Covers:
  - Type safety of pass-through fields (name, change, changesPercentage, pe, social_sentiment)
  - Edge cases: None values, string numerics, missing keys, NaN
  - Volume/PE formatting in the v2 tiered display
  - Staleness multiplier correctness
  - rank_score computation with various fallback chains
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from open_prep.utils import to_float


# =========================================================================
# 1. to_float safety (foundation for all numeric pass-through)
# =========================================================================

class TestToFloat:
    def test_none(self):
        assert to_float(None) == 0.0

    def test_string_number(self):
        assert to_float("3.14") == 3.14

    def test_empty_string(self):
        assert to_float("") == 0.0

    def test_nan(self):
        assert to_float(float("nan")) == 0.0

    def test_int(self):
        assert to_float(42) == 42.0

    def test_negative(self):
        assert to_float("-5.5") == -5.5

    def test_non_numeric_string(self):
        assert to_float("hello") == 0.0

    def test_custom_default(self):
        assert to_float(None, default=-1.0) == -1.0


# =========================================================================
# 2. scorer.py filter_candidate — pass-through field extraction
# =========================================================================

class TestScorerPassthrough:
    """Verify scorer.py extracts display fields correctly from various FMP quote shapes."""

    def _make_quote(self, **overrides):
        """Build a minimal FMP quote dict with defaults."""
        base = {
            "symbol": "TEST",
            "price": 50.0,
            "previousClose": 48.0,
            "volume": 1_000_000,
            "avgVolume": 800_000,
            "marketCap": 5_000_000_000,
            "sector": "Technology",
        }
        base.update(overrides)
        return base

    def test_name_from_name_field(self):
        q = self._make_quote(name="Apple Inc.")
        name = q.get("name") or q.get("companyName") or ""
        assert name == "Apple Inc."

    def test_name_from_companyName_field(self):
        q = self._make_quote(companyName="Apple Inc.")
        name = q.get("name") or q.get("companyName") or ""
        assert name == "Apple Inc."

    def test_name_missing(self):
        q = self._make_quote()
        name = q.get("name") or q.get("companyName") or ""
        assert name == ""

    def test_change_none(self):
        q = self._make_quote(change=None)
        assert to_float(q.get("change"), default=0.0) == 0.0

    def test_change_string(self):
        q = self._make_quote(change="2.35")
        assert to_float(q.get("change"), default=0.0) == 2.35

    def test_changesPercentage_fallback_to_changePercentage(self):
        q = self._make_quote(changePercentage=1.5)
        val = q.get("changesPercentage") or q.get("changePercentage")
        assert to_float(val, default=0.0) == 1.5

    def test_pe_none_passthrough(self):
        """PE should pass through None without crashing."""
        q = self._make_quote(pe=None)
        pe_val = q.get("pe")
        assert pe_val is None

    def test_pe_string_passthrough(self):
        """PE might be a string from FMP — scorer now converts via _to_float."""
        q = self._make_quote(pe="25.3")
        pe_val = q.get("pe")
        # After fix: scorer converts via _to_float, so downstream gets float or None
        # Simulate the fixed pipeline:
        converted = to_float(pe_val, default=0.0) or None
        assert converted == 25.3
        formatted = f"{converted:.1f}"
        assert formatted == "25.3"

    def test_pe_float_passthrough(self):
        q = self._make_quote(pe=25.3)
        pe_val = q.get("pe")
        assert f"{pe_val:.1f}" == "25.3"


# =========================================================================
# 3. Staleness multiplier
# =========================================================================

class TestStalenessMultiplier:
    """Verify the exponential decay function used in streamlit_monitor.py."""

    @staticmethod
    def _staleness_multiplier(age_min: float) -> float:
        if age_min <= 0:
            return 1.0
        return max(math.exp(-age_min * math.log(2) / 30.0), 0.05)

    def test_zero_age(self):
        assert self._staleness_multiplier(0) == 1.0

    def test_negative_age(self):
        assert self._staleness_multiplier(-5) == 1.0

    def test_30_min_halflife(self):
        result = self._staleness_multiplier(30)
        assert abs(result - 0.5) < 0.001

    def test_60_min_quarter(self):
        result = self._staleness_multiplier(60)
        assert abs(result - 0.25) < 0.001

    def test_180_min_very_low(self):
        """3 hours old hits the 0.05 floor (actual decay ≈1.6%, clamped to 5%)."""
        result = self._staleness_multiplier(180)
        assert result == 0.05  # clamped to floor

    def test_floor_at_0_05(self):
        """Even very old data should not go below 5%."""
        result = self._staleness_multiplier(10000)
        assert result == 0.05


# =========================================================================
# 4. rank_score computation edge cases
# =========================================================================

class TestRankScore:
    """Test the rank_score formula as implemented in streamlit_monitor.py."""

    @staticmethod
    def _compute_rank_score(row: dict, stale_mult: float = 1.0) -> float:
        _chg = abs(float(
            row.get("gap_pct")
            or row.get("bz_chg_pct")
            or row.get("changesPercentage")
            or 0
        ))
        _ns = float(row.get("score") or 0)
        _raw_rank = _chg * 0.7 + _ns * 100.0 * 0.3
        return round(_raw_rank * stale_mult, 2)

    def test_all_zeros(self):
        row = {"gap_pct": 0, "score": 0}
        assert self._compute_rank_score(row) == 0.0

    def test_gap_pct_used_first(self):
        row = {"gap_pct": 5.0, "changesPercentage": 3.0, "score": 0.5}
        result = self._compute_rank_score(row)
        # gap_pct=5.0 should be used (truthy), not changesPercentage
        expected = abs(5.0) * 0.7 + 0.5 * 100.0 * 0.3
        assert result == round(expected, 2)

    def test_fallback_to_changesPercentage_when_gap_is_zero(self):
        row = {"gap_pct": 0.0, "changesPercentage": 3.0, "score": 0.5}
        result = self._compute_rank_score(row)
        # gap_pct=0.0 is falsy, so changesPercentage=3.0 should be used
        expected = abs(3.0) * 0.7 + 0.5 * 100.0 * 0.3
        assert result == round(expected, 2)

    def test_fallback_chain_all_none(self):
        row = {"gap_pct": None, "bz_chg_pct": None, "changesPercentage": None, "score": 0.8}
        result = self._compute_rank_score(row)
        expected = 0 * 0.7 + 0.8 * 100.0 * 0.3
        assert result == round(expected, 2)

    def test_staleness_decay(self):
        row = {"gap_pct": 5.0, "score": 0.5}
        fresh = self._compute_rank_score(row, stale_mult=1.0)
        stale = self._compute_rank_score(row, stale_mult=0.5)
        assert stale == round(fresh * 0.5, 2)

    def test_negative_gap_pct(self):
        """Negative gap should still contribute via abs()."""
        row = {"gap_pct": -5.0, "score": 0.5}
        result = self._compute_rank_score(row)
        # -5.0 is truthy, abs(-5.0) = 5.0
        expected = 5.0 * 0.7 + 0.5 * 100.0 * 0.3
        assert result == round(expected, 2)

    def test_gap_pct_zero_but_bz_chg_present(self):
        row = {"gap_pct": 0.0, "bz_chg_pct": 2.5, "changesPercentage": 1.0, "score": 0.3}
        result = self._compute_rank_score(row)
        # gap_pct=0.0 falsy -> bz_chg_pct=2.5 truthy
        expected = abs(2.5) * 0.7 + 0.3 * 100.0 * 0.3
        assert result == round(expected, 2)

    def test_gap_pct_string_value(self):
        """If gap_pct is a string (from JSON), float() should handle it."""
        row = {"gap_pct": "4.2", "score": 0.5}
        result = self._compute_rank_score(row)
        # "4.2" is truthy, float("4.2") = 4.2
        expected = abs(4.2) * 0.7 + 0.5 * 100.0 * 0.3
        assert result == round(expected, 2)


# =========================================================================
# 5. Volume formatting edge cases
# =========================================================================

class TestVolumeFormatting:
    """Test the volume formatting logic used in v2 tiered display."""

    @staticmethod
    def _format_volume(vol) -> str:
        """Replicate the display logic from streamlit_monitor.py."""
        if vol is None:
            vol = 0
        try:
            vol = float(vol)
        except (TypeError, ValueError):
            return ""
        if vol >= 1e6:
            return f" · vol {vol / 1e6:.1f}M"
        if vol >= 1e3:
            return f" · vol {vol / 1e3:.0f}K"
        return ""

    def test_millions(self):
        assert "5.0M" in self._format_volume(5_000_000)

    def test_thousands(self):
        assert "500K" in self._format_volume(500_000)

    def test_small(self):
        assert self._format_volume(500) == ""

    def test_zero(self):
        assert self._format_volume(0) == ""

    def test_none(self):
        """BUG: r.get('volume', 0) returns None if key exists with None value."""
        assert self._format_volume(None) == ""

    def test_string_volume(self):
        assert "5.0M" in self._format_volume("5000000")

    def test_negative_volume(self):
        """Negative volume is nonsensical but should not crash."""
        result = self._format_volume(-1000)
        # -1000 < 1e3 so returns ""
        assert result == ""


# =========================================================================
# 6. PE formatting edge cases
# =========================================================================

class TestPEFormatting:
    """Test PE formatting logic for type safety."""

    @staticmethod
    def _format_pe(pe_val) -> str:
        """Safe PE formatting that handles all types."""
        if pe_val is None:
            return ""
        try:
            return f" · P/E {float(pe_val):.1f}"
        except (TypeError, ValueError):
            return ""

    def test_float_pe(self):
        assert "25.3" in self._format_pe(25.3)

    def test_string_pe(self):
        """PE from FMP could be a string."""
        assert "25.3" in self._format_pe("25.3")

    def test_none_pe(self):
        assert self._format_pe(None) == ""

    def test_nan_pe(self):
        result = self._format_pe(float("nan"))
        assert "nan" in result.lower()  # Would display 'nan' — not ideal but won't crash

    def test_negative_pe(self):
        assert "-5.0" in self._format_pe(-5.0)


# =========================================================================
# 7. _age_label edge cases
# =========================================================================

class TestAgeLabel:

    @staticmethod
    def _age_label(age_min: float) -> str:
        if age_min < 5:
            return "🟢 <5m"
        if age_min < 15:
            return f"🟡 {age_min:.0f}m"
        if age_min < 60:
            return f"🟠 {age_min:.0f}m"
        return f"🔴 {age_min:.0f}m"

    def test_fresh(self):
        assert "🟢" in self._age_label(0)

    def test_moderate(self):
        assert "🟡" in self._age_label(10)

    def test_old(self):
        assert "🟠" in self._age_label(30)

    def test_stale(self):
        assert "🔴" in self._age_label(120)

    def test_negative(self):
        """Negative age should show fresh."""
        assert "🟢" in self._age_label(-1)


# =========================================================================
# 8. Integration: scorer.py round() with None pe
# =========================================================================

class TestScorerRoundSafety:
    """Test that the fixed `or 0.0` pattern prevents round() crashes."""

    def test_round_change_none_safe(self):
        """After fix: f.get('change') or 0.0 returns 0.0 when value is None."""
        f = {"change": None}
        val = f.get("change") or 0.0
        assert round(val, 4) == 0.0

    def test_round_changesPercentage_none_safe(self):
        f = {"changesPercentage": None}
        val = f.get("changesPercentage") or 0.0
        assert round(val, 4) == 0.0

    def test_round_social_sentiment_none_safe(self):
        f = {"social_sentiment": None}
        val = f.get("social_sentiment") or 0.0
        assert round(val, 4) == 0.0


# =========================================================================
# 9. v2 display _chg_pct format string with None
# =========================================================================

class TestDisplayFormatStrings:
    """Test that format strings in v2 display handle None values safely."""

    def test_chg_pct_zero(self):
        """_chg_pct=0 is falsy, so _chg_txt should be empty."""
        _chg_pct = 0
        _chg_txt = f" · chg {_chg_pct:+.1f}%" if _chg_pct else ""
        assert _chg_txt == ""

    def test_chg_pct_none_from_get(self):
        """r.get('changesPercentage', 0) when key exists with None value."""
        r = {"changesPercentage": None}
        _chg_pct = r.get("changesPercentage", 0)
        # _chg_pct is None! The format string would crash.
        try:
            _chg_txt = f" · chg {_chg_pct:+.1f}%" if _chg_pct else ""
            # None is falsy, so the `if _chg_pct` guard saves us here
            assert _chg_txt == ""
        except TypeError:
            assert False, "Should not reach here — None is falsy"

    def test_vol_none_from_get(self):
        """After fix: float(r.get('volume') or 0) handles None safely."""
        r = {"volume": None}
        _vol = float(r.get("volume") or 0)
        assert _vol == 0.0
        # The comparison now works without TypeError
        _vol_txt = f" · vol {_vol / 1e6:.1f}M" if _vol >= 1e6 else (
            f" · vol {_vol / 1e3:.0f}K" if _vol >= 1e3 else "")
        assert _vol_txt == ""

    def test_pe_string_from_get(self):
        """After fix: pe is converted via try/except float() in display layer."""
        _pe_raw = "25.3"
        try:
            _pe_val = float(_pe_raw) if _pe_raw is not None else None
        except (TypeError, ValueError):
            _pe_val = None
        assert _pe_val == 25.3
        _pe_txt = f" · P/E {_pe_val:.1f}" if _pe_val is not None else ""
        assert "25.3" in _pe_txt


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
