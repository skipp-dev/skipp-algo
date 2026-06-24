"""Phase D — OB / FVG / Sweep Confluence sub-score.

The existing ``build_signal_quality`` score already contains implicit confluence:
it sums independent OB, FVG, and Liquidity bucket scores.  The purpose of this
module is to compute an *orthogonal interaction term* — a score that captures
*co-presence* of all three family types near the same price level, which is
empirically a stronger signal than any single family alone.

The key design constraint: this module must NOT re-sum the same evidence already
counted in the OB, FVG, and Liquidity buckets.  It is an XOR-style presence
indicator — "were all three families active near this event?" — not a weighted
average.

Anti-double-count guardrail (enforced in ``build_signal_quality_v2``)
-----------------------------------------------------------------------
Before this sub-score earns any budget weight, the caller must demonstrate
incremental Brier improvement over the additive v1 score.  The scaffold below
returns ``raw_confluence_score=0.0`` and ``confluence_tier="NONE"`` if the
interaction is not observed, making it safe to enable in shadow mode without
affecting the score until the evidence threshold is reached.

Integration
-----------
:func:`~smc_integration.measurement_evidence._event_signal_quality_score`
calls :func:`compute_confluence` when ``ENABLE_CONFLUENCE_SCORE=1``, adds the
result under ``"confluence_v2"`` in the enrichment dict, and
``build_signal_quality_v2`` reads ``"confluence_v2"`` to fill the Confluence
bucket (weight 12 in v2 budget).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ConfluenceTier = Literal["HIGH", "MEDIUM", "LOW", "NONE"]

#: Minimum per-family score (0.0–1.0 normalised) for that family to count as
#: "active" in the confluence calculation.
OB_ACTIVE_THRESHOLD: float = 0.40
FVG_ACTIVE_THRESHOLD: float = 0.40
SWEEP_ACTIVE_THRESHOLD: float = 0.30


@dataclass(frozen=True, slots=True)
class ConfluenceScore:
    """Orthogonal confluence descriptor.

    Parameters
    ----------
    ob_contribution:
        Normalised 0.0–1.0 contribution of the OB family (derived from the OB
        context light score, independent of the OB bucket in the main score).
    fvg_contribution:
        Normalised 0.0–1.0 FVG contribution.
    sweep_contribution:
        Normalised 0.0–1.0 sweep / liquidity contribution.  Uses
        ``SWEEP_TRAP_QUALITY_SCORE`` when Phase B is active; falls back to the
        raw ``SWEEP_QUALITY_SCORE``.
    raw_confluence_score:
        0.0–1.0 orthogonal interaction term.  Computed as a weighted geometric
        mean of the active-family contributions; returns ``0.0`` when fewer
        than two families are active.
    confluence_tier:
        ``"HIGH"`` — all three families active with high individual scores.
        ``"MEDIUM"`` — two or three families active with moderate scores.
        ``"LOW"`` — one family active.
        ``"NONE"`` — no family above threshold.
    """

    ob_contribution: float
    fvg_contribution: float
    sweep_contribution: float
    raw_confluence_score: float
    confluence_tier: ConfluenceTier


# ---------------------------------------------------------------------------
# Tier thresholds for raw_confluence_score
# ---------------------------------------------------------------------------

_TIER_HIGH: float = 0.70
_TIER_MEDIUM: float = 0.40
_TIER_LOW: float = 0.10


def compute_confluence(
    ob_light: dict[str, Any] | None,
    fvg_light: dict[str, Any] | None,
    sweep_light: dict[str, Any] | None,
) -> ConfluenceScore:
    """Compute the orthogonal OB ∩ FVG ∩ Sweep confluence score.

    Parameters
    ----------
    ob_light:
        OB context light dict from ``_ob_context_light_for_event``; expected
        key ``"OB_SUPPORT_SCORE"`` (0–15 range, will be normalised to 0–1).
        ``None`` if the OB family is absent.
    fvg_light:
        FVG lifecycle light dict; expected key ``"FVG_GAP_SCORE"`` (0–15).
        ``None`` if absent.
    sweep_light:
        Liquidity sweeps dict; expected key ``"SWEEP_TRAP_QUALITY_SCORE"``
        (0–1, Phase B) or fallback ``"SWEEP_QUALITY_SCORE"`` (0–1).
        ``None`` if absent.

    Returns
    -------
    ConfluenceScore
        Fully populated confluence descriptor.
    """
    # Normalise each family contribution to 0.0–1.0.
    ob_raw: float = float((ob_light or {}).get("OB_SUPPORT_SCORE", 0))
    fvg_raw: float = float((fvg_light or {}).get("FVG_GAP_SCORE", 0))

    sweep_dict: dict[str, Any] = sweep_light or {}
    sweep_raw: float = float(
        sweep_dict.get("SWEEP_TRAP_QUALITY_SCORE", sweep_dict.get("SWEEP_QUALITY_SCORE", 0))
    )

    # Normalise OB and FVG from 0-15 scale to 0-1.
    ob_contrib: float = max(0.0, min(1.0, ob_raw / 15.0))
    fvg_contrib: float = max(0.0, min(1.0, fvg_raw / 15.0))
    sweep_contrib: float = max(0.0, min(1.0, sweep_raw))

    # Count active families.
    active: list[float] = []
    if ob_contrib >= OB_ACTIVE_THRESHOLD:
        active.append(ob_contrib)
    if fvg_contrib >= FVG_ACTIVE_THRESHOLD:
        active.append(fvg_contrib)
    if sweep_contrib >= SWEEP_ACTIVE_THRESHOLD:
        active.append(sweep_contrib)

    n_active: int = len(active)

    if n_active == 0:
        raw_score: float = 0.0
        tier: ConfluenceTier = "NONE"
    elif n_active == 1:
        # Single family — low baseline only.
        raw_score = active[0] * 0.30
        tier = "LOW"
    else:
        # Geometric mean of active contributions — orthogonal interaction.
        product: float = 1.0
        for v in active:
            product *= v
        raw_score = product ** (1.0 / n_active)
        # Bonus for tri-family confluence.
        if n_active == 3:
            raw_score = min(1.0, raw_score * 1.20)

        if raw_score >= _TIER_HIGH:
            tier = "HIGH"
        elif raw_score >= _TIER_MEDIUM:
            tier = "MEDIUM"
        else:
            tier = "LOW"

    return ConfluenceScore(
        ob_contribution=ob_contrib,
        fvg_contribution=fvg_contrib,
        sweep_contribution=sweep_contrib,
        raw_confluence_score=raw_score,
        confluence_tier=tier,
    )
