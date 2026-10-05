"""Tests for ``scripts.track_record_gate`` (Sprint C6 / T6)."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.track_record_gate import (
    GREEN,
    KNOWN_GATE_CHECK_NAMES,
    MIN_TRADING_DAYS,
    RED,
    REQUIRED_CLAIM_EVIDENCE,
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


_DAY = 86_400.0
_FIRST_DAY = 1_788_220_800.0  # 2026-09-01T00:00:00Z


def _anchors(n: int, *, days: int) -> list[float]:
    """``n`` anchors dealt round-robin over ``days`` consecutive UTC days."""
    return [_FIRST_DAY + (i % days) * _DAY + 52_200.0 for i in range(n)]


def _check_named(verdict: TrackRecordGateVerdict, name: str) -> GateCheck:
    found = [c for c in verdict.checks if c.name == name]
    assert len(found) == 1, f"expected exactly one {name} check, got {len(found)}"
    return found[0]


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
    assert verdict.checks, "the gate emitted no checks at all — the loop below would pass vacuously"
    optional_seen = optional_names & {c.name for c in verdict.checks}
    assert optional_seen == optional_names, (
        "the verdict does not carry every optional check, so the SKIPPED "
        f"assertion below never runs for: {sorted(optional_names - optional_seen)}"
    )
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


def test_red_verdict_says_its_green_checks_are_not_claims() -> None:
    """2026-08-16 (weekly review P2): the raw JSON is the rendering surface.

    A red gate with green sub-checks (Sharpe 9.44 on 33 trades) must carry
    the disclaimer itself — the claim_note names every red check so a
    reader of the dated gate artifact sees WHY the greens do not count.
    """
    verdict = evaluate_track_record_gate([0.5] * 5 + [-0.5], bootstrap_B=50)
    d = verdict_to_dict(verdict)

    assert d["status"] == "red"
    assert d["claimable"] is False
    assert "not claimable evidence" in d["claim_note"]
    for check in d["checks"]:
        if check["status"] == "red":
            assert check["name"] in d["claim_note"]


def test_green_without_required_evidence_is_not_claimable() -> None:
    """2026-08-18 (Verdrahtungs-Sweep K4): kein Producer im Repo liefert
    walk_forward_efficiency/fdr_rate/per_regime_hit_rate_spread, und das
    Aggregat ignoriert SKIPPED — ein gruenes Gate darf mit drei nie
    gemessenen Pflicht-Pruefungen nicht claimable werden. Die claim_note
    benennt, was fehlt. (Ersetzt den frueheren Test, der genau dieses Loch
    als Erwartung pinnte.)"""
    verdict = evaluate_track_record_gate(_profitable_returns(), bootstrap_B=50)
    d = verdict_to_dict(verdict)

    assert d["status"] == "green"
    assert d["claimable"] is False
    for name in (
        "walk_forward_efficiency",
        "fdr_rate",
        "per_regime_hit_rate_spread",
    ):
        assert name in d["claim_note"], name


def test_green_with_measured_required_evidence_is_claimable() -> None:
    # permutation_p bleibt bewusst weg: advisory by design (Schema-B-Caveat)
    # — ein fehlendes Advisory blockt die Claim nicht.
    verdict = evaluate_track_record_gate(
        _profitable_returns(),
        anchor_ts=_anchors(200, days=40),
        walk_forward_efficiency=0.7,
        fdr_rate=0.05,
        per_regime_hit_rate_spread=0.10,
        bootstrap_B=50,
    )
    d = verdict_to_dict(verdict)

    assert d["status"] == "green"
    assert d["claimable"] is True
    assert d["claim_note"] is None


def test_verdict_carries_schema_version() -> None:
    """Deep-Review 2026-04-27: dashboard / public-report consumers must
    be able to detect breaking verdict-schema changes via a semver
    field. PATCH/MINOR additive bumps must keep the same MAJOR; bumping
    MAJOR requires updating every downstream consumer.
    """
    verdict = evaluate_track_record_gate(_profitable_returns(), bootstrap_B=50)
    assert verdict.schema_version == "1.1.0"
    d = verdict_to_dict(verdict)
    assert d["schema_version"] == "1.1.0"
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
        anchor_ts=_anchors(200, days=40),
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


# --- Stat-review S4 (#2674): Sharpe annualisation on the trade clock ---


def _sharpe_check(verdict):
    return next(c for c in verdict.checks if c.name == "sharpe")


def test_trades_per_year_rescales_sharpe_and_is_disclosed() -> None:
    import pytest

    r = _profitable_returns()
    base = evaluate_track_record_gate(r, bootstrap_B=80)
    scaled = evaluate_track_record_gate(r, trades_per_year=63.0, bootstrap_B=80)
    c_base, c_scaled = _sharpe_check(base), _sharpe_check(scaled)
    # Annualised Sharpe scales with sqrt(freq): 63 = 252/4 -> exactly half.
    assert c_scaled.value == pytest.approx(c_base.value * 0.5, rel=1e-9)
    assert "observed trades/year" in c_scaled.detail
    assert "63" in c_scaled.detail


def test_default_freq_disclosure_names_the_daily_bar_assumption() -> None:
    verdict = evaluate_track_record_gate(_profitable_returns(), bootstrap_B=80)
    detail = _sharpe_check(verdict).detail
    assert "freq=252" in detail
    assert "daily-bar assumption" in detail
    assert "trades_per_year" in detail


def test_non_positive_trades_per_year_falls_back_to_default() -> None:
    r = _profitable_returns()
    base = evaluate_track_record_gate(r, bootstrap_B=80)
    fallback = evaluate_track_record_gate(r, trades_per_year=0.0, bootstrap_B=80)
    assert _sharpe_check(fallback).value == _sharpe_check(base).value
    assert "daily-bar assumption" in _sharpe_check(fallback).detail


def test_per_variant_forwards_trades_per_year() -> None:
    r = _profitable_returns()
    out = evaluate_track_record_gate_per_variant(
        {"v1": r}, trades_per_year=63.0, bootstrap_B=80
    )
    checks = {c["name"]: c for c in out["v1"]["checks"]}
    assert "observed trades/year" in checks["sharpe"]["detail"]


# ---------------------------------------------------------------------------
# Day checks (ADR-0031, Nachtrag 2026-10-02): the day is the unit, not the trade
# ---------------------------------------------------------------------------


def test_many_trades_from_one_day_cannot_turn_green() -> None:
    """The reading of 2026-10-02: 210 SWEEP trades, all anchored on one day,
    with every trade-level check green. One day is one draw."""
    returns = _profitable_returns()
    trade_level = evaluate_track_record_gate(returns, bootstrap_B=50)
    assert trade_level.status == GREEN, "the fixture must be green on trade counts alone"

    verdict = evaluate_track_record_gate(returns, anchor_ts=_anchors(200, days=1), bootstrap_B=50)

    days = _check_named(verdict, "trading_days")
    assert (days.status, days.value, days.threshold) == (RED, 1.0, float(MIN_TRADING_DAYS))
    assert "200 trades on one day" in days.detail
    assert _check_named(verdict, "day_clustered_mean_ci_low").status == SKIPPED
    assert verdict.status == RED
    assert verdict.summary["day_clustered"]["ci_low"] is None


def test_the_day_threshold_is_inclusive_at_thirty() -> None:
    returns = _profitable_returns(n=300)
    below = evaluate_track_record_gate(returns, anchor_ts=_anchors(300, days=MIN_TRADING_DAYS - 1), bootstrap_B=50)
    at = evaluate_track_record_gate(returns, anchor_ts=_anchors(300, days=MIN_TRADING_DAYS), bootstrap_B=50)
    assert _check_named(below, "trading_days").status == RED
    assert _check_named(at, "trading_days").status == GREEN
    assert MIN_TRADING_DAYS == 30


def test_trades_that_move_together_within_a_day_do_not_pass_the_day_interval() -> None:
    """Forty days, fifty trades each. Every trade of a day shares the day's
    move; half the days are up 2 %, half down 1.9 %. Trade by trade that is
    2 000 observations with a positive mean; day by day it is a coin flip."""
    rng = np.random.default_rng(11)
    day_move = np.array([0.02, -0.019] * 20)
    returns = np.repeat(day_move, 50) + rng.normal(0.0, 0.0005, size=2000)
    anchors = np.repeat(_FIRST_DAY + np.arange(40) * _DAY, 50) + 52_200.0

    verdict = evaluate_track_record_gate(returns, anchor_ts=anchors, bootstrap_B=50)

    assert _check_named(verdict, "trading_days").status == GREEN
    interval = _check_named(verdict, "day_clustered_mean_ci_low")
    assert interval.status == RED
    assert interval.value is not None and interval.value < 0.0
    assert verdict.status == RED
    summary = verdict.summary["day_clustered"]
    assert summary["n_days"] == 40
    assert summary["max_trades_per_day"] == 50
    assert summary["positive_days"] == 20
    assert summary["ci_low"] < 0.0 < summary["ci_high"]


def test_independent_days_with_an_edge_pass_both_day_checks() -> None:
    verdict = evaluate_track_record_gate(_profitable_returns(), anchor_ts=_anchors(200, days=40), bootstrap_B=50)
    assert _check_named(verdict, "trading_days").status == GREEN
    interval = _check_named(verdict, "day_clustered_mean_ci_low")
    assert interval.status == GREEN
    assert interval.value is not None and interval.value > 0.0
    assert verdict.status == GREEN


def test_a_day_interval_touching_zero_is_red_not_green() -> None:
    """The bound must be ABOVE zero. Fifty days, each holding one +1 % and
    one -1 % trade: every day nets to zero, so every resample's mean is
    exactly 0 — a bound AT zero, which is not evidence of an edge."""
    returns = [0.01, -0.01] * 50
    anchors = [_FIRST_DAY + (i // 2) * _DAY + (i % 2) * 60.0 for i in range(100)]
    verdict = evaluate_track_record_gate(returns, anchor_ts=anchors, bootstrap_B=50)
    interval = _check_named(verdict, "day_clustered_mean_ci_low")
    assert interval.value == 0.0, "every day nets to zero, so every resample does"
    assert interval.status == RED


def test_day_checks_are_skipped_without_anchors_and_block_the_claim() -> None:
    verdict = evaluate_track_record_gate(
        _profitable_returns(),
        walk_forward_efficiency=0.7,
        fdr_rate=0.05,
        per_regime_hit_rate_spread=0.10,
        bootstrap_B=50,
    )
    assert _check_named(verdict, "trading_days").status == SKIPPED
    assert _check_named(verdict, "day_clustered_mean_ci_low").status == SKIPPED
    assert verdict.summary["day_clustered"] is None

    d = verdict_to_dict(verdict)
    assert d["status"] == "green"
    assert d["claimable"] is False
    assert "trading_days" in d["claim_note"]
    assert "day_clustered_mean_ci_low" in d["claim_note"]
    assert {"trading_days", "day_clustered_mean_ci_low"} <= set(REQUIRED_CLAIM_EVIDENCE)


def test_anchors_must_be_parallel_to_returns() -> None:
    with pytest.raises(ValueError, match="parallel"):
        evaluate_track_record_gate(_profitable_returns(), anchor_ts=_anchors(199, days=40), bootstrap_B=50)


def test_a_dropped_non_finite_return_takes_its_anchor_with_it() -> None:
    """The NaN trade sits alone on day 41. Dropping the return must drop
    that day too, or the count would credit a day without a trade."""
    returns = np.append(_profitable_returns(), np.nan)
    anchors = [*_anchors(200, days=40), _FIRST_DAY + 40 * _DAY]
    verdict = evaluate_track_record_gate(returns, anchor_ts=anchors, bootstrap_B=50)
    assert verdict.n_trades == 200
    assert _check_named(verdict, "trading_days").value == 40.0


def test_a_finite_return_without_a_day_is_refused() -> None:
    anchors = _anchors(200, days=40)
    anchors[3] = float("nan")
    with pytest.raises(ValueError, match="no day"):
        evaluate_track_record_gate(_profitable_returns(), anchor_ts=anchors, bootstrap_B=50)


def test_the_day_is_the_utc_calendar_day_of_the_anchor() -> None:
    """23:59:59 and 00:00:00 are one second apart and two days."""
    returns = _profitable_returns(n=100)
    midnight = _FIRST_DAY + _DAY
    same_day = [midnight + i for i in range(100)]
    across = [midnight - 1.0] + [midnight + i for i in range(99)]
    assert _check_named(evaluate_track_record_gate(returns, anchor_ts=same_day, bootstrap_B=50), "trading_days").value == 1.0
    assert _check_named(evaluate_track_record_gate(returns, anchor_ts=across, bootstrap_B=50), "trading_days").value == 2.0


def test_per_variant_forwards_anchors_and_rejects_unknown_families() -> None:
    returns = {"SWEEP": list(_profitable_returns())}
    out = evaluate_track_record_gate_per_variant(
        returns, anchor_ts_by_variant={"SWEEP": _anchors(200, days=3)}, bootstrap_B=50
    )
    checks = {c["name"]: c for c in out["SWEEP"]["checks"]}
    assert checks["trading_days"]["value"] == 3.0
    assert checks["trading_days"]["status"] == RED
    assert any(f.startswith("trading_days=") for f in out["SWEEP"]["failures"])

    with pytest.raises(ValueError, match="anchor_ts_by_variant"):
        evaluate_track_record_gate_per_variant(
            returns, anchor_ts_by_variant={"SWEP": _anchors(200, days=3)}, bootstrap_B=50
        )
