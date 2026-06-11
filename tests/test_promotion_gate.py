"""Sprint X2 smoke tests for ``governance.promotion_gate``."""
from __future__ import annotations

import pytest

from governance import PromotionGate
from governance.promotion_gate import (
    DECISION_SCHEMA_VERSION,
    ML_MODELLING_PROVENANCE_KEYS,
    PIPELINE_CLASS_KEY,
    REQUIRED_PROVENANCE_KEYS,
    SMC_DIRECT_NO_ML,
    FamilyMetrics,
    GateThresholds,
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
    snap.magnitude_resolution_pass = True  # ADR-0023 move-size bar cleared
    snap.magnitude_auc = 0.62
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


def test_magnitude_resolution_unmeasured_is_non_blocking_in_lax_mode() -> None:
    # ADR-0023: the additive move-size check is a qualifier, not a regression.
    # An unmeasured family keeps the legacy direction-only behaviour.
    snap = _green_snapshot()
    assert snap.magnitude_resolution_pass is None
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is True
    checks = {b["check"] for b in d["blockers"]}
    assert "magnitude_resolution_floor" not in checks


def test_magnitude_resolution_pass_surfaces_auc_metric() -> None:
    snap = _green_snapshot()
    snap.magnitude_resolution_pass = True
    snap.magnitude_auc = 0.66
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is True
    assert d["metrics"]["magnitude_resolution_pass"] == 1.0
    assert d["metrics"]["magnitude_auc"] == pytest.approx(0.66)


def test_magnitude_resolution_failure_blocks_additively() -> None:
    # A family that does not clear the ADR-0023 §2 bar is hard-blocked on the
    # new check while the direction-Brier check stays green (additive design).
    snap = _green_snapshot()
    snap.magnitude_resolution_pass = False
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is False
    blockers = [b["check"] for b in d["blockers"] if b["severity"] == "blocker"]
    assert blockers == ["magnitude_resolution_floor"]
    assert d["metrics"]["magnitude_resolution_pass"] == 0.0


def test_magnitude_resolution_unmeasured_info_blocks_in_strict_mode() -> None:
    snap = _green_snapshot()  # leaves magnitude_resolution_pass None
    d = PromotionGate(GateThresholds(strict_provenance=True)).evaluate(snap)
    info = {b["check"] for b in d["blockers"] if b["severity"] == "info"}
    assert "magnitude_resolution_floor" in info


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


def _no_ml_strict_snapshot(family: EventFamily = "BOS") -> FamilyMetrics:
    """Strict snapshot for an SMC-direct no-ML pipeline (ADR-0016).

    Clears every W1.a numeric check, declares the pipeline class, and supplies
    ONLY the pipeline-agnostic provenance keys -- the ML-modelling keys
    (bootstrap_method/block_size/stacked_used) are deliberately absent because
    no such modelling layer exists.
    """
    snap = _strict_snapshot(family)
    snap.provenance = {
        "wf_scheme": "purged_kfold",
        "wf_embargo_bars": 32,
        "psr_method": "minIS",
        PIPELINE_CLASS_KEY: SMC_DIRECT_NO_ML,
    }
    return snap


def test_no_ml_class_waives_ml_modelling_provenance_keys() -> None:
    # ADR-0016: a declared no-ML pipeline is not blocked by the three
    # ML-modelling keys -- they are not-applicable, not missing.
    d = PromotionGate(GateThresholds(strict_provenance=True)).evaluate(
        _no_ml_strict_snapshot()
    )
    checks = {b["check"] for b in d["blockers"]}
    for key in ML_MODELLING_PROVENANCE_KEYS:
        assert f"provenance.{key}" not in checks
    assert d["promoted"] is True
    assert d["posture"] == "green"
    assert d["provenance"][PIPELINE_CLASS_KEY] == SMC_DIRECT_NO_ML


def test_unknown_pipeline_class_grants_no_waiver() -> None:
    # An arbitrary/unknown class value must NOT unlock the waiver, so the
    # ML-modelling keys stay required.
    snap = _no_ml_strict_snapshot()
    snap.provenance = dict(snap.provenance)
    snap.provenance[PIPELINE_CLASS_KEY] = "totally_made_up_class"
    d = PromotionGate(GateThresholds(strict_provenance=True)).evaluate(snap)
    checks = {b["check"] for b in d["blockers"]}
    for key in ML_MODELLING_PROVENANCE_KEYS:
        assert f"provenance.{key}" in checks
    assert d["promoted"] is False


def test_no_ml_class_still_requires_pipeline_agnostic_keys() -> None:
    # The waiver is scoped to the ML-modelling keys only; the pipeline-agnostic
    # keys (wf_scheme/wf_embargo_bars/psr_method) stay required for every class.
    snap = _no_ml_strict_snapshot()
    snap.provenance = {PIPELINE_CLASS_KEY: SMC_DIRECT_NO_ML}
    d = PromotionGate(GateThresholds(strict_provenance=True)).evaluate(snap)
    checks = {b["check"] for b in d["blockers"]}
    assert "provenance.wf_scheme" in checks
    assert "provenance.wf_embargo_bars" in checks
    assert "provenance.psr_method" in checks
    assert d["promoted"] is False


def test_no_ml_class_does_not_waive_conformal_coverage() -> None:
    # ADR-0016 changes only the provenance-key requirement; conformal coverage
    # is computed on the OOS pairs and stays an applicable, measured guard.
    snap = _no_ml_strict_snapshot()
    snap.conformal_coverage = None
    snap.conformal_target = None
    d = PromotionGate(GateThresholds(strict_provenance=True)).evaluate(snap)
    checks = {b["check"] for b in d["blockers"]}
    assert "conformal_coverage" in checks
    assert d["promoted"] is False


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


def test_brier_ci_upper_max_tracks_brier_max_override() -> None:
    # Coupling: overriding only brier_max must flow through to the CI bar so
    # the CI check is never silently left looser than the point-estimate bar.
    t = GateThresholds(brier_max=0.18)
    assert t.brier_ci_upper_max == 0.18
    # A CI upper bound that clears the old default (0.22) but breaches the
    # tightened bar (0.18) must now block.
    snap = _green_snapshot()
    snap.brier = 0.17
    snap.brier_ci_upper = 0.20  # under 0.22, over the tightened 0.18
    d = PromotionGate(t).evaluate(snap)
    checks = {b["check"]: b["severity"] for b in d["blockers"]}
    assert checks["brier_ci_upper"] == "blocker"


def test_brier_ci_upper_max_can_be_decoupled_explicitly() -> None:
    # Passing an explicit float decouples the two knobs.
    t = GateThresholds(brier_max=0.18, brier_ci_upper_max=0.25)
    assert t.brier_ci_upper_max == 0.25


def test_brier_ci_upper_max_is_always_a_concrete_float() -> None:
    # The stored attribute must never surface the tracking sentinel (or None):
    # both default and overridden construction resolve to a concrete float so
    # downstream code never has to re-narrow ``float | None``.
    default = GateThresholds()
    assert isinstance(default.brier_ci_upper_max, float)
    assert default.brier_ci_upper_max == default.brier_max
    overridden = GateThresholds(brier_max=0.18)
    assert isinstance(overridden.brier_ci_upper_max, float)
    assert overridden.brier_ci_upper_max == 0.18


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


# ---- ADR-0023 Stage 2: per-family magnitude arming ----------------------


def _armed_gate(*families: str) -> PromotionGate:
    return PromotionGate(
        GateThresholds(magnitude_strict_families=frozenset(families))
    )


def test_armed_family_unmeasured_magnitude_blocks_in_lax_mode() -> None:
    # Stage 2: an armed family is fail-closed on a MISSING measurement even
    # when the gate is otherwise lax.
    d = _armed_gate("BOS").evaluate(_green_snapshot("BOS"))
    assert d["promoted"] is False
    info = {b["check"] for b in d["blockers"] if b["severity"] == "info"}
    assert "magnitude_resolution_floor" in info
    [blocker] = [
        b for b in d["blockers"] if b["check"] == "magnitude_resolution_floor"
    ]
    assert "armed strict" in blocker["message"]


def test_unarmed_family_unaffected_by_other_families_arming() -> None:
    # Arming BOS/SWEEP must not change FVG's lax dormant posture.
    d = _armed_gate("BOS", "SWEEP").evaluate(_green_snapshot("FVG"))
    assert d["promoted"] is True
    assert d["blockers"] == []


def test_armed_family_measured_pass_promotes_in_lax_mode() -> None:
    snap = _green_snapshot("SWEEP")
    snap.magnitude_resolution_pass = True
    snap.magnitude_auc = 0.66
    d = _armed_gate("BOS", "SWEEP").evaluate(snap)
    assert d["promoted"] is True
    assert d["metrics"]["magnitude_resolution_pass"] == 1.0


def test_armed_family_measured_fail_hard_blocks() -> None:
    snap = _green_snapshot("BOS")
    snap.magnitude_resolution_pass = False
    d = _armed_gate("BOS").evaluate(snap)
    assert d["promoted"] is False
    [blocker] = [
        b for b in d["blockers"] if b["check"] == "magnitude_resolution_floor"
    ]
    assert blocker["severity"] == "blocker"


def test_arming_does_not_co_trigger_provenance_blockers_in_lax_mode() -> None:
    # ADR-0016 interaction guard (handover §5 item 4): arming one family's
    # magnitude floor is decoupled from strict_provenance, so it must NOT
    # surface any provenance.* / W1.a missing-field info blockers.
    snap = _green_snapshot("BOS")  # carries no provenance keys at all
    d = _armed_gate("BOS").evaluate(snap)
    checks = {b["check"] for b in d["blockers"]}
    assert checks == {"magnitude_resolution_floor"}
    assert not any(c.startswith("provenance.") for c in checks)


def test_arming_preserves_no_ml_waiver_in_strict_mode() -> None:
    # ADR-0016: under strict provenance a declared no-ML pipeline waives the
    # ML-modelling keys. Arming the same family must keep that waiver intact —
    # the armed magnitude branch and the provenance branch stay independent.
    snap = _no_ml_strict_snapshot("BOS")
    gate = PromotionGate(
        GateThresholds(
            strict_provenance=True,
            magnitude_strict_families=frozenset({"BOS"}),
        )
    )
    d = gate.evaluate(snap)
    checks = {b["check"] for b in d["blockers"]}
    for key in ML_MODELLING_PROVENANCE_KEYS:
        assert f"provenance.{key}" not in checks
    assert d["promoted"] is True


def test_arming_magnitude_failure_does_not_add_provenance_blockers_strict() -> None:
    # Even when the armed family FAILS the magnitude bar under strict
    # provenance, the only NEW blocker vs. the unarmed run is the magnitude
    # floor itself — no provenance blocker co-triggers.
    snap = _no_ml_strict_snapshot("BOS")
    snap.magnitude_resolution_pass = False
    strict = GateThresholds(strict_provenance=True)
    armed = GateThresholds(
        strict_provenance=True, magnitude_strict_families=frozenset({"BOS"})
    )
    base_checks = {
        b["check"] for b in PromotionGate(strict).evaluate(snap)["blockers"]
    }
    armed_checks = {
        b["check"] for b in PromotionGate(armed).evaluate(snap)["blockers"]
    }
    assert armed_checks == base_checks == {"magnitude_resolution_floor"}


def test_gate_thresholds_default_is_unarmed() -> None:
    assert GateThresholds().magnitude_strict_families == frozenset()
