"""Tests for smc_core.confluence_score (Phase D)."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from smc_core.confluence_score import compute_confluence_score


@pytest.fixture(autouse=True)
def _clear_env() -> Iterator[None]:
    key = "ENABLE_CONFLUENCE_SCORE"
    saved = os.environ.pop(key, None)
    yield
    if saved is not None:
        os.environ[key] = saved
    else:
        os.environ.pop(key, None)


def test_disabled_returns_neutral() -> None:
    result = compute_confluence_score(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
        }
    )
    assert result == {"CONFLUENCE_SCORE": 0, "CONFLUENCE_DIRECTION": "neutral"}


def test_enabled_no_signals_returns_neutral() -> None:
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    result = compute_confluence_score(enrichment={})
    assert result["CONFLUENCE_SCORE"] == 0
    assert result["CONFLUENCE_DIRECTION"] == "neutral"


def test_enabled_full_bullish_confluence() -> None:
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    result = compute_confluence_score(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {"PRIMARY_OB_SIDE": "BULL", "OB_FRESH": True},
            "fvg_lifecycle_light": {"PRIMARY_FVG_SIDE": "BULL", "FVG_FRESH": True},
            "liquidity_sweeps": {"SWEEP_DIRECTION": "BULL"},
        }
    )
    assert result["CONFLUENCE_SCORE"] == 100
    assert result["CONFLUENCE_DIRECTION"] == "bull"


def test_enabled_mixed_signals_neutral() -> None:
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    result = compute_confluence_score(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BEARISH"},
            "ob_context_light": {"PRIMARY_OB_SIDE": "BEAR", "OB_FRESH": True},
            "fvg_lifecycle_light": {"PRIMARY_FVG_SIDE": "BULL", "FVG_FRESH": True},
            "liquidity_sweeps": {"SWEEP_DIRECTION": "NONE"},
        }
    )
    assert result["CONFLUENCE_SCORE"] == 0
    assert result["CONFLUENCE_DIRECTION"] == "neutral"


def test_enabled_clamped_to_100() -> None:
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    result = compute_confluence_score(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {"PRIMARY_OB_SIDE": "BULL", "OB_FRESH": True},
            "fvg_lifecycle_light": {"PRIMARY_FVG_SIDE": "BULL", "FVG_FRESH": True},
            "liquidity_sweeps": {"SWEEP_DIRECTION": "BULL"},
        }
    )
    assert result["CONFLUENCE_SCORE"] <= 100

def test_enabled_partial_confluence_score_40() -> None:
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    result = compute_confluence_score(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
        }
    )
    assert result["CONFLUENCE_SCORE"] == 40
    assert result["CONFLUENCE_DIRECTION"] == "bull"


def test_enabled_partial_confluence_score_60() -> None:
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    result = compute_confluence_score(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {"PRIMARY_OB_SIDE": "BULL", "OB_FRESH": True},
        }
    )
    assert result["CONFLUENCE_SCORE"] == 60
    assert result["CONFLUENCE_DIRECTION"] == "bull"

