"""Tests for Phase A Freshness v2 in scripts.smc_signal_quality."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from scripts.smc_signal_quality import build_signal_quality


@pytest.fixture(autouse=True)
def _reset_env() -> Iterator[None]:
    """Reset env vars that influence routing / freshness v2."""
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


def test_v2_routes_to_v1_when_flag_off() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    result = build_signal_quality(enrichment={})
    assert result["SIGNAL_FRESHNESS"] == "stale"


def test_v2_uses_extended_freshness_when_flag_on() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    os.environ["ENABLE_FRESHNESS_V2"] = "1"
    enrichment = {
        "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_EVENT_AGE_BARS": 2},
        "fvg_lifecycle_light": {"FVG_FRESH": True},
        "ob_context_light": {"OB_FRESH": True},
        "session_context_light": {"IN_KILLZONE": True},
        "liquidity_sweeps": {"RECENT_BULL_SWEEP": True},
        "compression_regime": {"ATR_REGIME": "NORMAL"},
    }
    result = build_signal_quality(enrichment=enrichment)
    assert result["SIGNAL_FRESHNESS"] == "very_fresh"


def test_v2_freshness_expired_when_exhaustion() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    os.environ["ENABLE_FRESHNESS_V2"] = "1"
    enrichment = {
        "structure_state_light": {"STRUCTURE_FRESH": False, "STRUCTURE_EVENT_AGE_BARS": 60},
        "fvg_lifecycle_light": {"FVG_FRESH": False},
        "ob_context_light": {"OB_FRESH": False},
        "compression_regime": {"ATR_REGIME": "EXHAUSTION"},
    }
    result = build_signal_quality(enrichment=enrichment)
    assert result["SIGNAL_FRESHNESS"] == "expired"


def test_v2_feature_flag_triggers_v2_routing_with_default_model() -> None:
    os.environ["ENABLE_FRESHNESS_V2"] = "1"
    enrichment = {
        "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_EVENT_AGE_BARS": 2},
        "fvg_lifecycle_light": {"FVG_FRESH": True},
        "ob_context_light": {"OB_FRESH": True},
        "session_context_light": {"IN_KILLZONE": True},
        "liquidity_sweeps": {"RECENT_BULL_SWEEP": True},
        "compression_regime": {"ATR_REGIME": "NORMAL"},
    }
    result = build_signal_quality(enrichment=enrichment)
    # The feature flag forces v2 routing even when SIGNAL_QUALITY_MODEL is unset.
    assert result["SIGNAL_FRESHNESS"] == "very_fresh"


def test_overrides_still_win_with_v2_freshness() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    os.environ["ENABLE_FRESHNESS_V2"] = "1"
    result = build_signal_quality(
        enrichment={},
        overrides={"SIGNAL_FRESHNESS": "manual"},
    )
    assert result["SIGNAL_FRESHNESS"] == "manual"


def test_v2_includes_confluence_score_when_enabled() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    result = build_signal_quality(
        enrichment={
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
    )
    assert "CONFLUENCE_SCORE" in result
    assert "CONFLUENCE_DIRECTION" in result
    assert result["CONFLUENCE_SCORE"] == 12
    assert result["CONFLUENCE_DIRECTION"] == "bull"
