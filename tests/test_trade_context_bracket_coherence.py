"""A displayed bracket must be coherent or absent — never half of one.

``open_prep/atr_quality`` caps ATR at ``MAX_ACTIONABLE_ATR_PCT = 50.0`` and its
module docstring names the reason: consumers "fail closed on implausible
percentages rather than creating unreachable outcome barriers or negative
display stops". But the cap is not coupled to the bracket multipliers. With
the default ``target_mult = 2.0`` a SHORT target is ``price * (1 - 2*atr/100)``,
which reaches zero at exactly ``atr_pct = 50``, and ``actionable_atr_pct``
rejects only ``parsed > 50.0`` — so the degenerate value itself passes.

The daemon then nulls each leg independently (``_pos_float`` is a sign filter),
while ``trade_r`` is a CONSTANT ``target_mult / stop_mult`` and survives. The
panel would show an entry, a stop, no target — and a 2:1 reward claim.
"""

from __future__ import annotations

import pytest

from open_prep.atr_quality import MAX_ACTIONABLE_ATR_PCT
from open_prep.trade_context import trade_context


@pytest.mark.parametrize("direction", ["SHORT", "B_DOWN", "DOWN", "LONG", "UP"])
def test_no_bracket_leg_is_ever_non_positive(direction: str) -> None:
    """Sweep the whole admissible ATR range, not a sample of it."""
    bad: list[tuple[float, dict[str, float]]] = []
    for tenth in range(1, int(MAX_ACTIONABLE_ATR_PCT * 100) + 1):
        atr_pct = tenth / 100.0
        ctx = trade_context(100.0, atr_pct, direction)
        if ctx is None:
            continue
        if any(ctx[key] <= 0.0 for key in ("trade_entry", "trade_stop", "trade_target")):
            bad.append((atr_pct, ctx))
    assert bad == [], (
        f"{len(bad)} admissible ATR values produce a non-positive bracket leg, "
        f"first: {bad[0] if bad else None}. The consumer nulls that leg and "
        f"keeps trade_r, so the panel claims a reward ratio it cannot reach."
    )


def test_the_degenerate_boundary_value_is_refused_outright() -> None:
    """atr_pct == 50.00 with the default 2x target is exactly the zero-target
    case, and it is a reachable discrete value (the engine rounds to 2 dp)."""
    assert trade_context(100.0, 50.0, "SHORT") is None


def test_a_normal_bracket_is_untouched() -> None:
    ctx = trade_context(100.0, 2.5, "SHORT")
    assert ctx == {
        "trade_entry": 100.0,
        "trade_stop": 102.5,
        "trade_target": 95.0,
        "trade_r": 2.0,
    }
