"""Tests for smc_core.v2_config tunables."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from smc_core import v2_config
from smc_core.sweep_trap import detect_sweep_trap


@pytest.fixture(autouse=True)
def _clear_env() -> Iterator[None]:
    keys = [
        "ENABLE_SWEEP_TRAP",
        "SMC_SWEEP_TRAP_QUALITY_THRESHOLD",
        "SMC_SWEEP_TRAP_LOPSIDED_BOOST",
        "SMC_SWEEP_TRAP_REVERSAL_PENALTY",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def test_default_quality_threshold() -> None:
    assert v2_config.sweep_trap_config.quality_threshold == 3


def test_custom_quality_threshold_via_env() -> None:
    os.environ["SMC_SWEEP_TRAP_QUALITY_THRESHOLD"] = "4"
    assert v2_config.sweep_trap_config.quality_threshold == 4


def test_quality_threshold_clamped_high() -> None:
    os.environ["SMC_SWEEP_TRAP_QUALITY_THRESHOLD"] = "10"
    assert v2_config.sweep_trap_config.quality_threshold == 5


def test_quality_threshold_clamped_low() -> None:
    os.environ["SMC_SWEEP_TRAP_QUALITY_THRESHOLD"] = "-1"
    assert v2_config.sweep_trap_config.quality_threshold == 0


def test_custom_lopsided_boost_changes_confidence() -> None:
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    os.environ["SMC_SWEEP_TRAP_LOPSIDED_BOOST"] = "5"
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
    # quality 1 -> 80, lopsided boost 5 -> 85
    assert result["SWEEP_TRAP_CONFIDENCE"] == 85
