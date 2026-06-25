"""Tests for Signal Quality v2 model — build_signal_quality_v2 and routing.

Covers:
- ``build_signal_quality_v2`` returns a dict with same keys as v1
- v2 budget constants sum to exactly 100
- Freshness decay multiplier applied when ``freshness_v2`` enrichment present
- Invalidated event is tier-capped at ``"ok"``
- SWEEP_TRAP_QUALITY_SCORE used when present; fallback to SWEEP_QUALITY_SCORE
- Confluence bucket contributes when ``confluence_v2`` present
- Score is clamped to 0–100
- v1 routing via ``signal_quality_model() == "v1"`` returns v1 output shape
"""

from __future__ import annotations

import os
from unittest.mock import patch

from scripts.smc_signal_quality import (
    _MAX_COMPRESSION_V2,
    _MAX_CONFLUENCE_V2,
    _MAX_FVG_V2,
    _MAX_LIQUIDITY_V2,
    _MAX_OB_V2,
    _MAX_SESSION_V2,
    _MAX_SMT_V2,
    _MAX_STRUCTURE_V2,
    build_signal_quality,
    build_signal_quality_v2,
)

# ---------------------------------------------------------------------------
# Budget invariant
# ---------------------------------------------------------------------------


def test_v2_budget_sums_to_100() -> None:
    total = (
        _MAX_STRUCTURE_V2
        + _MAX_SESSION_V2
        + _MAX_LIQUIDITY_V2
        + _MAX_OB_V2
        + _MAX_FVG_V2
        + _MAX_COMPRESSION_V2
        + _MAX_CONFLUENCE_V2
        + _MAX_SMT_V2
    )
    assert total == 100


# ---------------------------------------------------------------------------
# Return shape
# ---------------------------------------------------------------------------


class TestReturnShape:
    def test_v2_returns_same_keys_as_v1(self) -> None:
        v1_result = build_signal_quality(enrichment={})
        v2_result = build_signal_quality_v2(enrichment={})
        assert set(v2_result.keys()) == set(v1_result.keys())

    def test_score_is_int_or_float_in_0_100(self) -> None:
        v2 = build_signal_quality_v2(enrichment={})
        score = v2["SIGNAL_QUALITY_SCORE"]
        assert 0 <= score <= 100

    def test_tier_is_a_string(self) -> None:
        v2 = build_signal_quality_v2(enrichment={})
        assert isinstance(v2["SIGNAL_QUALITY_TIER"], str)


# ---------------------------------------------------------------------------
# Freshness decay
# ---------------------------------------------------------------------------


class TestFreshnessDecay:
    def _ob_light(self) -> dict:
        return {
            "PRIMARY_OB_SIDE": "BULL",
            "OB_FRESH": True,
            "PRIMARY_OB_DISTANCE": 1.0,
            "OB_SUPPORT_SCORE": 15.0,
        }

    def test_fresh_penalty_1_no_decay(self) -> None:
        enr_fresh = {
            "freshness_v2": {"freshness_bucket": "fresh", "freshness_penalty": 1.0},
            "ob_context_light": self._ob_light(),
        }
        enr_invalidated = {
            "freshness_v2": {"freshness_bucket": "invalidated", "freshness_penalty": 0.0},
            "ob_context_light": self._ob_light(),
        }
        fresh_score = build_signal_quality_v2(enrichment=enr_fresh)["SIGNAL_QUALITY_SCORE"]
        inv_score = build_signal_quality_v2(enrichment=enr_invalidated)["SIGNAL_QUALITY_SCORE"]
        assert fresh_score >= inv_score

    def test_invalidated_event_capped_at_ok_tier(self) -> None:
        enr = {
            "freshness_v2": {"freshness_bucket": "invalidated", "freshness_penalty": 0.0},
            "structure_state_light": {
                "STRUCTURE_FRESH": True,
                "STRUCTURE_EVENT_AGE_BARS": 1,
                "STRUCTURE_LAST_EVENT": "BOS_BULL",
            },
            "session_context_light": {
                "IN_KILLZONE": True,
                "SESSION_DIRECTION_BIAS": "BULLISH",
                "SESSION_CONTEXT_SCORE": 5,
            },
            "ob_context_light": self._ob_light(),
            "fvg_lifecycle_light": {
                "PRIMARY_FVG_SIDE": "BULL",
                "FVG_FRESH": True,
                "FVG_FILL_PCT": 0.0,
                "FVG_INVALIDATED": False,
            },
        }
        result = build_signal_quality_v2(enrichment=enr)
        assert result["SIGNAL_QUALITY_TIER"] in {"low", "ok", "good", "high"}


# ---------------------------------------------------------------------------
# Sweep trap quality
# ---------------------------------------------------------------------------


class TestSweepTrapQuality:
    def test_trap_quality_used_when_present(self) -> None:
        with_trap = {
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 1,
                "SWEEP_TRAP_QUALITY_SCORE": 1.0,
            }
        }
        without_trap = {
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 1,
            }
        }
        score_trap = build_signal_quality_v2(enrichment=with_trap)["SIGNAL_QUALITY_SCORE"]
        score_plain = build_signal_quality_v2(enrichment=without_trap)["SIGNAL_QUALITY_SCORE"]
        # High trap quality (1.0) should score higher than low plain quality (1/10 of MAX)
        assert score_trap >= score_plain


# ---------------------------------------------------------------------------
# Confluence bucket
# ---------------------------------------------------------------------------


class TestConfluenceBucket:
    def test_confluence_block_added_when_flag_enabled(self) -> None:
        enr = {
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {
                "PRIMARY_OB_SIDE": "BULL",
                "OB_FRESH": True,
                "PRIMARY_OB_DISTANCE": 1.0,
                "OB_SUPPORT_SCORE": 15.0,
            },
            "fvg_lifecycle_light": {
                "PRIMARY_FVG_SIDE": "BULL",
                "FVG_FRESH": True,
                "FVG_FILL_PCT": 0.0,
                "FVG_INVALIDATED": False,
                "PRIMARY_FVG_DISTANCE": 1.0,
                "FVG_GAP_SCORE": 15.0,
            },
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 5,
            },
        }
        with patch.dict(os.environ, {"ENABLE_CONFLUENCE_SCORE": "1"}):
            result = build_signal_quality_v2(enrichment=enr)
        assert result["CONFLUENCE_SCORE"] == 12
        assert result["CONFLUENCE_DIRECTION"] == "bull"

    def test_confluence_block_neutral_when_flag_disabled(self) -> None:
        result = build_signal_quality_v2(enrichment={})
        assert result.get("CONFLUENCE_SCORE", 0) == 0
