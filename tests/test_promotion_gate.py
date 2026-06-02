"""Sprint X2 smoke tests for ``governance.promotion_gate``."""
from __future__ import annotations

import pytest

from governance import PromotionGate
from governance.promotion_gate import (
    DECISION_SCHEMA_VERSION,
    FamilyMetrics,
    GateThresholds,
    REQUIRED_PROVENANCE_KEYS,
)
from governance.types import EventFamily


def _green_snapshot(family: EventFamily = "BOS") -> FamilyMetrics:
    return FamilyMetrics(
        family=family,
        brier=0.18,
        ece=0.03,
        fdr_pvalue=0.01,
        psr=0.97,
        mintrl_years=1.4,
        psi=0.12,
        live_brier=0.19,
        walkforward_brier=0.18,
    )


def _strict_snapshot(family: EventFamily = "BOS") -> FamilyMetrics:
    """Green snapshot that also clears every W1.a check in strict mode."""
    snap = _green_snapshot(family)
    snap.regime_degraded = False
    snap.psi_slope = 0.01
    snap.conformal_coverage = 0.92
    snap.conformal_target = 0.90
    snap.brier_ci_upper = 0.21  # block-bootstrap CI upper still under bar
    snap.provenance = {
        "wf_scheme": "purged_kfold",
        "wf_embargo_bars": 32,
        "bootstrap_method": "bca",
        "block_size": 64,
        "psr_method": "minIS",
        "stacked_used": True,
    }
    return snap


def test_green_snapshot_promotes() -> None:
    gate = PromotionGate()
    d = gate.evaluate(_green_snapshot())
    assert d["promoted"] is True
    assert d["posture"] == "green"
    assert d["blockers"] == []
    assert d["schema_version"] == DECISION_SCHEMA_VERSION


def test_single_blocker_orange_not_promoted() -> None:
    snap = _green_snapshot()
    snap.brier = 0.50  # fails
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is False
    assert d["posture"] == "orange"
    blockers = [b["check"] for b in d["blockers"] if b["severity"] == "blocker"]
    assert blockers == ["brier_threshold"]


def test_two_blockers_red() -> None:
    snap = _green_snapshot()
    snap.brier = 0.50
    snap.psr = 0.10
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is False
    assert d["posture"] == "red"


def test_missing_metrics_emit_info_not_blocker() -> None:
    snap = FamilyMetrics(family="OB")
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is False
    severities = {b["severity"] for b in d["blockers"]}
    assert severities == {"info"}
    assert d["posture"] == "yellow"


def test_live_vs_wf_ratio_blocker() -> None:
    snap = _green_snapshot()
    snap.live_brier = 0.30  # ratio 0.30 / 0.18 ≈ 1.67 > 1.5
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is False
    blockers = [b["check"] for b in d["blockers"] if b["severity"] == "blocker"]
    assert "live_vs_wf_ratio" in blockers
    assert d["metrics"]["live_vs_wf_ratio"] == pytest.approx(0.30 / 0.18)


def test_audit_string_contains_each_blocker() -> None:
    snap = _green_snapshot()
    snap.brier = 0.50
    snap.psr = 0.10
    gate = PromotionGate()
    text = gate.audit(gate.evaluate(snap))
    assert "BOS" in text
    assert "BLOCKED" in text
    assert "brier_threshold" in text
    assert "psr_minimum" in text


def test_custom_thresholds_apply() -> None:
    gate = PromotionGate(GateThresholds(brier_max=0.10))
    snap = _green_snapshot()
    snap.brier = 0.18  # passes default 0.22 but fails the 0.10 override
    d = gate.evaluate(snap)
    assert d["promoted"] is False


def test_extras_surface_in_metrics() -> None:
    snap = _green_snapshot()
    snap.extras["sharpe_oos"] = 1.42
    d = PromotionGate().evaluate(snap)
    assert d["metrics"]["extra.sharpe_oos"] == pytest.approx(1.42)


def test_metrics_dict_contains_all_observed_values() -> None:
    snap = _green_snapshot()
    d = PromotionGate().evaluate(snap)
    assert set(d["metrics"]) == {
        "brier",
        "ece",
        "fdr_pvalue",
        "psr",
        "mintrl_years",
        "psi",
        "live_vs_wf_ratio",
    }


# ---------------------------------------------------------------------------
# live_vs_wf_ratio edge cases: walkforward_brier <= 0 / non-finite must
# surface as blocker-severity data-quality failures with observed=None,
# instead of being silently clamped to ``1e-9`` (which produced a ~1e+9
# ratio that tripped the threshold but masked the underlying issue).
# The arithmetic is delegated to
# ``scripts.forward_test_tracking.expected_vs_realized_ratio`` so this also
# pins the contract between the gate and that helper.
# ---------------------------------------------------------------------------
def _live_vs_wf_blocker(d) -> dict:
    matches = [b for b in d["blockers"] if b["check"] == "live_vs_wf_ratio"]
    assert len(matches) == 1, d["blockers"]
    return matches[0]


def _single_check(d, check: str) -> dict:
    matches = [b for b in d["blockers"] if b["check"] == check]
    assert len(matches) == 1, d["blockers"]
    return matches[0]


def test_live_vs_wf_ratio_wf_zero_with_live_positive_is_blocker() -> None:
    # wf == 0 makes the denominator invalid. Hard blocker, not info.
    snap = _green_snapshot()
    snap.walkforward_brier = 0.0  # live_brier stays at 0.19 from fixture
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "blocker"
    assert "data_integrity_violation" in b["message"]
    assert "<= 0" in b["message"]
    assert b["observed"] is None
    assert "live_vs_wf_ratio" not in d["metrics"]
    assert d["promoted"] is False


def test_live_vs_wf_ratio_wf_negative_is_data_integrity_blocker() -> None:
    # The ratio denominator must be strictly positive; negative values
    # upstream are data corruption and must surface as a blocker, not info.
    snap = _green_snapshot()
    snap.walkforward_brier = -0.05
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "blocker"
    assert "data_integrity_violation" in b["message"]
    assert b["observed"] is None
    assert d["promoted"] is False


def test_live_vs_wf_ratio_wf_non_finite_is_data_integrity_blocker() -> None:
    snap = _green_snapshot()
    snap.walkforward_brier = float("nan")
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "blocker"
    assert "data_integrity_violation" in b["message"]
    assert b["observed"] is None
    assert d["promoted"] is False


def test_live_vs_wf_ratio_live_non_finite_is_data_integrity_blocker() -> None:
    snap = _green_snapshot()
    snap.live_brier = float("inf")
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "blocker"
    assert "data_integrity_violation" in b["message"]
    assert d["promoted"] is False


def test_live_vs_wf_ratio_both_zero_is_blocker() -> None:
    # Even if both Brier scores are zero, live/wf ratio is undefined when
    # the walk-forward denominator is zero. This is a blocker now.
    snap = _green_snapshot()
    snap.live_brier = 0.0
    snap.walkforward_brier = 0.0
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "blocker"
    assert "data_integrity_violation" in b["message"]
    assert "<= 0" in b["message"]
    assert b["observed"] is None
    assert d["promoted"] is False
    assert d["posture"] == "orange"


def test_live_vs_wf_ratio_too_good_to_be_true_is_warning_and_does_not_block() -> None:
    # ratio < live_vs_wf_ratio_min (0.05) means live calibration is
    # implausibly better than walk-forward. Flag as suspicious_too_good,
    # don't block.
    snap = _green_snapshot()
    snap.live_brier = 0.001
    snap.walkforward_brier = 0.10  # ratio = 0.01 < 0.05
    d = PromotionGate().evaluate(snap)
    b = _single_check(d, "suspicious_too_good")
    assert b["severity"] == "warning"
    assert "suspicious_too_good" in b["message"]
    assert b["observed"] == pytest.approx(0.01)
    assert d["metrics"]["live_vs_wf_ratio"] == pytest.approx(0.01)
    assert d["promoted"] is True
    assert d["posture"] == "yellow"


def test_live_vs_wf_ratio_normal_path_unchanged() -> None:
    # Regression guard: valid inputs still compute the ratio identically
    # to the pre-refactor ``live_brier / walkforward_brier`` formula.
    snap = _green_snapshot()
    snap.live_brier = 0.20
    snap.walkforward_brier = 0.10
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "blocker"
    assert b["observed"] == pytest.approx(2.0)
    assert d["metrics"]["live_vs_wf_ratio"] == pytest.approx(2.0)
    assert d["promoted"] is False


# ---------------------------------------------------------------------------
# Sprint W1.a: schema v2 + provenance + strict-mode gating.
# ---------------------------------------------------------------------------
def test_decision_schema_version_is_two() -> None:
    assert DECISION_SCHEMA_VERSION == 2
    d = PromotionGate().evaluate(_green_snapshot())
    assert d["schema_version"] == 2


def test_decision_includes_provenance_dict() -> None:
    d = PromotionGate().evaluate(_green_snapshot())
    assert "provenance" in d
    assert d["provenance"] == {}


def test_lax_mode_ignores_missing_w1a_fields() -> None:
    d = PromotionGate().evaluate(_green_snapshot())
    assert d["promoted"] is True
    assert d["posture"] == "green"


def test_strict_mode_blocks_when_w1a_fields_missing() -> None:
    gate = PromotionGate(GateThresholds(strict_provenance=True))
    d = gate.evaluate(_green_snapshot())
    assert d["promoted"] is False
    checks = {b["check"] for b in d["blockers"]}
    assert "regime_degraded" in checks
    assert "psi_slope_threshold" in checks
    assert "conformal_coverage" in checks
    assert "brier_ci_upper" in checks
    for key in REQUIRED_PROVENANCE_KEYS:
        assert f"provenance.{key}" in checks


def test_strict_mode_passes_when_all_fields_present() -> None:
    gate = PromotionGate(GateThresholds(strict_provenance=True))
    d = gate.evaluate(_strict_snapshot())
    assert d["promoted"] is True
    assert d["posture"] == "green"
    assert d["blockers"] == []
    assert d["provenance"]["wf_scheme"] == "purged_kfold"
    assert d["provenance"]["stacked_used"] is True


def test_brier_ci_upper_breach_blocks_even_in_lax_mode() -> None:
    # Point Brier is fine, but the block-bootstrap CI upper bound pokes above
    # the bar: once measured, that is serial-dependence-aware evidence the true
    # Brier may exceed threshold, so it blocks regardless of strict mode.
    snap = _green_snapshot()
    snap.brier_ci_upper = 0.30  # > DEFAULT_BRIER_CI_UPPER_MAX (0.22)
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is False
    checks = {b["check"]: b["severity"] for b in d["blockers"]}
    assert checks["brier_ci_upper"] == "blocker"


def test_brier_ci_upper_under_bar_passes() -> None:
    snap = _green_snapshot()
    snap.brier_ci_upper = 0.21  # <= 0.22
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is True
    assert d["metrics"]["brier_ci_upper"] == 0.21


def test_brier_ci_upper_missing_is_lax_passthrough_strict_block() -> None:
    # Missing CI: lax mode lets it pass (legacy snapshots stay valid), strict
    # mode blocks it as "not yet measured" with info severity.
    snap = _green_snapshot()  # brier_ci_upper defaults to None
    assert PromotionGate().evaluate(snap)["promoted"] is True
    strict = PromotionGate(GateThresholds(strict_provenance=True)).evaluate(snap)
    info = {b["check"]: b["severity"] for b in strict["blockers"]}
    assert info["brier_ci_upper"] == "info"


def test_regime_degraded_true_is_hard_blocker_in_lax_mode() -> None:
    snap = _green_snapshot()
    snap.regime_degraded = True
    d = PromotionGate().evaluate(snap)
    severities = {b["check"]: b["severity"] for b in d["blockers"]}
    assert d["promoted"] is False
    assert severities.get("regime_degraded") == "blocker"


def test_psi_slope_above_threshold_blocks() -> None:
    snap = _strict_snapshot()
    snap.psi_slope = 0.20  # above default 0.05 cap
    d = PromotionGate(GateThresholds(strict_provenance=True)).evaluate(snap)
    assert d["promoted"] is False
    assert any(
        b["check"] == "psi_slope_threshold" and b["severity"] == "blocker"
        for b in d["blockers"]
    )


def test_conformal_coverage_below_floor_blocks() -> None:
    snap = _strict_snapshot()
    snap.conformal_coverage = 0.80  # target 0.90 minus tolerance 0.02 → floor 0.88
    d = PromotionGate(GateThresholds(strict_provenance=True)).evaluate(snap)
    assert d["promoted"] is False
    blockers = [b for b in d["blockers"] if b["check"] == "conformal_coverage"]
    assert blockers and blockers[0]["severity"] == "blocker"


def test_provenance_passes_through_in_lax_mode() -> None:
    snap = _green_snapshot()
    snap.provenance = {"wf_scheme": "purged_kfold", "psr_method": "minIS"}
    d = PromotionGate().evaluate(snap)
    assert d["provenance"] == {"wf_scheme": "purged_kfold", "psr_method": "minIS"}
    assert d["promoted"] is True
