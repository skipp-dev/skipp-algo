"""Tests for smc_core.sweep_trap (Phase B)."""
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
    result = detect_sweep_trap(
        enrichment={"liquidity_sweeps": {"RECENT_BULL_SWEEP": True, "SWEEP_QUALITY_SCORE": 1}}
    )
    assert result == {"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_CONFIDENCE": 0}


def test_enabled_no_sweep_returns_neutral() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(enrichment={})
    assert result["SWEEP_TRAP_DETECTED"] is False
    assert result["SWEEP_TRAP_CONFIDENCE"] == 0


def test_enabled_low_quality_bull_sweep_detected() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(
        enrichment={
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 2,
            }
        }
    )
    assert result["SWEEP_TRAP_DETECTED"] is True
    assert result["SWEEP_TRAP_CONFIDENCE"] == 80


def test_enabled_high_quality_returns_neutral() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    result = detect_sweep_trap(
        enrichment={
            "liquidity_sweeps": {
                "RECENT_BULL_SWEEP": True,
                "RECENT_BEAR_SWEEP": False,
                "SWEEP_DIRECTION": "BULL",
                "SWEEP_QUALITY_SCORE": 9,
            }
        }
    )
    assert result["SWEEP_TRAP_DETECTED"] is False
    assert result["SWEEP_TRAP_CONFIDENCE"] == 0
