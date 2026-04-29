"""Sprint C8.1 tests for forward-test tracking helpers."""
from __future__ import annotations

import math

import pytest

from scripts.forward_test_tracking import (
    DynamicIncubationCriteria,
    dynamic_incubation_decision,
    expected_vs_realized_ratio,
)

# ---------------------------------------------------------------------------
# expected_vs_realized_ratio
# ---------------------------------------------------------------------------


def test_evr_returns_ratio_for_positive_inputs() -> None:
    assert expected_vs_realized_ratio(0.20, 0.10) == pytest.approx(2.0)
    assert expected_vs_realized_ratio(0.05, 0.10) == pytest.approx(0.5)


def test_evr_none_for_nonpositive_wf() -> None:
    assert expected_vs_realized_ratio(0.10, 0.0) is None
    assert expected_vs_realized_ratio(0.10, -0.01) is None


def test_evr_none_for_non_finite() -> None:
    assert expected_vs_realized_ratio(math.nan, 0.10) is None
    assert expected_vs_realized_ratio(0.10, math.inf) is None
    assert expected_vs_realized_ratio(math.inf, 0.10) is None


# ---------------------------------------------------------------------------
# dynamic_incubation_decision
# ---------------------------------------------------------------------------


def _ok_kwargs(**overrides):
    base = dict(
        days_in_phase=30,
        n_trades_closed=35,
        psr_live=0.95,
        psr_walkforward=0.95,
        live_brier=0.10,
        walkforward_brier=0.10,
    )
    base.update(overrides)
    return base


def test_promote_when_all_criteria_met() -> None:
    decision, blockers = dynamic_incubation_decision(**_ok_kwargs())
    assert decision == "promote"
    assert blockers == []


def test_continue_when_too_few_days() -> None:
    decision, blockers = dynamic_incubation_decision(**_ok_kwargs(days_in_phase=10))
    assert decision == "continue"
    assert any("days_in_phase" in b for b in blockers)


def test_continue_when_too_few_trades() -> None:
    decision, blockers = dynamic_incubation_decision(
        **_ok_kwargs(n_trades_closed=5)
    )
    assert decision == "continue"
    assert any("n_trades_closed" in b for b in blockers)


def test_continue_when_psr_below_wf_minus_margin() -> None:
    decision, blockers = dynamic_incubation_decision(
        **_ok_kwargs(psr_live=0.70, psr_walkforward=0.95)
    )
    assert decision == "continue"
    assert any("psr_live" in b for b in blockers)


def test_continue_when_psr_within_margin() -> None:
    """psr_live within margin of psr_wf is acceptable for promote."""
    decision, _ = dynamic_incubation_decision(
        **_ok_kwargs(psr_live=0.91, psr_walkforward=0.95)
    )
    assert decision == "promote"


def test_demote_when_live_brier_blows_threshold() -> None:
    decision, blockers = dynamic_incubation_decision(
        **_ok_kwargs(live_brier=0.20, walkforward_brier=0.10)
    )
    assert decision == "demote"
    assert any("live_vs_wf_brier_ratio" in b for b in blockers)


def test_demote_overrides_other_blockers() -> None:
    """A blown ratio short-circuits even a missing-days blocker."""
    decision, _ = dynamic_incubation_decision(
        **_ok_kwargs(
            days_in_phase=2,  # would otherwise block
            live_brier=0.30,
            walkforward_brier=0.10,
        )
    )
    assert decision == "demote"


def test_continue_when_metrics_missing() -> None:
    decision, blockers = dynamic_incubation_decision(
        **_ok_kwargs(psr_live=None, psr_walkforward=None)
    )
    assert decision == "continue"
    assert any("psr_live_or_walkforward_missing" in b for b in blockers)


def test_custom_criteria_tighten_promotion() -> None:
    crit = DynamicIncubationCriteria(
        min_phase_days=50, min_trades_closed=60, psr_margin=0.01
    )
    decision, blockers = dynamic_incubation_decision(
        **_ok_kwargs(), criteria=crit
    )
    assert decision == "continue"
    # Both calendar + sample-size fail under the tighter criteria.
    assert any("days_in_phase" in b for b in blockers)
    assert any("n_trades_closed" in b for b in blockers)


def test_demote_threshold_can_be_relaxed() -> None:
    crit = DynamicIncubationCriteria(demote_ratio_threshold=3.0)
    decision, _ = dynamic_incubation_decision(
        **_ok_kwargs(live_brier=0.20, walkforward_brier=0.10), criteria=crit
    )
    # Ratio 2.0 < threshold 3.0 → no demote.
    assert decision == "promote"


def test_evr_zero_live_brier_yields_zero_ratio() -> None:
    """Perfect live calibration is allowed (ratio == 0)."""
    assert expected_vs_realized_ratio(0.0, 0.10) == 0.0


def test_undefined_brier_ratio_blocks_promote() -> None:
    """When both Brier inputs are provided but the ratio is undefined
    (walkforward_brier <= 0 or non-finite), the decision must not be
    promote — it must surface the issue as an explicit blocker.
    """
    decision, blockers = dynamic_incubation_decision(
        **_ok_kwargs(live_brier=0.10, walkforward_brier=0.0)
    )
    assert decision == "continue"
    assert any("live_vs_wf_brier_ratio_undefined" in b for b in blockers)
