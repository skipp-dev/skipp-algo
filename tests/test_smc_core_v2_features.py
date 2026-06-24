"""Tests for smc_core.v2_features isolation layer."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

from smc_core.v2_features import (
    active_signal_quality_model,
    confluence_score_enabled,
    freshness_v2_enabled,
    reaction_zone_enabled,
    smt_divergence_enabled,
    sweep_trap_enabled,
)


@pytest.fixture(autouse=True)
def _clear_feature_flags() -> Iterator[None]:
    """Remove all SMC v2 feature flags before each test."""
    keys = [
        "ENABLE_SWEEP_TRAP",
        "ENABLE_REACTION_ZONE",
        "ENABLE_CONFLUENCE_SCORE",
        "ENABLE_FRESHNESS_V2",
        "ENABLE_SMT_DIVERGENCE",
        "SIGNAL_QUALITY_MODEL",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


@pytest.mark.parametrize(
    "env_var,func",
    [
        ("ENABLE_SWEEP_TRAP", sweep_trap_enabled),
        ("ENABLE_REACTION_ZONE", reaction_zone_enabled),
        ("ENABLE_CONFLUENCE_SCORE", confluence_score_enabled),
        ("ENABLE_FRESHNESS_V2", freshness_v2_enabled),
        ("ENABLE_SMT_DIVERGENCE", smt_divergence_enabled),
    ],
)
def test_feature_default_off(env_var: str, func: Callable[[], bool]) -> None:
    assert func() is False


@pytest.mark.parametrize(
    "env_var,func",
    [
        ("ENABLE_SWEEP_TRAP", sweep_trap_enabled),
        ("ENABLE_REACTION_ZONE", reaction_zone_enabled),
        ("ENABLE_CONFLUENCE_SCORE", confluence_score_enabled),
        ("ENABLE_FRESHNESS_V2", freshness_v2_enabled),
        ("ENABLE_SMT_DIVERGENCE", smt_divergence_enabled),
    ],
)
def test_feature_explicit_on(env_var: str, func: Callable[[], bool]) -> None:
    os.environ[env_var] = "1"
    assert func() is True


def test_active_signal_quality_model_default_v1() -> None:
    assert active_signal_quality_model() == "v1"


def test_active_signal_quality_model_v2() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2"
    assert active_signal_quality_model() == "v2"


def test_active_signal_quality_model_v2_1() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v2.1"
    assert active_signal_quality_model() == "v2.1"


def test_active_signal_quality_model_unknown_fallback() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "v3"
    assert active_signal_quality_model() == "v1"


def test_active_signal_quality_model_empty_fallback() -> None:
    os.environ["SIGNAL_QUALITY_MODEL"] = "  "
    assert active_signal_quality_model() == "v1"
