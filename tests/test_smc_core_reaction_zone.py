"""Tests for smc_core.reaction_zone (Phase C)."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from smc_core.reaction_zone import detect_reaction_zone


@pytest.fixture(autouse=True)
def _clear_env() -> Iterator[None]:
    key = "ENABLE_REACTION_CONTEXT"
    saved = os.environ.pop(key, None)
    yield
    if saved is not None:
        os.environ[key] = saved
    else:
        os.environ.pop(key, None)


def test_disabled_returns_neutral() -> None:
    result = detect_reaction_zone(
        enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 1.5, "PRIMARY_OB_SIDE": "BULL"},
        }
    )
    assert result["REACTION_CONTEXT_DETECTED"] is False
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 0
    assert result["REACTION_CONTEXT_DIRECTION"] == "neutral"


def test_enabled_no_anchor_returns_neutral() -> None:
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(enrichment={})
    assert result["REACTION_CONTEXT_DETECTED"] is False


def test_near_support_without_resolvable_direction_not_detected() -> None:
    """Near support + fresh structure but no resolvable side -> NOT detected.

    A reaction zone whose direction stays "neutral" (no OB/FVG/sweep/structure
    side) is not actionable and must not be emitted as detected.
    """
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(
        enrichment={
            # fresh structure passes the entry gate, but no directional event
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "NONE"},
            # near support, but side unresolved
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 1.5, "PRIMARY_OB_SIDE": "NONE"},
        }
    )
    assert result["REACTION_CONTEXT_DETECTED"] is False
    assert result["REACTION_CONTEXT_DIRECTION"] == "neutral"
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 0


def test_enabled_bullish_zone_with_bias_alignment() -> None:
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 1.5, "PRIMARY_OB_SIDE": "BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
        }
    )
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bull"
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 60


def test_enabled_bearish_zone_without_bias_alignment() -> None:
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "liquidity_sweeps": {"RECENT_BEAR_SWEEP": True, "SWEEP_DIRECTION": "BEAR"},
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_DISTANCE": 2.0, "PRIMARY_FVG_SIDE": "BEAR"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
        }
    )
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bear"
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 40

def test_enabled_ob_takes_direction_priority_over_fvg() -> None:  # 2026-07-13: renamed — the old name claimed the OPPOSITE of what it asserts (OB precedence)
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 1.5, "PRIMARY_OB_SIDE": "BEAR"},
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_DISTANCE": 2.0, "PRIMARY_FVG_SIDE": "BULL"},
        }
    )
    # OB is checked first in direction resolution.
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bear"


def test_enabled_distance_too_far_returns_neutral() -> None:
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 5.0, "PRIMARY_OB_SIDE": "BULL"},
        }
    )
    assert result["REACTION_CONTEXT_DETECTED"] is False
    assert result["REACTION_CONTEXT_CONFIDENCE"] == 0



def test_direction_comes_only_from_the_qualifying_support() -> None:
    """A stale/far OB must not overwrite the direction of the FVG that actually
    qualified the detection (direction is derived per-support, post-qualification)."""
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            # OB: BEAR side but stale AND far -> does not qualify, must not steer.
            "ob_context_light": {"OB_FRESH": False, "PRIMARY_OB_DISTANCE": 99.0, "PRIMARY_OB_SIDE": "BEAR"},
            # FVG: fresh and near -> the actual qualifier.
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_DISTANCE": 0.5, "PRIMARY_FVG_SIDE": "BULL"},
        }
    )
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bull"


def test_qualifying_ob_still_takes_precedence_over_fvg() -> None:
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BEAR"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 0.5, "PRIMARY_OB_SIDE": "BEAR"},
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_DISTANCE": 0.5, "PRIMARY_FVG_SIDE": "BULL"},
        }
    )
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bear"


def test_qualifying_support_with_side_none_falls_back_to_sweep_direction() -> None:
    """Post qualification-gated direction (#3592): a qualifying OB whose side is
    NONE must not end the resolution — the sweep/structure fallback chain still
    supplies the direction."""
    os.environ["ENABLE_REACTION_CONTEXT"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "NONE"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 0.5, "PRIMARY_OB_SIDE": "NONE"},
            "liquidity_sweeps": {"RECENT_BULL_SWEEP": True, "SWEEP_DIRECTION": "BULL"},
        }
    )
    assert result["REACTION_CONTEXT_DETECTED"] is True
    assert result["REACTION_CONTEXT_DIRECTION"] == "bull"
