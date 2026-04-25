"""Weekly validation script for ``scripts/strategy_permutation.py`` (C4 / T5).

Runs the full Monte-Carlo gates that are too slow for the PR test gate.
Emits ``artifacts/c4_permutation_validation.json``.

Gates (see ``docs/SPRINT_PLAN_C4_PERMUTATION_TEST_2026-04-26.md`` §T5):

1. Power: synthetic edge → p < 0.05 in ≥80% of 100 reps.
2. Type-I error: noise → p < 0.05 in ≤6% of 100 reps (one-sided).
3. Determinism: same seed → identical p-values.
4. Skip below MIN_EVENTS_FOR_BOOTSTRAP.
5. Property: ``0.0 < p_value < 1.0`` (Phipson-Smyth floor) across 50
   random ``(B, schema)`` combinations.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from scripts import strategy_permutation as sp


N_POWER_REPS = 100
N_TYPE1_REPS = 100
PERM_B = 1000
POWER_FLOOR = 0.80
TYPE1_CEILING = 0.06


def _gate_power() -> dict[str, Any]:
    n_rejected = 0
    seed_seq = np.random.SeedSequence(20260426)
    for ss in seed_seq.spawn(N_POWER_REPS):
        rng = np.random.default_rng(ss)
        # Synthetic edge: positive drift ~0.5 sigma → Sharpe ≈ 0.5/sqrt-trade
        returns = rng.normal(loc=0.005, scale=0.010, size=120)
        out = sp.permutation_test_sharpe(returns, B=PERM_B, seed=int(ss.entropy) % (2**31))
        if out.get("p_value_one_sided", 1.0) < 0.05:
            n_rejected += 1
    rate = n_rejected / N_POWER_REPS
    return {
        "name": "power",
        "passed": rate >= POWER_FLOOR,
        "rate": rate,
        "floor": POWER_FLOOR,
        "n_reps": N_POWER_REPS,
        "B": PERM_B,
    }


def _gate_type_i_error() -> dict[str, Any]:
    n_rejected = 0
    seed_seq = np.random.SeedSequence(20260427)
    for ss in seed_seq.spawn(N_TYPE1_REPS):
        rng = np.random.default_rng(ss)
        returns = rng.normal(loc=0.0, scale=0.010, size=120)
        out = sp.permutation_test_sharpe(returns, B=PERM_B, seed=int(ss.entropy) % (2**31))
        if out.get("p_value_one_sided", 1.0) < 0.05:
            n_rejected += 1
    rate = n_rejected / N_TYPE1_REPS
    # Allow a small finite-sample tolerance over the nominal alpha=0.05.
    return {
        "name": "type_i_error",
        "passed": rate <= TYPE1_CEILING,
        "rate": rate,
        "ceiling": TYPE1_CEILING,
        "n_reps": N_TYPE1_REPS,
        "B": PERM_B,
    }


def _gate_determinism() -> dict[str, Any]:
    rng = np.random.default_rng(11)
    returns = rng.normal(0.001, 0.01, size=150)
    a = sp.permutation_test_sharpe(returns, B=500, seed=42)
    b = sp.permutation_test_sharpe(returns, B=500, seed=42)
    return {"name": "determinism", "passed": a == b}


def _gate_skip_insufficient() -> dict[str, Any]:
    out = sp.permutation_test_sharpe(np.array([0.01] * 10), B=200, seed=1)
    return {
        "name": "skip_insufficient_trades",
        "passed": out.get("skipped_reason") == "insufficient_trades",
        "got": out,
    }


def _gate_phipson_smyth_bounds(rng: np.random.Generator) -> dict[str, Any]:
    n_trials = 50
    failures: list[dict[str, Any]] = []
    for i in range(n_trials):
        B = int(rng.integers(200, 2000))
        n = int(rng.integers(40, 250))
        returns = rng.normal(0.0005, 0.012, size=n)
        out = sp.permutation_test_sharpe(returns, B=B, seed=int(rng.integers(0, 2**31)))
        if "skipped_reason" in out:
            continue
        p1 = out["p_value_one_sided"]
        p2 = out["p_value_two_sided"]
        floor = 1.0 / (B + 1)
        if not (floor <= p1 <= 1.0 and floor <= p2 <= 1.0):
            failures.append({"trial": i, "B": B, "n": n, "p1": p1, "p2": p2, "floor": floor})
    return {
        "name": "phipson_smyth_bounds",
        "passed": not failures,
        "n_trials": n_trials,
        "n_failures": len(failures),
        "failures": failures,
    }


def main() -> int:
    rng = np.random.default_rng(20260426)
    gates = [
        _gate_power(),
        _gate_type_i_error(),
        _gate_determinism(),
        _gate_skip_insufficient(),
        _gate_phipson_smyth_bounds(rng),
    ]
    overall = all(g["passed"] for g in gates)
    artifact = {
        "schema": "c4_permutation_validation/v1",
        "passed": overall,
        "gates": gates,
    }
    out_dir = Path("artifacts")
    out_dir.mkdir(exist_ok=True)
    (out_dir / "c4_permutation_validation.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True, default=float)
    )
    print(json.dumps({"passed": overall, "gates": [
        {"name": g["name"], "passed": g["passed"]} for g in gates
    ]}, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
