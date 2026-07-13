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


def test_reversal_against_sweep_reduces_confidence_but_stays_detected() -> None:
    # NOTE: a structure reversal only SUBTRACTS ``reversal_penalty``; it does not
    # cancel/deactivate the candidate (the old name "cancels_trap" was a
    # misnomer). Confidence merely drops by the penalty and stays above 0, so
    # DETECTED remains True.
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
    # quality 0 -> factor 100, lopsided +20, reversal penalty -40 -> 80
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


def test_reversal_reduces_confidence_but_quality2_stays_detected() -> None:
    # Same misnomer guard at quality 2: the reversal drops confidence to 40 but
    # the candidate is STILL detected (the old name "neutralises_trap" was wrong).
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
    # quality 2 -> 60, lopsided +20, reversal -40 -> 40 (still detected)
    assert result["SWEEP_TRAP_DETECTED"] is True
    assert result["SWEEP_TRAP_CONFIDENCE"] == 40


def test_reversal_only_neutralises_when_penalty_drives_confidence_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The candidate collapses to neutral ONLY when the reversal penalty is
    large enough to zero out confidence — with the default penalty (40) a valid
    low-quality sweep (min factor 60) can never reach 0, so the neutral branch
    is unreachable via reversal alone. Raising the penalty to factor+boost hits
    exactly 0 and returns the neutral block."""
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    # quality 2 -> factor 60, lopsided +20 = 80; penalty 80 -> confidence 0.
    monkeypatch.setenv("SMC_SWEEP_TRAP_REVERSAL_PENALTY", "80")
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
    assert result == {"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_CONFIDENCE": 0}


def test_default_penalty_cannot_neutralise_a_valid_candidate() -> None:
    """Guard the F5 truth directly: across every quality that can form a trap
    (0,1,2 < default threshold 3), the default reversal penalty (40) never
    drives DETECTED to False — confidence only shrinks."""
    os.environ["ENABLE_SWEEP_TRAP"] = "1"
    for quality in (0, 1, 2):
        result = detect_sweep_trap(
            enrichment={
                "liquidity_sweeps": {
                    "RECENT_BULL_SWEEP": True,
                    "RECENT_BEAR_SWEEP": False,
                    "SWEEP_DIRECTION": "BULL",
                    "SWEEP_QUALITY_SCORE": quality,
                },
                "structure_state_light": {"STRUCTURE_LAST_EVENT": "CHOCH_BEAR"},
            }
        )
        assert result["SWEEP_TRAP_DETECTED"] is True, quality
        assert result["SWEEP_TRAP_CONFIDENCE"] > 0, quality
