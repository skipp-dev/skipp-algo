"""Property-test pin: ``c9_threshold_replay`` detector consensus invariants.

Companion to the deferred re-tuning in
https://github.com/skippALGO/skipp-algo/issues/298. The bauchgefühl
literals (0.3 mean-shift, 0.5/2.0 variance ratio) will be replaced by
calibrated t-/F-tests once ≥ 90 days of live data have accumulated.
This file pins the **structural** invariants of ``_episode_fires`` so
that the eventual swap of detectors 3 + 4 cannot silently regress:

- the 2-of-4 consensus arithmetic,
- the zero-variance guards on baseline/live,
- the KS-severity ladder (green/yellow/red) and its ``None`` handling,
- the immutability of ``Episode`` and the key-stability of
  ``ThresholdSetting``.

Pure stdlib + numpy. Runtime budget: < 1 s.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from scripts.c9_threshold_replay import (
    Episode,
    ThresholdSetting,
    _episode_fires,
    _is_drift_severity,
    _ks_severity,
)


# ── helpers ─────────────────────────────────────────────────────────


def _flat_episode(label: str = "x", *, drift: bool = False, n: int = 60) -> Episode:
    """Identical zero-variance baseline and live — no detector should fire."""
    zeros = tuple(0.0 for _ in range(n))
    return Episode(label=label, is_drift=drift, baseline=zeros, live=zeros)


def _shifted_episode(shift: float, *, n: int = 80, seed: int = 0) -> Episode:
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 1.0, n)
    live = rng.normal(shift, 1.0, n)
    return Episode(
        label=f"shift_{shift:+.2f}",
        is_drift=shift != 0.0,
        baseline=tuple(float(x) for x in base),
        live=tuple(float(x) for x in live),
    )


# ── _ks_severity ladder ────────────────────────────────────────────


def test_ks_severity_none_is_green() -> None:
    assert _ks_severity(None, p_yellow=0.05, p_red=0.01) == "green"


@pytest.mark.parametrize(
    "p,expected",
    [
        (0.0, "red"),
        (0.005, "red"),
        (0.01, "yellow"),  # exactly p_red — fails strict ``< p_red``
        (0.025, "yellow"),
        (0.05, "green"),  # exactly p_yellow — fails strict ``< p_yellow``
        (0.5, "green"),
        (1.0, "green"),
    ],
)
def test_ks_severity_threshold_boundaries(p: float, expected: str) -> None:
    assert _ks_severity(p, p_yellow=0.05, p_red=0.01) == expected


def test_ks_severity_yellow_window_excludes_red_and_green() -> None:
    # any p in [p_red, p_yellow) is yellow exactly
    for p in (0.011, 0.02, 0.0499):
        assert _ks_severity(p, p_yellow=0.05, p_red=0.01) == "yellow"


# ── _is_drift_severity boolean mapping ─────────────────────────────


@pytest.mark.parametrize(
    "severity,expected",
    [("red", True), ("yellow", True), ("green", False)],
)
def test_is_drift_severity_only_red_yellow(severity: str, expected: bool) -> None:
    assert _is_drift_severity(severity) is expected


# ── _episode_fires structural invariants ───────────────────────────


def test_identical_zero_variance_episode_never_fires() -> None:
    """bstd=lstd=0 short-circuits detectors 3 & 4; KS/PSI also benign."""
    ep = _flat_episode()
    for cmin in (1, 2, 3, 4):
        setting = ThresholdSetting(
            ks_p_red=0.01, ks_p_yellow=0.05, consensus_min=cmin
        )
        assert _episode_fires(ep, setting) is False, f"consensus_min={cmin}"


def test_consensus_min_above_max_detectors_never_fires() -> None:
    """Only 4 detectors exist; consensus_min=5 is unreachable by construction."""
    ep = _shifted_episode(3.0, seed=11)  # huge drift — most detectors fire
    setting = ThresholdSetting(
        ks_p_red=0.5, ks_p_yellow=0.9, consensus_min=5
    )
    assert _episode_fires(ep, setting) is False


def test_consensus_min_one_fires_on_strong_drift() -> None:
    ep = _shifted_episode(3.0, seed=13)
    setting = ThresholdSetting(
        ks_p_red=0.01, ks_p_yellow=0.05, consensus_min=1
    )
    assert _episode_fires(ep, setting) is True


def test_consensus_arithmetic_is_monotone_in_min() -> None:
    """Raising consensus_min can only turn a True into False, never reverse."""
    ep = _shifted_episode(0.8, seed=17)
    prev = True
    for cmin in (1, 2, 3, 4, 5):
        setting = ThresholdSetting(
            ks_p_red=0.01, ks_p_yellow=0.05, consensus_min=cmin
        )
        cur = _episode_fires(ep, setting)
        assert not (cur and not prev), (
            f"consensus_min={cmin} fired={cur} but lower bound was {prev}"
        )
        prev = cur


def test_zero_variance_baseline_disables_mean_and_variance_detectors() -> None:
    """When bstd == 0 detectors 3 + 4 cannot fire, regardless of live."""
    rng = np.random.default_rng(23)
    live = tuple(float(x) for x in rng.normal(5.0, 2.0, 80))
    ep = Episode(
        label="flat_base",
        is_drift=True,
        baseline=tuple(0.0 for _ in range(80)),
        live=live,
    )
    # ks_p_red impossibly high → KS always at least yellow; PSI may fire.
    setting = ThresholdSetting(
        ks_p_red=0.99, ks_p_yellow=0.999, consensus_min=3
    )
    # With detectors 3 & 4 disabled, max possible fire-count is 2 — below 3.
    assert _episode_fires(ep, setting) is False


def test_zero_variance_live_disables_variance_ratio_detector() -> None:
    """When lstd == 0 detector 4 cannot fire (ratio guard)."""
    rng = np.random.default_rng(29)
    baseline = tuple(float(x) for x in rng.normal(0.0, 1.0, 80))
    ep = Episode(
        label="flat_live",
        is_drift=True,
        baseline=baseline,
        live=tuple(0.0 for _ in range(80)),
    )
    # Detector 3 mean-shift definitely fires (|mean diff| / bstd ≥ 0.3 likely).
    # KS very likely fires. PSI likely fires. Detector 4 must NOT fire.
    setting = ThresholdSetting(
        ks_p_red=0.01, ks_p_yellow=0.05, consensus_min=4
    )
    # Max 3 detectors possible → 4-of-4 unreachable.
    assert _episode_fires(ep, setting) is False


def test_episode_fires_returns_bool() -> None:
    ep = _shifted_episode(1.5, seed=31)
    setting = ThresholdSetting(ks_p_red=0.01, ks_p_yellow=0.05)
    result = _episode_fires(ep, setting)
    assert isinstance(result, bool)


def test_episode_fires_is_deterministic() -> None:
    ep = _shifted_episode(0.6, seed=37)
    setting = ThresholdSetting(ks_p_red=0.01, ks_p_yellow=0.05, consensus_min=2)
    runs = {_episode_fires(ep, setting) for _ in range(5)}
    assert len(runs) == 1


# ── Episode immutability ───────────────────────────────────────────


def test_episode_is_frozen() -> None:
    ep = _flat_episode()
    with pytest.raises(FrozenInstanceError):
        ep.label = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ep.baseline = ()  # type: ignore[misc]


# ── ThresholdSetting key stability ─────────────────────────────────


def test_setting_key_is_deterministic_for_same_params() -> None:
    a = ThresholdSetting(0.01, 0.05, psi_n_buckets=10, consensus_min=2)
    b = ThresholdSetting(0.01, 0.05, psi_n_buckets=10, consensus_min=2)
    assert a.key() == b.key()


@pytest.mark.parametrize(
    "other",
    [
        ThresholdSetting(0.001, 0.05),  # ks_p_red differs
        ThresholdSetting(0.01, 0.025),  # ks_p_yellow differs
        ThresholdSetting(0.01, 0.05, psi_n_buckets=20),  # bins differs
        ThresholdSetting(0.01, 0.05, consensus_min=3),  # consensus differs
    ],
)
def test_setting_key_changes_with_each_axis(other: ThresholdSetting) -> None:
    base = ThresholdSetting(0.01, 0.05, psi_n_buckets=10, consensus_min=2)
    assert base.key() != other.key()


def test_setting_is_frozen() -> None:
    s = ThresholdSetting(0.01, 0.05)
    with pytest.raises(FrozenInstanceError):
        s.ks_p_red = 0.0  # type: ignore[misc]
