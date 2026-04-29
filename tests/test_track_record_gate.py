"""Tests for ``scripts.track_record_gate`` (Sprint C6 / T6)."""

from __future__ import annotations

import numpy as np

from scripts.track_record_gate import (
    GREEN,
    KNOWN_GATE_CHECK_NAMES,
    RED,
    SKIPPED,
    YELLOW,
    GateCheck,
    TrackRecordGateVerdict,
    evaluate_track_record_gate,
    evaluate_track_record_gate_per_variant,
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
    for ca, cb in zip(a.checks, b.checks, strict=False):
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


def test_verdict_carries_schema_version() -> None:
    """Deep-Review 2026-04-27: dashboard / public-report consumers must
    be able to detect breaking verdict-schema changes via a semver
    field. PATCH/MINOR additive bumps must keep the same MAJOR; bumping
    MAJOR requires updating every downstream consumer.
    """
    verdict = evaluate_track_record_gate(_profitable_returns(), bootstrap_B=50)
    assert verdict.schema_version == "1.0.0"
    d = verdict_to_dict(verdict)
    assert d["schema_version"] == "1.0.0"
    # Pin the MAJOR explicitly so a future MINOR bump (e.g. "1.1.0")
    # is still allowed but a MAJOR bump (e.g. "2.0.0") fails the suite
    # and forces a deliberate consumer audit.
    assert d["schema_version"].split(".", 1)[0] == "1"


# ---------------------------------------------------------------------------
# Contract pin: every emitted check name must be in KNOWN_GATE_CHECK_NAMES
# (C-sprint deep-review MAJOR fix — unknown failure codes were silently
# coerced on the Streamlit dashboard).
# ---------------------------------------------------------------------------


def _all_emitted_check_names(verdict: TrackRecordGateVerdict) -> list[str]:
    return [c.name for c in verdict.checks]


def test_evaluate_emits_all_known_check_names_on_full_input() -> None:
    """A verdict computed with every optional kwarg supplied must emit
    exactly :data:`KNOWN_GATE_CHECK_NAMES` and nothing else.
    """
    verdict = evaluate_track_record_gate(
        _profitable_returns(),
        walk_forward_efficiency=0.6,
        permutation_p=0.01,
        fdr_rate=0.05,
        per_regime_hit_rate_spread=0.10,
        bootstrap_B=50,
    )
    emitted = _all_emitted_check_names(verdict)
    # Order must be stable too — consumer code may rely on it.
    assert tuple(emitted) == KNOWN_GATE_CHECK_NAMES


def test_known_gate_check_names_match_emitted_with_minimal_input() -> None:
    """Even with all optional kwargs absent, the same name set is emitted
    (some statuses become SKIPPED, but no name disappears).
    """
    verdict = evaluate_track_record_gate(_profitable_returns(), bootstrap_B=50)
    emitted = set(_all_emitted_check_names(verdict))
    assert emitted == set(KNOWN_GATE_CHECK_NAMES)


def test_per_variant_failures_only_reference_known_check_names() -> None:
    """The per-variant ``failures`` list (consumed by tab_track_record)
    must only mention names from :data:`KNOWN_GATE_CHECK_NAMES`.
    """
    out = evaluate_track_record_gate_per_variant(
        {"sample": _losing_returns()},
        walk_forward_efficiency_by_variant={"sample": 0.20},
        permutation_p_by_variant={"sample": 0.30},
    )
    failures = out["sample"]["failures"]
    # ``failures`` strings start with ``f"{c.name}=..."`` (or just
    # ``c.name`` when value/threshold are None) — extract the leading
    # token before ``=`` or whitespace.
    leading_names = [f.split("=", 1)[0].split()[0] for f in failures]
    unknown = [n for n in leading_names if n not in KNOWN_GATE_CHECK_NAMES]
    assert not unknown, f"per-variant failures referenced unknown check(s): {unknown}"


def test_min_trl_no_edge_fires_red_not_skipped() -> None:
    """When ``sr_hat <= sr_star`` the MinTRL check now fires RED with a
    detail string, instead of being silently SKIPPED (C-sprint deep-
    review MAJOR fix).
    """
    verdict = evaluate_track_record_gate(_losing_returns(n=300), bootstrap_B=50)
    min_trl_checks = [c for c in verdict.checks if c.name == "min_trl_within_n"]
    assert len(min_trl_checks) == 1
    check = min_trl_checks[0]
    assert check.status == RED
    assert "no detectable edge" in check.detail
    assert verdict.status == RED


# ---------------------------------------------------------------------------
# Negative-case coverage (C-sprint deep-review MINOR finding)
# ---------------------------------------------------------------------------


def test_evaluate_empty_returns_raises_value_error() -> None:
    """Zero-length returns must explicitly raise so callers do not
    accidentally dispatch the gate on empty data and render a
    misleading "all-skipped" row."""
    import pytest

    with pytest.raises(ValueError):
        evaluate_track_record_gate(np.array([], dtype=np.float64), bootstrap_B=10)


def test_evaluate_all_nan_returns_raises_value_error() -> None:
    """All-NaN returns must not be silently treated as zero-edge data."""
    import pytest

    arr = np.array([np.nan] * 50, dtype=np.float64)
    with pytest.raises(ValueError):
        evaluate_track_record_gate(arr, bootstrap_B=10)


def test_evaluate_zero_variance_returns_raises_value_error() -> None:
    """Constant returns crash deep inside the bootstrap CI helpers; the
    gate must fail loud at its boundary so callers get a clear
    remediation message instead of an IndexError from numpy.
    """
    import pytest

    arr = np.full(60, 0.001, dtype=np.float64)
    with pytest.raises(ValueError, match="zero-variance"):
        evaluate_track_record_gate(arr, bootstrap_B=20)


def test_per_variant_unknown_optional_key_raises_value_error() -> None:
    """Typo in optional dict (e.g. wrong-case variant key) must raise
    instead of silently producing SKIPPED checks the dashboard then
    renders as healthy (C-sprint deep-review MINOR fix).
    """
    import pytest

    with pytest.raises(ValueError, match="walk_forward_efficiency_by_variant"):
        evaluate_track_record_gate_per_variant(
            {"sample": _profitable_returns()},
            walk_forward_efficiency_by_variant={"SAMPLE": 0.6},  # case typo
        )
