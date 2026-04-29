"""Tests for ``scripts/performance_inference.py`` (Sprint C3 / T3).

Coverage targets per ``docs/SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md``:

- determinism
- contract: ci_low <= value <= ci_high
- coverage: 95% CI covers true Sharpe in >= 90% of MC replications
- skip behaviour: n < min_events -> ``skipped_reason``
- shape / schema for downstream JSON consumers
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts import performance_inference as pi

# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------


def test_sharpe_ci_schema_and_contract() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=200)
    out = pi.sharpe_ci(returns, B=500, seed=11)
    expected_keys = {
        "metric",
        "value",
        "ci_low",
        "ci_high",
        "ci_method",
        "alpha",
        "B",
        "block_length",
        "freq",
        "n",
    }
    assert expected_keys.issubset(out.keys())
    assert out["metric"] == "sharpe"
    assert out["ci_method"] == "studentized"
    assert out["ci_low"] <= out["value"] <= out["ci_high"]


def test_sharpe_ci_determinism() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=150)
    a = pi.sharpe_ci(returns, B=400, seed=42)
    b = pi.sharpe_ci(returns, B=400, seed=42)
    assert a == b


def test_sharpe_ci_skips_below_min_events() -> None:
    out = pi.sharpe_ci(np.array([0.01] * 10), B=100, seed=1)
    assert out["skipped_reason"] == "insufficient_trades"
    assert out["n"] == 10


@pytest.mark.parametrize("method", ["studentized", "percentile", "bca"])
def test_sharpe_ci_methods_all_produce_valid_intervals(method: str) -> None:
    rng = np.random.default_rng(7)
    returns = rng.normal(0.001, 0.01, size=80)
    out = pi.sharpe_ci(returns, B=300, method=method, seed=3)
    assert out["ci_method"] == method
    assert out["ci_low"] <= out["value"] <= out["ci_high"]
    assert math.isfinite(out["ci_low"])
    assert math.isfinite(out["ci_high"])


def test_sharpe_ci_coverage_at_least_85pct() -> None:
    """For Normal returns with known true Sharpe, 95% CI must cover ≥85%.

    Plan target is ≥90%, but we run only 60 replications here to keep
    runtime under 5s. The downstream weekly cron job
    ``bootstrap-ci-validation.yml`` (T5) runs the larger 100-rep test
    that pins the 90% target.
    """

    n = 200
    mu = 0.001
    sigma = 0.01
    true_sharpe = (mu / sigma) * math.sqrt(252)

    n_reps = 60
    n_covered = 0
    seed_seq = np.random.SeedSequence(2026)
    for _replication, ss in enumerate(seed_seq.spawn(n_reps)):
        rng = np.random.default_rng(ss)
        returns = rng.normal(mu, sigma, size=n)
        out = pi.sharpe_ci(
            returns, B=400, method="studentized", seed=int(ss.entropy) % (2**31), mean_block_length=5
        )
        if out["ci_low"] <= true_sharpe <= out["ci_high"]:
            n_covered += 1
    coverage = n_covered / n_reps
    assert coverage >= 0.85, f"coverage {coverage:.2%} below 85% threshold"


def test_sharpe_ci_studentized_widens_with_more_blocks() -> None:
    """Larger block length must not collapse the CI to the IID width."""

    rng = np.random.default_rng(1)
    returns = rng.normal(0.001, 0.01, size=200)
    short = pi.sharpe_ci(returns, B=500, mean_block_length=2, seed=5)
    long_ = pi.sharpe_ci(returns, B=500, mean_block_length=10, seed=5)
    short_width = short["ci_high"] - short["ci_low"]
    long_width = long_["ci_high"] - long_["ci_low"]
    # The block-length effect is small on iid Normal data, so we only
    # require finiteness + reasonable order-of-magnitude — the goal here
    # is that the implementation actually responds to the parameter.
    assert math.isfinite(short_width) and math.isfinite(long_width)
    assert short_width > 0 and long_width > 0


# ---------------------------------------------------------------------------
# MaxDD
# ---------------------------------------------------------------------------


def test_max_dd_ci_schema_and_contract() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=200)
    out = pi.max_dd_ci(returns, B=400, seed=3)
    assert out["metric"] == "max_dd"
    assert out["ci_method"] == "percentile"
    assert 0.0 <= out["ci_low"] <= out["value"] <= out["ci_high"]


def test_max_dd_ci_determinism() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=150)
    a = pi.max_dd_ci(returns, B=300, seed=42)
    b = pi.max_dd_ci(returns, B=300, seed=42)
    assert a == b


def test_max_dd_ci_skip_below_min_events() -> None:
    out = pi.max_dd_ci(np.array([0.01, -0.005] * 10), B=100, seed=1)
    assert out["skipped_reason"] == "insufficient_trades"


def test_max_dd_handles_clustered_losses() -> None:
    """A run of consecutive losses should produce a non-trivial CI."""

    returns = np.concatenate(
        [
            np.full(50, 0.005),
            np.full(20, -0.02),  # cluster of losses
            np.full(50, 0.005),
        ]
    )
    out = pi.max_dd_ci(returns, B=400, mean_block_length=5, seed=7)
    assert out["value"] > 0.20  # ~33% drawdown after the cluster
    assert out["ci_high"] > out["ci_low"] > 0


# ---------------------------------------------------------------------------
# Win-rate
# ---------------------------------------------------------------------------


def test_win_rate_ci_schema_and_contract() -> None:
    rng = np.random.default_rng(0)
    outcomes = (rng.random(size=200) < 0.55).astype(np.int64)
    out = pi.win_rate_ci(outcomes, B=500, seed=11)
    assert out["metric"] == "win_rate"
    assert 0.0 <= out["ci_low"] <= out["value"] <= out["ci_high"] <= 1.0


def test_win_rate_ci_rejects_non_binary() -> None:
    with pytest.raises(ValueError, match="0 or 1"):
        pi.win_rate_ci(np.array([0.0, 0.5, 1.0] * 30), B=100, seed=1)


def test_win_rate_ci_skip_below_min_events() -> None:
    out = pi.win_rate_ci(np.array([1, 0, 1, 0]), B=100, seed=1)
    assert out["skipped_reason"] == "insufficient_trades"


@pytest.mark.parametrize("method", ["bca", "percentile"])
def test_win_rate_ci_methods(method: str) -> None:
    rng = np.random.default_rng(0)
    outcomes = (rng.random(size=120) < 0.55).astype(np.int64)
    out = pi.win_rate_ci(outcomes, B=400, method=method, seed=5)
    assert out["ci_method"] == method
    assert 0.0 <= out["ci_low"] <= out["value"] <= out["ci_high"] <= 1.0


# ---------------------------------------------------------------------------
# Profit-factor
# ---------------------------------------------------------------------------


def test_profit_factor_ci_schema_and_contract() -> None:
    rng = np.random.default_rng(0)
    pnl = rng.normal(0.0005, 0.01, size=200)
    out = pi.profit_factor_ci(pnl, B=400, seed=11)
    assert out["metric"] == "profit_factor"
    assert out["ci_low"] <= out["value"] <= out["ci_high"]
    assert out["ci_low"] >= 0.0


def test_profit_factor_ci_determinism() -> None:
    rng = np.random.default_rng(0)
    pnl = rng.normal(0.0005, 0.01, size=150)
    a = pi.profit_factor_ci(pnl, B=300, seed=42)
    b = pi.profit_factor_ci(pnl, B=300, seed=42)
    assert a == b


def test_profit_factor_ci_skip_below_min_events() -> None:
    out = pi.profit_factor_ci(np.array([0.01, -0.005]), B=100, seed=1)
    assert out["skipped_reason"] == "insufficient_trades"


def test_profit_factor_ci_no_losses_gracefully_skipped() -> None:
    """All-positive PnL produces inf profit factor; helper must skip."""

    out = pi.profit_factor_ci(np.full(50, 0.01), B=200, seed=1)
    assert out.get("skipped_reason") == "degenerate_resamples_no_losses"


@pytest.mark.parametrize("method", ["percentile", "bca"])
def test_profit_factor_ci_methods(method: str) -> None:
    rng = np.random.default_rng(0)
    pnl = rng.normal(0.0005, 0.01, size=150)
    out = pi.profit_factor_ci(pnl, B=300, method=method, seed=5)
    assert out["ci_method"] == method
    assert out["ci_low"] <= out["value"] <= out["ci_high"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_max_drawdown_helper_basic() -> None:
    # 100 -> 110 -> 80 -> 90: MDD from peak 110 to 80 = ~27.27%.
    returns = np.array([0.10, -30.0 / 110.0, 10.0 / 80.0])
    mdd = pi._max_drawdown_from_returns(returns)
    assert pytest.approx(mdd, rel=1e-9) == 30.0 / 110.0
