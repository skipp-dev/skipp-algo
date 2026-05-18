"""Sprint X2 smoke tests for ``governance.promotion_gate``."""
from __future__ import annotations

import pytest

from governance import PromotionGate
from governance.promotion_gate import (
    DECISION_SCHEMA_VERSION,
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
    # 7 missing checks (brier, ece, fdr, psr, mintrl, psi, live_vs_wf) -> yellow
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
# surface as an info-severity blocker with observed=None, instead of being
# silently clamped to ``1e-9`` (which produced a ~1e+9 ratio that tripped
# the threshold but masked the underlying data-quality issue).
# The arithmetic is delegated to
# ``scripts.forward_test_tracking.expected_vs_realized_ratio`` so this also
# pins the contract between the gate and that helper.
# ---------------------------------------------------------------------------
def _live_vs_wf_blocker(d) -> dict:
    matches = [b for b in d["blockers"] if b["check"] == "live_vs_wf_ratio"]
    assert len(matches) == 1, d["blockers"]
    return matches[0]


def test_live_vs_wf_ratio_wf_zero_with_live_positive_is_blocker() -> None:
    # wf == 0, live > 0 → ratio undefined AND live calibration has clearly
    # degraded relative to an impossible-to-beat baseline. Hard blocker.
    snap = _green_snapshot()
    snap.walkforward_brier = 0.0  # live_brier stays at 0.19 from fixture
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "blocker"
    assert "live_degraded_undefined" in b["message"]
    assert b["observed"] is None
    assert "live_vs_wf_ratio" not in d["metrics"]
    assert d["promoted"] is False


def test_live_vs_wf_ratio_wf_negative_is_data_integrity_blocker() -> None:
    # Brier is mathematically in [0, 1]; negative values upstream are
    # data corruption and must surface as a blocker, not info.
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


def test_live_vs_wf_ratio_both_zero_is_warning_and_does_not_block() -> None:
    # Both Brier scores at zero = perfect calibration on both sides.
    # Theoretically possible but suspicious; flag as warning, don't block.
    snap = _green_snapshot()
    snap.live_brier = 0.0
    snap.walkforward_brier = 0.0
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "warning"
    assert "degenerate_both_perfect" in b["message"]
    assert b["observed"] is None
    # All other green-snapshot checks pass → warning alone must not block.
    assert d["promoted"] is True
    assert d["posture"] == "yellow"  # warning downgrades posture from green


def test_live_vs_wf_ratio_too_good_to_be_true_is_warning_and_does_not_block() -> None:
    # ratio < live_vs_wf_ratio_min (0.05) means live calibration is
    # implausibly better than walk-forward. Flag, don't block.
    snap = _green_snapshot()
    snap.live_brier = 0.001
    snap.walkforward_brier = 0.10  # ratio = 0.01 < 0.05
    d = PromotionGate().evaluate(snap)
    b = _live_vs_wf_blocker(d)
    assert b["severity"] == "warning"
    assert "too_good_to_be_true" in b["message"]
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
