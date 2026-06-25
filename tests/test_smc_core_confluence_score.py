"""Tests for the smc_core.smc_confluence integration in signal quality (Phase D)."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from scripts.smc_signal_quality import build_signal_quality_v2
from smc_core.smc_confluence import compute_confluence


@pytest.fixture(autouse=True)
def _clear_env() -> Iterator[None]:
    key = "ENABLE_CONFLUENCE_SCORE"
    saved = os.environ.pop(key, None)
    yield
    if saved is not None:
        os.environ[key] = saved
    else:
        os.environ.pop(key, None)


_FULL_BULLISH = {
    "PRIMARY_OB_SIDE": "BULL",
    "OB_FRESH": True,
    "PRIMARY_OB_DISTANCE": 1.0,
    "OB_SUPPORT_SCORE": 15.0,
}
_FULL_BULLISH_FVG = {
    "PRIMARY_FVG_SIDE": "BULL",
    "FVG_FRESH": True,
    "FVG_FILL_PCT": 0.0,
    "FVG_INVALIDATED": False,
    "PRIMARY_FVG_DISTANCE": 1.0,
    "FVG_GAP_SCORE": 15.0,
}
_FULL_BULLISH_SWEEP = {
    "RECENT_BULL_SWEEP": True,
    "SWEEP_DIRECTION": "BULL",
    "SWEEP_QUALITY_SCORE": 5,
}


def test_compute_confluence_no_signals() -> None:
    result = compute_confluence(None, None, None)
    assert result.raw_confluence_score == pytest.approx(0.0)
    assert result.confluence_tier == "NONE"


def test_compute_confluence_full() -> None:
    result = compute_confluence(_FULL_BULLISH, _FULL_BULLISH_FVG, _FULL_BULLISH_SWEEP)
    assert result.raw_confluence_score == pytest.approx(1.0)
    assert result.confluence_tier == "HIGH"


def test_build_signal_quality_v2_full_confluence() -> None:
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    enrichment = {
        "ob_context_light": _FULL_BULLISH,
        "fvg_lifecycle_light": _FULL_BULLISH_FVG,
        "liquidity_sweeps": _FULL_BULLISH_SWEEP,
    }
    result = build_signal_quality_v2(enrichment=enrichment)
    assert result["CONFLUENCE_SCORE"] == 12
    assert result["CONFLUENCE_DIRECTION"] == "bull"
    assert result["CONFLUENCE_TIER"] == "HIGH"


def test_build_signal_quality_v2_confluence_disabled() -> None:
    enrichment = {
        "ob_context_light": _FULL_BULLISH,
        "fvg_lifecycle_light": _FULL_BULLISH_FVG,
        "liquidity_sweeps": _FULL_BULLISH_SWEEP,
    }
    result = build_signal_quality_v2(enrichment=enrichment)
    assert "CONFLUENCE_SCORE" not in result


def test_build_signal_quality_v2_mixed_direction_neutral() -> None:
    os.environ["ENABLE_CONFLUENCE_SCORE"] = "1"
    enrichment = {
        "ob_context_light": {
            "PRIMARY_OB_SIDE": "BEAR",
            "OB_FRESH": True,
            "PRIMARY_OB_DISTANCE": 1.0,
            "OB_SUPPORT_SCORE": 15.0,
        },
        "fvg_lifecycle_light": _FULL_BULLISH_FVG,
        "liquidity_sweeps": {"SWEEP_DIRECTION": "NONE"},
    }
    result = build_signal_quality_v2(enrichment=enrichment)
    assert result["CONFLUENCE_DIRECTION"] == "neutral"
