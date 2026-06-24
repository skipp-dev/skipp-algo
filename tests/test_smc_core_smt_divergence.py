"""Tests for smc_core.smt_divergence (Phase E)."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from smc_core.smt_divergence import detect_smt_divergence


@pytest.fixture(autouse=True)
def _clear_env() -> Iterator[None]:
    key = "ENABLE_SMT_DIVERGENCE"
    saved = os.environ.pop(key, None)
    yield
    if saved is not None:
        os.environ[key] = saved
    else:
        os.environ.pop(key, None)


def test_disabled_returns_neutral() -> None:
    result = detect_smt_divergence(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "correlated_context": {"CORRELATED_BIAS": "BEARISH"},
        }
    )
    assert result == {
        "SMT_DIVERGENCE_DETECTED": False,
        "SMT_DIVERGENCE_SIDE": "none",
        "SMT_DIVERGENCE_CONFIDENCE": 0,
    }


def test_enabled_no_primary_structure_returns_neutral() -> None:
    os.environ["ENABLE_SMT_DIVERGENCE"] = "1"
    result = detect_smt_divergence(enrichment={})
    assert result["SMT_DIVERGENCE_DETECTED"] is False


def test_enabled_bull_primary_with_bearish_correlated() -> None:
    os.environ["ENABLE_SMT_DIVERGENCE"] = "1"
    result = detect_smt_divergence(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "correlated_context": {"CORRELATED_BIAS": "BEARISH"},
        }
    )
    assert result["SMT_DIVERGENCE_DETECTED"] is True
    assert result["SMT_DIVERGENCE_SIDE"] == "bear"
    assert result["SMT_DIVERGENCE_CONFIDENCE"] == 70


def test_enabled_bear_primary_with_bullish_correlated() -> None:
    os.environ["ENABLE_SMT_DIVERGENCE"] = "1"
    result = detect_smt_divergence(
        enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "CHOCH_BEAR"},
            "correlated_context": {"CORRELATED_LAST_EVENT": "BOS_BULL"},
        }
    )
    assert result["SMT_DIVERGENCE_DETECTED"] is True
    assert result["SMT_DIVERGENCE_SIDE"] == "bull"
    assert result["SMT_DIVERGENCE_CONFIDENCE"] == 70
