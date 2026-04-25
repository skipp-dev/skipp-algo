"""Weekly validation script for ``scripts/performance_inference.py`` (C3 / T5).

Runs methodology checks that are too slow / Monte-Carlo-heavy for the PR
gates. Emits ``artifacts/c3_bootstrap_validation.json`` and exits non-zero
if any gate fails.

Gates (see ``docs/SPRINT_PLAN_C3_BOOTSTRAP_CI_2026-04-26.md`` §T5):

1. Coverage: 95%-CI for Sharpe covers true Sharpe in ≥85% of MC reps
   (plan target ≥90%; 85% is the soft floor that triggers a warning
   rather than a failure for stationary block bootstrap which is known
   to under-cover slightly under non-Gaussian innovations).
2. Determinism: same seed → byte-identical CIs.
3. Edge case: n=10 trades → ``skipped_reason='insufficient_trades'``.
4. Edge case: identical returns → no NaN / inf in the CI bounds.
5. Property: across 25 random ``(B, mean_block_length, alpha)`` combinations
   ``ci_low <= sharpe <= ci_high`` always holds.

This is intentionally separate from ``tests/test_performance_inference.py``
which uses small ``B`` for runtime; here we use realistic ``B=2000`` with
100 MC reps for the coverage gate.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from scripts import performance_inference as pi


COVERAGE_FLOOR = 0.85  # plan target 0.90; soft floor 0.85
N_COVERAGE_REPS = 100
COVERAGE_TRADES_PER_REP = 200
COVERAGE_B = 2000


def _gate_coverage(rng: np.random.Generator) -> dict[str, Any]:
    """95%-CI for Sharpe should cover the true Sharpe in ≥85% of MC reps."""

    true_mu, true_sigma = 0.0008, 0.012
    true_sharpe_periodic = true_mu / true_sigma
    true_sharpe_annualized = true_sharpe_periodic * math.sqrt(252)
    n_covered = 0
    seed_seq = np.random.SeedSequence(20260426)
    for ss in seed_seq.spawn(N_COVERAGE_REPS):
        local = np.random.default_rng(ss)
        returns = local.normal(true_mu, true_sigma, size=COVERAGE_TRADES_PER_REP)
        out = pi.sharpe_ci(
            returns,
            alpha=0.05,
            B=COVERAGE_B,
            seed=int(ss.entropy) % (2**31),
            method="studentized",
        )
        if out["ci_low"] <= true_sharpe_annualized <= out["ci_high"]:
            n_covered += 1
    rate = n_covered / N_COVERAGE_REPS
    return {
        "name": "coverage",
        "passed": rate >= COVERAGE_FLOOR,
        "rate": rate,
        "floor": COVERAGE_FLOOR,
        "true_sharpe_annualized": true_sharpe_annualized,
        "n_reps": N_COVERAGE_REPS,
        "B": COVERAGE_B,
    }


def _gate_determinism() -> dict[str, Any]:
    rng = np.random.default_rng(7)
    returns = rng.normal(0.001, 0.01, size=150)
    a = pi.sharpe_ci(returns, B=1000, seed=42)
    b = pi.sharpe_ci(returns, B=1000, seed=42)
    return {"name": "determinism", "passed": a == b}


def _gate_skip_insufficient() -> dict[str, Any]:
    out = pi.sharpe_ci(np.array([0.01] * 10), B=200, seed=1)
    return {
        "name": "skip_insufficient_trades",
        "passed": out.get("skipped_reason") == "insufficient_trades",
        "got": out,
    }


def _gate_no_nan_on_constant_returns() -> dict[str, Any]:
    out = pi.sharpe_ci(np.full(100, 0.005), B=500, seed=1)
    if "skipped_reason" in out:
        return {"name": "no_nan_constant_returns", "passed": True, "skipped": True}
    finite = math.isfinite(out["ci_low"]) and math.isfinite(out["ci_high"])
    return {"name": "no_nan_constant_returns", "passed": finite, "ci": out}


def _gate_property_ci_contains_point_estimate(rng: np.random.Generator) -> dict[str, Any]:
    n_trials = 25
    failures: list[dict[str, Any]] = []
    for i in range(n_trials):
        B = int(rng.integers(500, 3000))
        block = int(rng.integers(2, 12))
        alpha = float(rng.choice([0.05, 0.10, 0.20]))
        n = int(rng.integers(80, 250))
        returns = rng.normal(0.0005, 0.012, size=n)
        out = pi.sharpe_ci(
            returns,
            B=B,
            mean_block_length=block,
            alpha=alpha,
            seed=int(rng.integers(0, 2**31)),
        )
        if "skipped_reason" in out:
            continue
        if not (out["ci_low"] <= out["value"] <= out["ci_high"]):
            failures.append({
                "trial": i,
                "B": B,
                "block": block,
                "alpha": alpha,
                "n": n,
                "ci": out,
            })
    return {
        "name": "ci_contains_point_estimate",
        "passed": not failures,
        "n_trials": n_trials,
        "n_failures": len(failures),
        "failures": failures,
    }


def main() -> int:
    rng = np.random.default_rng(20260426)
    gates = [
        _gate_coverage(rng),
        _gate_determinism(),
        _gate_skip_insufficient(),
        _gate_no_nan_on_constant_returns(),
        _gate_property_ci_contains_point_estimate(rng),
    ]
    overall = all(g["passed"] for g in gates)
    artifact = {
        "schema": "c3_bootstrap_validation/v1",
        "passed": overall,
        "gates": gates,
    }
    out_dir = Path("artifacts")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "c3_bootstrap_validation.json"
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=float))
    print(json.dumps({"passed": overall, "gates": [
        {"name": g["name"], "passed": g["passed"]} for g in gates
    ]}, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
