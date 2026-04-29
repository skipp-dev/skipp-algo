"""Tests for ``scripts/strategy_permutation.py`` (Sprint C4 / T2).

Coverage targets per ``docs/SPRINT_PLAN_C4_PERMUTATION_TEST_2026-04-26.md``:

- determinism (same seed -> identical p-values)
- power: synthetic strategy with real edge -> p < 0.05 in >= 70% of MC reps
  (plan target 80%; reduced for unit-test runtime)
- type-I error: random returns -> p < 0.05 in <= 8% of MC reps (~alpha=0.05)
- skip behaviour for n < min_events
- BH-FDR aggregation across multiple setups
- Phipson-Smyth correction never produces exactly 0 or 1
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts import strategy_permutation as sp

# ---------------------------------------------------------------------------
# Determinism + schema
# ---------------------------------------------------------------------------


def test_sharpe_test_schema_and_determinism() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=200)
    a = sp.permutation_test_sharpe(returns, B=500, seed=42)
    b = sp.permutation_test_sharpe(returns, B=500, seed=42)
    assert a == b
    assert a["metric"] == "sharpe"
    assert a["schema"] == "outcome_sign"
    assert 0.0 < a["p_value_one_sided"] < 1.0
    assert 0.0 < a["p_value_two_sided"] <= 1.0


def test_profit_factor_test_schema_and_determinism() -> None:
    rng = np.random.default_rng(0)
    pnl = rng.normal(0.0005, 0.01, size=200)
    a = sp.permutation_test_profit_factor(pnl, B=500, seed=42)
    b = sp.permutation_test_profit_factor(pnl, B=500, seed=42)
    assert a == b
    assert 0.0 < a["p_value_one_sided"] <= 1.0


# ---------------------------------------------------------------------------
# Skip behaviour + validation
# ---------------------------------------------------------------------------


def test_sharpe_test_skips_below_min_events() -> None:
    out = sp.permutation_test_sharpe(np.array([0.01] * 10), B=200, seed=1)
    assert out["skipped_reason"] == "insufficient_trades"


def test_profit_factor_test_skips_below_min_events() -> None:
    out = sp.permutation_test_profit_factor(np.array([0.01] * 10), B=200, seed=1)
    assert out["skipped_reason"] == "insufficient_trades"


def test_unknown_schema_rejected() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=80)
    # 'entry_time' was the legacy placeholder for the (now-shipped) Schema B;
    # it is not a valid schema name. Schema B is exposed as
    # 'block_outcome_sign' (Deep-Review 2026-04-27 follow-up).
    with pytest.raises(ValueError, match=r"not supported|not implemented"):
        sp.permutation_test_sharpe(returns, schema="entry_time", B=100, seed=1)  # type: ignore[arg-type]


def test_schema_b_block_outcome_sign_supported() -> None:
    """Schema B (block sign-flip) preserves trade-stream autocorrelation
    under the null. Deep-Review 2026-04-27 follow-up: lifts the prior
    xfail by routing the previously-deferred entry-time-permutation
    placeholder through the autocorrelation-aware block sign-flip
    primitive (conceptual companion to
    :func:`smc_core.inference.permutation.block_permutation_test`).
    """
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=80)
    out = sp.permutation_test_sharpe(
        returns, schema="block_outcome_sign", B=200, seed=1, block_size=5,
    )
    assert out["schema"] == "block_outcome_sign"
    assert out["block_size"] == 5
    assert "p_value_one_sided" in out
    assert 0.0 < float(out["p_value_one_sided"]) <= 1.0


def test_schema_b_block_size_one_matches_schema_a() -> None:
    """block_size=1 reduces Schema B to Schema A exactly
    (verifies the dispatch fallback)."""
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=80)
    a = sp.permutation_test_sharpe(returns, schema="outcome_sign", B=200, seed=42)
    b = sp.permutation_test_sharpe(
        returns, schema="block_outcome_sign", B=200, seed=42, block_size=1,
    )
    # Same RNG seed + same per-element distribution -> bit-identical p-values.
    assert a["p_value_one_sided"] == b["p_value_one_sided"]
    assert a["p_value_two_sided"] == b["p_value_two_sided"]


# ---------------------------------------------------------------------------
# Phipson-Smyth correction guarantees
# ---------------------------------------------------------------------------


def test_phipson_smyth_never_zero() -> None:
    """Even an extreme observed value gets the (r+1)/(B+1) floor."""

    # Construct returns whose Sharpe sits well outside any sign-flip null.
    returns = np.full(100, 0.01)
    out = sp.permutation_test_sharpe(returns, B=200, seed=1)
    assert out["p_value_one_sided"] >= 1.0 / (200 + 1)
    # No exact 0.0 — Phipson-Smyth floor (1/(B+1)) is the minimum.
    assert out["p_value_one_sided"] > 0.0


# ---------------------------------------------------------------------------
# Power test (truncated for runtime)
# ---------------------------------------------------------------------------


def test_power_against_strong_edge_at_least_70pct() -> None:
    """Strategy with mean=2*sigma -> Sharpe>>0; should reject often.

    Plan target: 80% rejection at alpha=0.05 over 100 reps. We use 30
    reps + a slightly relaxed 70% threshold to keep this unit test
    inside the 5s budget. The full 100-rep power test runs in the
    weekly cron (T5).
    """

    n_reps = 30
    n_rejected = 0
    seed_seq = np.random.SeedSequence(2026_04_26)
    for ss in seed_seq.spawn(n_reps):
        rng = np.random.default_rng(ss)
        returns = rng.normal(loc=0.005, scale=0.005, size=120)
        out = sp.permutation_test_sharpe(returns, B=400, seed=int(ss.entropy) % (2**31))
        if out["p_value_one_sided"] < 0.05:
            n_rejected += 1
    rate = n_rejected / n_reps
    assert rate >= 0.70, f"power {rate:.2%} below 70% threshold"


def test_type_i_error_at_most_15pct() -> None:
    """Pure-noise (mean=0) returns should reject at ~alpha=0.05.

    Plan target ≤6% over 100 reps. We use 30 reps + a relaxed 15% upper
    bound for runtime / sampling-noise; the strict bound is enforced in
    the weekly cron (T5).
    """

    n_reps = 30
    n_rejected = 0
    seed_seq = np.random.SeedSequence(2026_04_27)
    for ss in seed_seq.spawn(n_reps):
        rng = np.random.default_rng(ss)
        returns = rng.normal(loc=0.0, scale=0.01, size=120)
        out = sp.permutation_test_sharpe(returns, B=400, seed=int(ss.entropy) % (2**31))
        if out["p_value_one_sided"] < 0.05:
            n_rejected += 1
    rate = n_rejected / n_reps
    assert rate <= 0.15, f"type-I error {rate:.2%} above 15% threshold"


# ---------------------------------------------------------------------------
# BH-FDR aggregation
# ---------------------------------------------------------------------------


def test_aggregate_permutation_results_basic() -> None:
    setup_results = {
        "smc_fvg_strict": {"p_value_one_sided": 0.001, "value": 1.5},
        "smc_fvg_quality": {"p_value_one_sided": 0.04, "value": 1.1},
        "smc_zone_priority_a": {"p_value_one_sided": 0.20, "value": 0.6},
        "smc_zone_priority_b": {"p_value_one_sided": 0.50, "value": 0.3},
        "smc_orderblock": {"p_value_one_sided": 0.85, "value": -0.2},
    }
    agg = sp.aggregate_permutation_results(setup_results, q=0.10)
    assert agg["aggregate"]["n_tested"] == 5
    # Per-setup augmentation
    for name in setup_results:
        assert "bh_adjusted_p" in agg["per_setup"][name]
        assert "bh_rejects_h0" in agg["per_setup"][name]
        assert agg["per_setup"][name]["fdr_q"] == 0.10
    # The smallest p-value must be rejected.
    assert agg["per_setup"]["smc_fvg_strict"]["bh_rejects_h0"] is True


def test_aggregate_skips_setups_with_skipped_reason() -> None:
    setup_results = {
        "good": {"p_value_one_sided": 0.001, "value": 1.5},
        "skipped": {"skipped_reason": "insufficient_trades", "n": 10},
    }
    agg = sp.aggregate_permutation_results(setup_results, q=0.10)
    assert agg["aggregate"]["n_tested"] == 1
    assert "bh_adjusted_p" in agg["per_setup"]["good"]
    assert "bh_adjusted_p" not in agg["per_setup"]["skipped"]


def test_aggregate_all_skipped() -> None:
    setup_results = {
        "a": {"skipped_reason": "insufficient_trades", "n": 5},
        "b": {"skipped_reason": "insufficient_trades", "n": 8},
    }
    agg = sp.aggregate_permutation_results(setup_results, q=0.10)
    assert agg["aggregate"]["n_tested"] == 0
    assert agg["aggregate"]["skipped_reason"] == "no_eligible_setups"
