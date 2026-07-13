"""EV-05 — per-family walk-forward / embargo configuration.

The X2 PromotionGate consumes ``wf_scheme`` and ``wf_embargo_bars`` in
each family's provenance block, but nothing pins what those values *are*
per :class:`~governance.types.EventFamily`. This module is that pin.

Leakage pin à la López de Prado's purge/embargo (the 2x factor is this
repo's conservative choice): ``embargo_bars >= 2 * max_event_horizon``. A sweep
reversal resolves faster than a break-of-structure swing, so the embargo
differs per family — encoding it here keeps the walk-forward split
honest and auditable rather than buried in a notebook.

Roadmap pointer: Edge-Validation Roadmap, Phase 1 / story EV-05.
"""
from __future__ import annotations

from typing import get_args

from governance.types import EventFamily
from ml.walkforward import WalkForwardConfig
from smc_core.label_horizons import LABEL_HORIZON_BARS

# Per-family TRADE-EXIT HOLD (bars held after entry before the exit close) —
# bar COUNTS: the wall-clock meaning follows the run's timeframe (8 bars = 2h at
# 15m, 8 days at 1D). This is the horizon ``realized_return`` uses to pick the
# exit close; it is NOT the label-RESOLUTION window (that is the SSOT
# ``smc_core.label_horizons.LABEL_HORIZON_BARS`` = 8/12/20/8) and must not be
# confused with it — see the embargo note in ``_build_config``.
_FAMILY_MAX_EVENT_HORIZON_BARS: dict[str, int] = {
    "BOS": 8,    # break-of-structure swing — slowest to resolve
    "OB": 6,     # order-block reaction
    "FVG": 4,    # fair-value-gap fill — quicker mean-reversion
    "SWEEP": 3,  # liquidity-sweep reversal — fastest
}


def _build_config(label_window_bars: int) -> WalkForwardConfig:
    # embargo_bars = 2 * LABEL-RESOLUTION window (López de Prado leakage guard).
    # Audit 2026-07-13: the embargo was keyed to the trade HOLD (``2 * horizon``),
    # which is SHORTER than the label window for OB/FVG/SWEEP (6/4/3 hold vs the
    # real 12/20/8 resolution), so a training event's label could overlap the
    # validation fold. Keying it to the shared LABEL_HORIZON_BARS SSOT — the same
    # window the measurement labels resolve over — closes that leak and can no
    # longer drift below it.
    return WalkForwardConfig(
        scheme="expanding",
        n_folds=5,
        embargo_bars=2 * label_window_bars,
    )


FAMILY_WALKFORWARD: dict[str, WalkForwardConfig] = {
    family: _build_config(LABEL_HORIZON_BARS[family])
    for family in _FAMILY_MAX_EVENT_HORIZON_BARS
}


def family_outcome_horizon(family: str) -> int:
    """Return the TRADE-EXIT HOLD (bars) for *family* — the horizon
    ``realized_return`` holds a position before taking the exit close.

    NOTE: this is not the label-RESOLUTION window used for the walk-forward
    embargo; that is ``smc_core.label_horizons.LABEL_HORIZON_BARS`` and drives
    :func:`get_family_config`'s ``embargo_bars``.
    """
    try:
        return _FAMILY_MAX_EVENT_HORIZON_BARS[family]
    except KeyError:
        raise KeyError(f"no walk-forward horizon registered for family {family!r}") from None


def get_family_config(family: str) -> WalkForwardConfig:
    """Return the frozen walk-forward config for *family*.

    Raises ``KeyError`` if the family has no registered config.
    """
    try:
        return FAMILY_WALKFORWARD[family]
    except KeyError:
        raise KeyError(f"no walk-forward config registered for family {family!r}") from None


def validate_family_coverage() -> dict[str, WalkForwardConfig]:
    """Ensure every gate ``EventFamily`` has a config; return the mapping.

    Raises ``ValueError`` on an uncovered or unknown family.
    """
    valid = set(get_args(EventFamily))
    registered = set(FAMILY_WALKFORWARD)
    uncovered = sorted(valid - registered)
    if uncovered:
        raise ValueError(f"no walk-forward config for families: {uncovered}")
    unknown = sorted(registered - valid)
    if unknown:
        raise ValueError(f"walk-forward config for unknown families: {unknown}")
    return dict(FAMILY_WALKFORWARD)


__all__ = [
    "FAMILY_WALKFORWARD",
    "family_outcome_horizon",
    "get_family_config",
    "validate_family_coverage",
]
