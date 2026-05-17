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
# Sprint C9.1: PSI-trend regression tests
# Ensure the additive psi_history field stays backwards-compatible
# (empty default => no trend check) and that warn / alarm slopes surface
# the correct blocker severity + metric.
# ---------------------------------------------------------------------------
def test_psi_history_empty_keeps_legacy_behaviour() -> None:
    snap = _green_snapshot()
    # psi_history default is an empty tuple
    assert snap.psi_history == ()
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is True
    assert "psi_slope_per_day" not in d["metrics"]


def test_psi_history_flat_emits_no_trend_alert() -> None:
    snap = _green_snapshot()
    snap.psi_history = (0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10)
    d = PromotionGate().evaluate(snap)
    assert d["promoted"] is True
    assert d["metrics"]["psi_slope_per_day"] == pytest.approx(0.0)
    assert all(b["check"] != "psi_trend" for b in d["blockers"])


def test_psi_history_slow_rise_emits_trend_warn() -> None:
    snap = _green_snapshot()
    # 14-day rise 0.05 -> 0.20 => slope ~0.011/day (warn band)
    snap.psi_history = tuple(0.05 + i * 0.0115 for i in range(14))
    d = PromotionGate().evaluate(snap)
    trend = [b for b in d["blockers"] if b["check"] == "psi_trend"]
    assert len(trend) == 1
    assert trend[0]["severity"] == "warning"
    # warn alone does not block promotion
    assert d["promoted"] is True


def test_psi_history_sharp_rise_blocks_promotion() -> None:
    snap = _green_snapshot()
    # 0.20 climb in 7 days => slope ~0.029/day (alarm band)
    snap.psi_history = tuple(0.05 + i * 0.029 for i in range(7))
    d = PromotionGate().evaluate(snap)
    trend = [b for b in d["blockers"] if b["check"] == "psi_trend"]
    assert len(trend) == 1
    assert trend[0]["severity"] == "blocker"
    assert d["promoted"] is False


def test_psi_history_single_sample_skipped() -> None:
    snap = _green_snapshot()
    snap.psi_history = (0.10,)
    d = PromotionGate().evaluate(snap)
    # < 2 samples => trend path skipped entirely
    assert "psi_slope_per_day" not in d["metrics"]
    assert all(b["check"] != "psi_trend" for b in d["blockers"])


def test_psi_history_custom_thresholds_override() -> None:
    snap = _green_snapshot()
    snap.psi_history = tuple(0.05 + i * 0.001 for i in range(7))  # slope 0.001
    # tighten warn to 0.0005 so the same slope now warns
    gate = PromotionGate(GateThresholds(psi_trend_slope_warn=0.0005, psi_trend_slope_alarm=0.01))
    d = gate.evaluate(snap)
    trend = [b for b in d["blockers"] if b["check"] == "psi_trend"]
    assert len(trend) == 1
    assert trend[0]["severity"] == "warning"
