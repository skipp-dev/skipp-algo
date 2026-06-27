"""Tests for smc_core.sweep_trap (Phase B hardening)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from smc_core.sweep_trap import detect_sweep_trap


@pytest.fixture(autouse=True)
def _clear_env() -> Iterator[None]:
    key = "ENABLE_SWEEP_TRAP"
    saved = os.environ.pop(key, None)
    yield
    if saved is not None:
        os.environ[key] = saved
    else:
        os.environ.pop(key, None)


def test_disabled_returns_neutral() -> None:
    result = detect_sweep_trap(enrichment={"liquidity_sweeps": {"RECENT_BULL_SWEEP": True, "SWEEP_QUALITY_SCORE": 1}})
    assert result == {"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_CONFIDENCE": 0}


def test_enabled_no_sweep_returns_neutral() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(enrichment={})
    assert result["SWEEP_TRAP_DETECTED"] is False
    assert result["SWEEP_TRAP_CONFIDENCE"] == 0


def test_enabled_low_quality_bull_sweep_lopsided_boost() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(
        enrichment={
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 1,
            }
        }
    )
    assert result["SWEEP_TRAP_DETECTED"] is True
    # quality 1 -> 80, lopsided boost +20, no reversal -> 100 (clamped)
    assert result["SWEEP_TRAP_CONFIDENCE"] == 100


def test_enabled_high_quality_returns_neutral() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(
        enrichment={
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 4,
            }
        }
    )
    assert result["SWEEP_TRAP_DETECTED"] is False
    assert result["SWEEP_TRAP_CONFIDENCE"] == 0


def test_enabled_both_sweeps_no_direction_boost() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(
        enrichment={
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": True,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 2,
            }
        }
    )
    assert result["SWEEP_TRAP_DETECTED"] is True
    # quality 2 -> 60, both sides present -> no boost
    assert result["SWEEP_TRAP_CONFIDENCE"] == 60


def test_enabled_reversal_against_sweep_cancels_trap() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(
        enrichment={
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 0,
            },
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "CHOCH_BEAR"},
        }
    )
    # quality 0 -> 100, lopsided +20, reversal penalty -40 -> 80
    assert result["SWEEP_TRAP_DETECTED"] is True
    assert result["SWEEP_TRAP_CONFIDENCE"] == 80


def test_float_quality_score_is_rounded_not_truncated() -> None:
    """Regression: float quality scores must round, not truncate."""
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    # 2.4 rounds to 2 (below default threshold 3) -> trap active.
    result = detect_sweep_trap(
        enrichment={
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 2.4,
            }
        }
    )
    assert result["SWEEP_TRAP_DETECTED"] is True
    # quality 2 -> 60, lopsided +20 -> 80
    assert result["SWEEP_TRAP_CONFIDENCE"] == 80


def test_enabled_strong_reversal_neutralises_trap() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(
        enrichment={
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 2,
            },
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "CHOCH_BEAR"},
        }
    )
    # quality 2 -> 60, lopsided +20, reversal -40 -> 40
    assert result["SWEEP_TRAP_DETECTED"] is True
    assert result["SWEEP_TRAP_CONFIDENCE"] == 40
