"""Tests for ``scripts/live_risk_limits.py`` (Sprint C8 / T2)."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.live_risk_limits import (
    AccountState,
    BreachReason,
    RiskLimits,
    check_risk_limits,
)


def _state(**overrides) -> AccountState:
    base = dict(
        as_of=date(2026, 4, 26),
        equity=100_000.0,
        starting_equity_today=100_000.0,
        high_water_mark=100_000.0,
        open_positions=0,
        gross_exposure_pct=0.0,
        last_n_pnls=(),
    )
    base.update(overrides)
    return AccountState(**base)


def test_default_state_is_safe() -> None:
    out = check_risk_limits(_state(), RiskLimits())
    assert out.engaged is False
    assert out.reasons == ()
    assert out.primary_reason is None


def test_manual_halt_engages_immediately() -> None:
    out = check_risk_limits(_state(), RiskLimits(manual_halt=True))
    assert out.engaged
    assert out.primary_reason is BreachReason.MANUAL_HALT


def test_daily_loss_breach_below_threshold() -> None:
    state = _state(equity=98_000.0)  # -2% exactly
    limits = RiskLimits(max_daily_loss_pct=2.0)
    out = check_risk_limits(state, limits)
    assert out.engaged
    assert BreachReason.DAILY_LOSS in out.reasons


def test_daily_loss_just_above_limit_safe() -> None:
    state = _state(equity=98_001.0)  # -1.999%
    limits = RiskLimits(max_daily_loss_pct=2.0)
    assert check_risk_limits(state, limits).engaged is False


def test_drawdown_breach() -> None:
    state = _state(equity=92_000.0, high_water_mark=100_000.0, starting_equity_today=92_000.0)
    limits = RiskLimits(max_drawdown_pct=8.0, max_daily_loss_pct=20.0)
    out = check_risk_limits(state, limits)
    assert BreachReason.DRAWDOWN in out.reasons


def test_max_open_positions_breach() -> None:
    state = _state(open_positions=6)
    limits = RiskLimits(max_open_positions=5)
    assert BreachReason.MAX_OPEN_POSITIONS in check_risk_limits(state, limits).reasons


def test_max_open_positions_at_limit_safe() -> None:
    state = _state(open_positions=5)
    limits = RiskLimits(max_open_positions=5)
    assert check_risk_limits(state, limits).engaged is False


def test_exposure_breach() -> None:
    state = _state(gross_exposure_pct=210.0)
    limits = RiskLimits(max_gross_exposure_pct=200.0)
    assert BreachReason.EXPOSURE in check_risk_limits(state, limits).reasons


def test_consecutive_losses_breach_only_counts_tail() -> None:
    state = _state(last_n_pnls=(0.5, -0.1, -0.1, -0.1, -0.1))
    limits = RiskLimits(max_consecutive_losses=4)
    out = check_risk_limits(state, limits)
    assert BreachReason.MAX_CONSECUTIVE_LOSSES in out.reasons


def test_consecutive_losses_resets_on_win_in_tail() -> None:
    state = _state(last_n_pnls=(-0.1, -0.1, -0.1, -0.1, 0.05))
    limits = RiskLimits(max_consecutive_losses=4)
    assert check_risk_limits(state, limits).engaged is False


def test_zero_pnl_in_streak_does_not_count_as_loss() -> None:
    state = _state(last_n_pnls=(-0.1, -0.1, 0.0))
    limits = RiskLimits(max_consecutive_losses=2)
    # 0.0 breaks the streak; count from end = 0 < 2 → safe
    assert check_risk_limits(state, limits).engaged is False


def test_multiple_breaches_reported_together() -> None:
    state = _state(
        equity=90_000.0,
        starting_equity_today=100_000.0,
        high_water_mark=100_000.0,
        open_positions=10,
    )
    limits = RiskLimits(
        max_daily_loss_pct=2.0, max_open_positions=5, max_drawdown_pct=8.0
    )
    out = check_risk_limits(state, limits)
    assert {
        BreachReason.DAILY_LOSS,
        BreachReason.DRAWDOWN,
        BreachReason.MAX_OPEN_POSITIONS,
    }.issubset(set(out.reasons))


def test_zero_starting_equity_does_not_crash() -> None:
    state = _state(starting_equity_today=0.0, equity=-1000.0)
    out = check_risk_limits(state, RiskLimits())
    # daily_loss check skipped (no division by zero)
    assert BreachReason.DAILY_LOSS not in out.reasons


def test_zero_high_water_mark_does_not_crash() -> None:
    state = _state(high_water_mark=0.0, equity=-100.0)
    out = check_risk_limits(state, RiskLimits())
    assert BreachReason.DRAWDOWN not in out.reasons


def test_decision_immutable() -> None:
    out = check_risk_limits(_state(), RiskLimits())
    with pytest.raises(Exception):
        out.engaged = True  # type: ignore[misc]
