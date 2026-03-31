"""Tests for smc_core.bias_merge — HTF/Session single source of truth."""

from __future__ import annotations

import pytest

from smc_core.bias_merge import BiasVerdict, merge_bias


def _htf(counter: int) -> dict:
    return {"fvg_bias_counter": [{"counter": counter, "direction": "BULLISH" if counter > 0 else "BEARISH" if counter < 0 else "NEUTRAL"}]}


def _session_bullish() -> dict:
    return {"killzones": [{"high": 200.0, "low": 190.0, "mid": 196.0}]}  # ratio 0.6 > 0.55 → BULLISH


def _session_bearish() -> dict:
    return {"killzones": [{"high": 200.0, "low": 190.0, "mid": 194.0}]}  # ratio 0.4 < 0.45 → BEARISH


def _session_neutral() -> dict:
    return {"killzones": [{"high": 200.0, "low": 190.0, "mid": 195.0}]}  # ratio 0.5 → NEUTRAL


# --- both missing ---


def test_both_missing() -> None:
    v = merge_bias(None, None)
    assert v.direction == "NEUTRAL"
    assert v.confidence == 0.0
    assert v.source == "NONE"
    assert not v.conflict


# --- HTF only ---


def test_htf_only_bullish() -> None:
    v = merge_bias(_htf(3), None)
    assert v.direction == "BULLISH"
    assert v.source == "HTF"
    assert not v.conflict


def test_htf_only_bearish() -> None:
    v = merge_bias(_htf(-2), None)
    assert v.direction == "BEARISH"


# --- Session only ---


def test_session_only() -> None:
    v = merge_bias(None, _session_bullish())
    assert v.direction == "BULLISH"
    assert v.source == "SESSION"
    assert v.confidence == 0.5


# --- Both available, concordant ---


def test_concordant_bullish() -> None:
    v = merge_bias(_htf(3), _session_bullish())
    assert v.direction == "BULLISH"
    assert v.source == "MERGED"
    assert not v.conflict
    assert v.confidence > 0.8  # concordance bonus


# --- Both available, conflicting ---


def test_conflict_htf_dominates() -> None:
    v = merge_bias(_htf(3), _session_bearish())
    assert v.direction == "BULLISH"  # HTF dominates
    assert v.conflict is True
    assert v.confidence < 0.8  # reduced due to conflict


def test_conflict_bearish_htf() -> None:
    v = merge_bias(_htf(-2), _session_bullish())
    assert v.direction == "BEARISH"  # HTF still dominates
    assert v.conflict is True


# --- Determinism ---


def test_determinism() -> None:
    results = {merge_bias(_htf(3), _session_bearish()).direction for _ in range(50)}
    assert results == {"BULLISH"}


# --- Neutral HTF + directional session ---


def test_htf_neutral_session_directional() -> None:
    v = merge_bias(_htf(0), _session_bullish())
    assert v.direction == "NEUTRAL"  # HTF neutral dominates
    assert not v.conflict


# --- Empty dicts ---


def test_empty_dicts_treated_as_missing() -> None:
    v = merge_bias({}, {})
    assert v.direction == "NEUTRAL"
    assert v.source == "NONE"
