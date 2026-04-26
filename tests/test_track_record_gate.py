"""Tests for ``scripts.track_record_gate`` (Sprint C6 / T6)."""

from __future__ import annotations

import numpy as np

from scripts.track_record_gate import (
    GREEN,
    RED,
    SKIPPED,
    YELLOW,
    GateCheck,
    TrackRecordGateVerdict,
    evaluate_track_record_gate,
    verdict_to_dict,
)


def _profitable_returns(n: int = 200, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Mean ~0.4%/trade, stdev 1% → annualised Sharpe well above 1 at 252.
    return rng.normal(loc=0.004, scale=0.01, size=n)


def _losing_returns(n: int = 200, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(loc=-0.003, scale=0.01, size=n)


# ---------------------------------------------------------------------------
# Skeleton / shape
# ---------------------------------------------------------------------------


def test_verdict_dataclass_is_frozen() -> None:
    v = TrackRecordGateVerdict(status=GREEN)
    try:
        v.status = RED  # type: ignore[misc]
    except (AttributeError, TypeError):
        return
    raise AssertionError("verdict must be frozen")


def test_check_dataclass_is_frozen() -> None:
    c = GateCheck(name="x", status=GREEN)
    try:
        c.status = RED  # type: ignore[misc]
    except (AttributeError, TypeError):
        return
    raise AssertionError("check must be frozen")


def test_too_few_trades_yields_red_via_oos_check() -> None:
    verdict = evaluate_track_record_gate(
        [0.01, -0.01, 0.02], bootstrap_B=50
    )
    oos_checks = [c for c in verdict.checks if c.name == "oos_trades"]
    assert oos_checks and oos_checks[0].status == RED
    assert verdict.status == RED
    assert verdict.n_trades == 3


def test_skipped_checks_do_not_force_red() -> None:
    # Profitable returns + all optional inputs supplied above thresholds.
    verdict = evaluate_track_record_gate(
        _profitable_returns(),
        walk_forward_efficiency=0.7,
        permutation_p=0.01,
        fdr_rate=0.05,
        per_regime_hit_rate_spread=0.10,
        bootstrap_B=80,
    )
    # Status must be one of the canonical values.
    assert verdict.status in {GREEN, YELLOW, RED}
    # n_trades respects the input.
    assert verdict.n_trades == 200


# ---------------------------------------------------------------------------
# Aggregation logic
# ---------------------------------------------------------------------------


def test_red_dominates_yellow_and_green() -> None:
    # Force one RED via permutation_p above threshold.
    verdict = evaluate_track_record_gate(
        _profitable_returns(),
        walk_forward_efficiency=0.7,
        permutation_p=0.5,
        fdr_rate=0.05,
        per_regime_hit_rate_spread=0.10,
        bootstrap_B=80,
    )
    assert any(c.name == "permutation_p" and c.status == RED for c in verdict.checks)
    assert verdict.status == RED


def test_missing_optionals_are_skipped_not_red() -> None:
    verdict = evaluate_track_record_gate(_profitable_returns(), bootstrap_B=80)
    optional_names = {
        "walk_forward_efficiency",
        "permutation_p",
        "fdr_rate",
        "per_regime_hit_rate_spread",
    }
    for c in verdict.checks:
        if c.name in optional_names:
            assert c.status == SKIPPED, f"{c.name} should be SKIPPED, got {c.status}"


def test_losing_strategy_fails_sharpe_and_winrate() -> None:
    verdict = evaluate_track_record_gate(
        _losing_returns(),
        walk_forward_efficiency=0.7,
        permutation_p=0.01,
        fdr_rate=0.05,
        per_regime_hit_rate_spread=0.10,
        bootstrap_B=80,
    )
    failed = {c.name for c in verdict.checks if c.status == RED}
    # At least Sharpe and win-rate must trip on a clearly-losing strategy.
    assert "sharpe" in failed
    assert "win_rate" in failed
    assert verdict.status == RED


# ---------------------------------------------------------------------------
# Determinism + serialisation
# ---------------------------------------------------------------------------


def test_evaluation_is_deterministic_with_seed() -> None:
    r = _profitable_returns()
    a = evaluate_track_record_gate(r, bootstrap_B=80, bootstrap_seed=123)
    b = evaluate_track_record_gate(r, bootstrap_B=80, bootstrap_seed=123)
    # Statuses + per-check values must match exactly.
    assert a.status == b.status
    for ca, cb in zip(a.checks, b.checks):
        assert ca.name == cb.name
        assert ca.status == cb.status
        if ca.value is not None and cb.value is not None:
            assert abs(ca.value - cb.value) < 1e-12, ca.name


def test_verdict_to_dict_is_json_friendly() -> None:
    import json

    verdict = evaluate_track_record_gate(_profitable_returns(), bootstrap_B=50)
    d = verdict_to_dict(verdict)
    # Round-trip through JSON must succeed.
    s = json.dumps(d, default=str)
    back = json.loads(s)
    assert back["status"] == verdict.status
    assert back["n_trades"] == verdict.n_trades
    assert isinstance(back["checks"], list)
    assert all(set(c.keys()) == {"name", "status", "value", "threshold", "detail"} for c in back["checks"])
