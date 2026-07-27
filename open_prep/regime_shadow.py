"""Shadow measurement for the scorer's §15 SYMBOL-layer regime weights.

``score_candidate`` resolves ``symbol_regime`` from ``quote["adx"]`` and
``quote["bb_width_pct"]``.  No producer populates either key on the premarket
quote path, so the scorer always falls back to its defaults (15.0 / 3.0),
which classify as ``NEUTRAL`` — and ``resolve_regime_weights`` applies no tilt
for ``NEUTRAL``.  The §15 symbol-layer adjustment is therefore inert in
production even though the comment at its call site describes it as active.

The measured indicators *do* exist in the same run: ``run_open_prep`` computes
Wilder ADX and BB width from the daily bars, but only in the enrichment stage
that runs **after** scoring, so they cannot reach ``score_candidate``.

This module records what the measured regime *would* have changed, so the
decision to wire §15 up can be made on real runs instead of on a guess.  It is
observation-only: nothing here feeds a gate, a rank, a weight or a score.
Consumer (added 2026-07-28 after a sweep flagged the measurement as
reader-less): ``python -m scripts.report_regime_weight_shadow`` aggregates
the stamped rows from the run payloads into the decision summary.

Exactness
---------
The composite score is linear in the weights for the affected components:
``component_k = w_k * f_k``.  Under a different weight ``w'_k`` the component
becomes ``component_k * w'_k / w_k``, so the delta is reconstructible from the
emitted ``score_breakdown`` alone — no re-scoring, no feature reconstruction.

The baseline is ``resolve_regime_weights(base, "NEUTRAL")`` rather than the raw
base, because the scorer runs that call too: ``NEUTRAL`` applies no tilt but
still runs the iterative component cap.
"""
from __future__ import annotations

import math
from typing import Any, Final

from open_prep.technical_analysis import resolve_regime_weights

#: The regime ``score_candidate`` always resolves in production (see above).
SCORING_REGIME: Final[str] = "NEUTRAL"

#: Weight key -> the ``score_breakdown`` component that weight scales.
#: Exactly the five weights ``resolve_regime_weights`` tilts.
SHADOW_COMPONENTS: Final[dict[str, str]] = {
    "gap": "gap_component",
    "gap_sector_relative": "gap_sector_rel_component",
    "rvol": "rvol_component",
    "momentum_z": "momentum_component",
    "ext_hours": "ext_hours_component",
}


def _finite(value: Any) -> float | None:
    """Return *value* as a float, or ``None`` if it is not a finite number."""
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    out = float(value)
    if not math.isfinite(out):
        return None
    return out


def compute_regime_weight_shadow(
    row: dict[str, Any],
    measured_regime: Any,
    *,
    base_weights: dict[str, float],
) -> dict[str, Any]:
    """Return what *measured_regime* would have changed for *row*.

    Parameters
    ----------
    row:
        A ranked candidate carrying the scorer's ``score_breakdown``.  It is
        read, never mutated.
    measured_regime:
        The regime derived from measured ADX / BB width in the enrichment
        stage.  Non-string / empty values are treated as ``NEUTRAL``.
    base_weights:
        The weight set the scorer actually used for this run, so the delta
        reflects production rather than the module defaults.

    Returns
    -------
    dict
        ``score_delta`` is the additive change to the composite score.  The
        multiplicative haircuts (counter-trend, low-tier-news) scale the
        baseline and the shadow identically, so they are omitted.
        ``unresolved`` lists every component that could not be reconstructed —
        those are never silently counted as zero change.
    """
    regime = measured_regime if isinstance(measured_regime, str) else ""
    regime = regime.strip().upper()
    if not regime:
        regime = SCORING_REGIME

    baseline = resolve_regime_weights(dict(base_weights), SCORING_REGIME)
    measured = resolve_regime_weights(dict(base_weights), regime)

    raw_breakdown = row.get("score_breakdown")
    breakdown: dict[str, Any] = raw_breakdown if isinstance(raw_breakdown, dict) else {}

    component_delta: dict[str, float] = {}
    weight_delta: dict[str, float] = {}
    unresolved: list[str] = []
    score_delta = 0.0

    for weight_key, component_key in SHADOW_COMPONENTS.items():
        w_base = _finite(baseline.get(weight_key))
        w_measured = _finite(measured.get(weight_key))
        if w_base is None or w_measured is None:
            unresolved.append(weight_key)
            continue
        weight_delta[weight_key] = round(w_measured - w_base, 6)

        component = _finite(breakdown.get(component_key))
        if component is None:
            unresolved.append(component_key)
            continue
        if w_base == 0.0:
            # component is 0 by construction, so the feature value — and with
            # it the shadow contribution — is unrecoverable from the row.
            unresolved.append(component_key)
            continue

        delta = component * (w_measured / w_base) - component
        component_delta[component_key] = round(delta, 6)
        score_delta += delta

    return {
        "regime_at_scoring": SCORING_REGIME,
        "measured_regime": regime,
        "would_change_score": bool(component_delta) and score_delta != 0.0,
        "score_delta": round(score_delta, 6),
        "component_delta": component_delta,
        "weight_delta": weight_delta,
        "unresolved": unresolved,
    }
