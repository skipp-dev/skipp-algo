"""Tests for ``scripts/regime_stratified_inference.py`` (Sprint C5 / T4)."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.regime_stratification import MIN_TRADES_PER_REGIME
from scripts.regime_stratified_inference import (
    regime_stratified_bootstrap,
    regime_stratified_permutation,
)


def _make_trades(regime: str, pnls: list[float]) -> list[dict]:
    return [{"pnl": p, "regime_at_entry": regime} for p in pnls]


def _mean(arr: np.ndarray) -> float:
    return float(arr.mean())


def _diff_means(a: np.ndarray, b: np.ndarray) -> float:
    return float(a.mean() - b.mean())


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_returns_none_when_no_regime_meets_floor() -> None:
    trades = _make_trades("calm", [0.1] * (MIN_TRADES_PER_REGIME - 1))
    out = regime_stratified_bootstrap(trades, _mean, B=100)
    assert out["statistic_observed"] is None
    assert out["ci_lower"] is None
    assert out["skipped_regimes"] == ["calm"]


def test_bootstrap_basic_ci_brackets_observed_mean() -> None:
    rng = np.random.default_rng(42)
    calm = rng.normal(0.001, 0.01, size=200).tolist()
    vol = rng.normal(0.005, 0.02, size=200).tolist()
    trades = _make_trades("calm", calm) + _make_trades("vol", vol)
    out = regime_stratified_bootstrap(
        trades, _mean, method="iid", B=200, seed=7
    )
    obs = out["statistic_observed"]
    assert out["ci_lower"] <= obs <= out["ci_upper"]
    assert out["n_resamples"] == 200
    assert out["per_regime_n"] == {"calm": 200, "vol": 200}


def test_bootstrap_determinism() -> None:
    trades = _make_trades("a", [0.01 * i for i in range(40)])
    out1 = regime_stratified_bootstrap(trades, _mean, method="iid", B=50, seed=3)
    out2 = regime_stratified_bootstrap(trades, _mean, method="iid", B=50, seed=3)
    assert out1["ci_lower"] == out2["ci_lower"]
    assert out1["ci_upper"] == out2["ci_upper"]


def test_bootstrap_different_seeds_yield_different_ci() -> None:
    trades = _make_trades("a", [0.01 * i for i in range(40)])
    out1 = regime_stratified_bootstrap(trades, _mean, method="iid", B=50, seed=1)
    out2 = regime_stratified_bootstrap(trades, _mean, method="iid", B=50, seed=2)
    assert (out1["ci_lower"], out1["ci_upper"]) != (
        out2["ci_lower"],
        out2["ci_upper"],
    )


def test_bootstrap_skips_undersized_regime_but_uses_others() -> None:
    big = _make_trades("calm", [0.01] * (MIN_TRADES_PER_REGIME + 5))
    tiny = _make_trades("vol", [99.0] * 3)
    out = regime_stratified_bootstrap(big + tiny, _mean, method="iid", B=50, seed=0)
    assert "vol" in out["skipped_regimes"]
    assert "calm" not in out["skipped_regimes"]
    # Aggregate should not be polluted by the 99.0 tail values.
    assert abs(out["statistic_observed"] - 0.01) < 1e-9


def test_bootstrap_missing_pnl_field_raises() -> None:
    trades = [{"regime_at_entry": "x"}] * MIN_TRADES_PER_REGIME
    with pytest.raises(ValueError, match="missing 'pnl'"):
        regime_stratified_bootstrap(trades, _mean, B=10)


# ---------------------------------------------------------------------------
# Permutation
# ---------------------------------------------------------------------------


def test_permutation_two_sided_p_high_for_identical_distributions() -> None:
    rng = np.random.default_rng(0)
    samples = rng.normal(0.0, 0.01, size=200).tolist()
    a = _make_trades("calm", samples[:100])
    b = _make_trades("calm", samples[100:])
    out = regime_stratified_permutation(
        a, b, _diff_means, n_permutations=200, seed=11
    )
    assert out["p_value"] > 0.10  # should NOT be significant


def test_permutation_p_low_for_clearly_different_distributions() -> None:
    rng = np.random.default_rng(0)
    a_pnls = rng.normal(0.05, 0.01, size=80).tolist()
    b_pnls = rng.normal(-0.05, 0.01, size=80).tolist()
    a = _make_trades("calm", a_pnls)
    b = _make_trades("calm", b_pnls)
    out = regime_stratified_permutation(
        a, b, _diff_means, n_permutations=300, seed=2
    )
    assert out["p_value"] < 0.05


def test_permutation_skips_regimes_with_undersized_arm() -> None:
    a = _make_trades("calm", [0.01] * MIN_TRADES_PER_REGIME) + _make_trades(
        "vol", [0.05] * 5
    )
    b = _make_trades("calm", [0.01] * MIN_TRADES_PER_REGIME) + _make_trades(
        "vol", [0.05] * MIN_TRADES_PER_REGIME
    )
    out = regime_stratified_permutation(
        a, b, _diff_means, n_permutations=100, seed=0
    )
    assert "vol" in out["skipped_regimes"]
    assert out["p_value"] is not None


def test_permutation_returns_none_when_all_regimes_skipped() -> None:
    a = _make_trades("vol", [0.01] * 5)
    b = _make_trades("vol", [0.01] * 5)
    out = regime_stratified_permutation(
        a, b, _diff_means, n_permutations=10, seed=0
    )
    assert out["p_value"] is None
    assert out["statistic_observed"] is None


def test_permutation_determinism() -> None:
    a = _make_trades("calm", [0.01 * i for i in range(60)])
    b = _make_trades("calm", [0.02 * i for i in range(60)])
    out1 = regime_stratified_permutation(a, b, _diff_means, n_permutations=50, seed=5)
    out2 = regime_stratified_permutation(a, b, _diff_means, n_permutations=50, seed=5)
    assert out1["p_value"] == out2["p_value"]
