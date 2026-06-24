"""Integration test for the full SMC v2 signal-quality surface."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from scripts.smc_signal_quality import build_signal_quality


@pytest.fixture(autouse=True)
def _reset_env() -> Iterator[None]:
    """Reset all v2 feature flags after each test."""
    keys = {
        "SIGNAL_QUALITY_MODEL",
        "ENABLE_FRESHNESS_V2",
        "ENABLE_CONFLUENCE_SCORE",
        "ENABLE_SWEEP_TRAP",
        "ENABLE_REACTION_ZONE",
        "ENABLE_SMT_DIVERGENCE",
    }
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def _enable_all_v2_flags() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    os.environ["ENABLE_FRESHNESS_V2"] = "1"
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    os.environ["ENABLE_REACTION_ZONE"] = "1"
    os.environ["ENABLE_SMT_DIVERGENCE"] = "1"


def _make_full_enrichment() -> dict:
    return {
        "structure_state_light": {
            "STRUCTURE_FRESH": True,
            "STRUCTURE_EVENT_AGE_BARS": 2,
            "STRUCTURE_LAST_EVENT": "BOS_BULL",
        },
        "session_context_light": {
            "SESSION_DIRECTION_BIAS": "BULLISH",
            "SESSION_CONTEXT_SCORE": 5,
            "IN_KILLZONE": True,
        },
        "ob_context_light": {
            "PRIMARY_OB_SIDE": "BULL",
            "OB_FRESH": True,
            "PRIMARY_OB_DISTANCE": 1.5,
        },
        "fvg_lifecycle_light": {
            "PRIMARY_FVG_SIDE": "BULL",
            "FVG_FRESH": True,
            "FVG_FILL_PCT": 0.1,
            "FVG_INVALIDATED": False,
        },
        "liquidity_sweeps": {
            "RECENT_BULL_SWEEP": True,
            "RECENT_BEAR_SWEEP": False,
            "SWEEP_DIRECTION": "BULL",
            "SWEEP_QUALITY_SCORE": 1,
        },
        "compression_regime": {"ATR_REGIME": "NORMAL"},
        "correlated_context": {
            "CORRELATED_BIAS": "BEARISH",
            "CORRELATED_LAST_EVENT": "BOS_BEAR",
        },
    }


def test_all_v2_features_enabled_produces_expected_keys() -> None:
    """When every v2 feature is on, build_signal_quality returns every v2 field."""
    _enable_all_v2_flags()
    result = build_signal_quality(enrichment=_make_full_enrichment())

    # Core v1 fields are still present.
    assert "SIGNAL_QUALITY_SCORE" in result
    assert "SIGNAL_QUALITY_TIER" in result
    assert "SIGNAL_WARNINGS" in result
    assert "SIGNAL_BIAS_ALIGNMENT" in result
    assert "SIGNAL_FRESHNESS" in result

    # Phase A: Freshness v2
    assert result["SIGNAL_FRESHNESS"] == "very_fresh"

    # Phase D: Confluence score
    assert result["CONFLUENCE_SCORE"] == 100
    assert result["CONFLUENCE_DIRECTION"] == "bull"

    # Phase B: Sweep trap
    assert result["SWEEP_TRAP_DETECTED"] is True
    assert result["SWEEP_TRAP_CONFIDENCE"] == 100

    # Phase C: Reaction zone
    assert result["REACTION_ZONE_DETECTED"] is True
    assert result["REACTION_ZONE_DIRECTION"] == "bull"
    assert result["REACTION_ZONE_CONFIDENCE"] == 60

    # Phase E: SMT divergence
    assert result["SMT_DIVERGENCE_DETECTED"] is True
    assert result["SMT_DIVERGENCE_SIDE"] == "bear"
    assert result["SMT_DIVERGENCE_CONFIDENCE"] == 70


def test_v2_features_respect_individual_flags() -> None:
    """Each detector is independent: only enabled flags appear in the result."""
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"

    result = build_signal_quality(enrichment=_make_full_enrichment())

    assert "CONFLUENCE_SCORE" in result
    assert "SWEEP_TRAP_DETECTED" not in result
    assert "REACTION_ZONE_DETECTED" not in result
    assert "SMT_DIVERGENCE_DETECTED" not in result


def test_v2_overrides_win_across_all_features() -> None:
    """Manual overrides take precedence over every v2-derived field."""
    _enable_all_v2_flags()
    overrides = {
        "SIGNAL_FRESHNESS": "manual_fresh",
        "CONFLUENCE_SCORE": 42,
        "CONFLUENCE_DIRECTION": "neutral",
        "SWEEP_TRAP_DETECTED": False,
        "SWEEP_TRAP_CONFIDENCE": 0,
        "REACTION_ZONE_DETECTED": False,
        "REACTION_ZONE_DIRECTION": "neutral",
        "REACTION_ZONE_CONFIDENCE": 0,
        "SMT_DIVERGENCE_DETECTED": False,
        "SMT_DIVERGENCE_SIDE": "none",
        "SMT_DIVERGENCE_CONFIDENCE": 0,
    }
    result = build_signal_quality(enrichment=_make_full_enrichment(), overrides=overrides)
    for key, value in overrides.items():
        assert result[key] == value
