"""Tests for smc_core.reaction_zone (Phase C)."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from smc_core.reaction_zone import detect_reaction_zone


@pytest.fixture(autouse=True)
def _clear_env() -> Iterator[None]:
    key = "ENABLE_REACTION_ZONE"
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
    assert result["REACTION_ZONE_DETECTED"] is False
    assert result["REACTION_ZONE_CONFIDENCE"] == 0
    assert result["REACTION_ZONE_DIRECTION"] == "neutral"


def test_enabled_no_anchor_returns_neutral() -> None:
    os.environ["ENABLE_REACTION_ZONE"] = "1"
    result = detect_reaction_zone(enrichment={})
    assert result["REACTION_ZONE_DETECTED"] is False


def test_enabled_bullish_zone_with_bias_alignment() -> None:
    os.environ["ENABLE_REACTION_ZONE"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_DISTANCE": 1.5, "PRIMARY_OB_SIDE": "BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
        }
    )
    assert result["REACTION_ZONE_DETECTED"] is True
    assert result["REACTION_ZONE_DIRECTION"] == "bull"
    assert result["REACTION_ZONE_CONFIDENCE"] == 60


def test_enabled_bearish_zone_without_bias_alignment() -> None:
    os.environ["ENABLE_REACTION_ZONE"] = "1"
    result = detect_reaction_zone(
        enrichment={
            "liquidity_sweeps": {"RECENT_BEAR_SWEEP": True, "SWEEP_DIRECTION": "BEAR"},
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_DISTANCE": 2.0, "PRIMARY_FVG_SIDE": "BEAR"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
        }
    )
    assert result["REACTION_ZONE_DETECTED"] is True
    assert result["REACTION_ZONE_DIRECTION"] == "bear"
    assert result["REACTION_ZONE_CONFIDENCE"] == 40
