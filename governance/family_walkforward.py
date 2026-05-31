"""EV-05 — per-family walk-forward / embargo configuration.

The X2 PromotionGate consumes ``wf_scheme`` and ``wf_embargo_bars`` in
each family's provenance block, but nothing pins what those values *are*
per :class:`~governance.types.EventFamily`. This module is that pin.

López de Prado's leakage rule: ``embargo_bars >= 2 * max_event_horizon``
(the number of bars until a setup's label is fully resolved). A sweep
reversal resolves faster than a break-of-structure swing, so the embargo
differs per family — encoding it here keeps the walk-forward split
honest and auditable rather than buried in a notebook.

Roadmap pointer: Edge-Validation Roadmap, Phase 1 / story EV-05.
"""
from __future__ import annotations

from typing import get_args

from governance.types import EventFamily
from ml.walkforward import WalkForwardConfig

# Per-family outcome horizon (bars until the label is fully resolved) on
# the primary 15m timeframe. Embargo is derived as 2 * horizon per
# López de Prado, so these are the single source of truth.
#
# These are conservative starting values tied to each setup's typical
# hold; tighten only with measured label-resolution distributions.
_FAMILY_MAX_EVENT_HORIZON_BARS: dict[str, int] = {
    "BOS": 8,    # break-of-structure swing — slowest to resolve
    "OB": 6,     # order-block reaction
    "FVG": 4,    # fair-value-gap fill — quicker mean-reversion
    "SWEEP": 3,  # liquidity-sweep reversal — fastest
}


def _build_config(horizon_bars: int) -> WalkForwardConfig:
    # embargo_bars = 2 * max_event_horizon (López de Prado leakage guard).
    return WalkForwardConfig(
        scheme="expanding",
        n_folds=5,
        embargo_bars=2 * horizon_bars,
    )


FAMILY_WALKFORWARD: dict[str, WalkForwardConfig] = {
    family: _build_config(horizon)
    for family, horizon in _FAMILY_MAX_EVENT_HORIZON_BARS.items()
}


def family_outcome_horizon(family: str) -> int:
    """Return the label-resolution horizon (bars) for *family*."""
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
