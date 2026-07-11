"""HardConstraintLayer must validate its own caps so a misconfigured guard
fails CLOSED, not open.

Truth-audit finding: the layer rejected non-finite *inputs* but never checked
its own config, so a NaN drawdown cap silently disabled the veto (``x >= NaN``
is False), a >1 cap (a percent mistaken for a fraction) let through up to that
multiple of equity/drawdown, and a negative size cap made the guard emit a
negative size fraction.
"""
from __future__ import annotations

import pytest

from rl.safety import HardConstraintLayer
from rl.types import ExecutionAction


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_drawdown_pct": float("nan")},
        {"max_drawdown_pct": float("inf")},
        {"max_drawdown_pct": -0.1},
        {"max_drawdown_pct": 5.0},  # percent (5%) mistaken for a fraction
        {"max_size_fraction": float("nan")},
        {"max_size_fraction": float("-inf")},
        {"max_size_fraction": -0.1},
        {"max_size_fraction": 1.5},
    ],
)
def test_misconfigured_caps_raise(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="finite fraction in"):
        HardConstraintLayer(**kwargs)


def test_valid_caps_construct() -> None:
    layer = HardConstraintLayer(max_size_fraction=0.02, max_drawdown_pct=0.2)
    assert layer.max_size_fraction == 0.02
    assert layer.max_drawdown_pct == 0.2


def test_zero_caps_allowed_and_fail_closed() -> None:
    # A zero cap is the safe extreme (reject everything), not a misconfig: it
    # must construct and then veto at any drawdown / any positive size.
    layer = HardConstraintLayer(max_size_fraction=0.0, max_drawdown_pct=0.0)
    res = layer.guard_action(
        ExecutionAction(slice_size=0.5, order_type="market"), drawdown_pct=0.0
    )
    assert res.action.slice_size == 0.0
    assert res.decision == "rejected"
    enforced, decision, _ = layer.guard_size_fraction(0.5)
    assert enforced == 0.0 and decision == "clamped"
