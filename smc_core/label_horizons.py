"""Single source of truth for per-family SMC label-resolution horizons (bars).

The number of forward bars each family's canonical *outcome label* needs to
fully resolve. Both the measurement-evidence outcome labels
(:mod:`smc_integration.measurement_evidence`) and the governance walk-forward
purge/embargo (:mod:`governance.family_walkforward`) read from here so the
embargo (``2 * horizon``, López de Prado leakage guard) can never be shorter
than the label window it is meant to purge.

Audit 2026-07-13: the governance pin had drifted to ``BOS=8, OB=6, FVG=4,
SWEEP=3`` while the measurement labels actually resolve over ``8/12/20/8`` bars,
so OB/FVG/SWEEP embargo was too short and future labels leaked into
walk-forward training folds. Keeping one SSOT makes that drift impossible.

This module deliberately imports nothing (leaf), so both the ``smc_integration``
and ``governance`` layers can depend on it without a cycle.
"""

from __future__ import annotations

# Bars from the anchor (exclusive) over which each family's canonical outcome
# label is evaluated — i.e. the ScoredEvent label windows in
# ``measurement_evidence`` (``_BOS/_ZONE/_FVG/_SWEEP_LOOKAHEAD_BARS``).
LABEL_HORIZON_BARS: dict[str, int] = {
    "BOS": 8,
    "OB": 12,
    "FVG": 20,
    "SWEEP": 8,
}


def label_horizon_bars(family: str) -> int:
    """Return the label-resolution horizon (bars) for *family*.

    Raises ``KeyError`` for an unregistered family so a typo fails loudly
    rather than silently under-purging.
    """
    try:
        return LABEL_HORIZON_BARS[family]
    except KeyError:
        raise KeyError(f"no label horizon registered for family {family!r}") from None
