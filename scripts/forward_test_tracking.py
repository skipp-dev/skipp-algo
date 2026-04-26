"""Sprint C8.1 — forward-test tracking + dynamic incubation.

Two helpers built on top of the existing :mod:`scripts.run_smc_live_incubation`
phase-criteria framework. Both are pure functions designed to be called
from a paper/live polling loop without coupling to any specific data
backend.

1. **expected_vs_realized_ratio(live_brier, walkforward_brier).**
   Returns the ``live / wf`` ratio. The X2 PromotionGate already
   consumes a ``live_vs_wf_ratio`` blocker (default threshold 1.5);
   this helper centralises the math + edge-cases.

2. **dynamic_incubation_decision(live_metrics, wf_metrics, criteria).**
   The runbook's static 4-week-Phase-A criterion is sound for normal
   PnL-density strategies but wastes calendar time when the strategy
   accumulates the required sample size (and PSR) in fewer days. The
   decision helper returns ``"continue"``, ``"promote"``, or
   ``"demote"`` based on:

     - ``promote`` ⇔ ``n_live >= min_n*`` AND ``psr_live >= psr_wf - margin``
       AND ``min_phase_days`` hit (lower bound is non-negotiable).
     - ``demote`` ⇔ ``expected_vs_realized_ratio > demote_ratio_threshold``
       (live Brier blew through the WF reference).
     - else ``continue``.

Out of scope:
- Mutating the runbook PhasePassCriteria thresholds (they are the
  contract; this helper only adds a faster green path within them).
- Coupling to C12 RL (separate sprint owns its own gate).

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c81
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Decision = Literal["promote", "continue", "demote"]


def expected_vs_realized_ratio(
    live_brier: float,
    walkforward_brier: float,
) -> float | None:
    """Return ``live / wf`` Brier ratio, or ``None`` if undefined.

    A ratio > 1 means live calibration is *worse* than walk-forward.
    Returns ``None`` when ``walkforward_brier <= 0`` or either input is
    not finite — undefined ratios must not be silently coerced to a
    benign value because PromotionGate would then read them as "ok".
    """
    import math

    if not math.isfinite(live_brier) or not math.isfinite(walkforward_brier):
        return None
    if walkforward_brier <= 0.0:
        return None
    return live_brier / walkforward_brier


@dataclass(frozen=True)
class DynamicIncubationCriteria:
    """Numeric policy for the dynamic-stop helper.

    ``min_phase_days`` is a hard lower bound (calendar safety); the
    promotion path only short-circuits the *upper* bound, never the
    lower. This protects against single-week luck.
    """

    min_phase_days: int = 28
    min_trades_closed: int = 30
    psr_margin: float = 0.05
    demote_ratio_threshold: float = 1.5  # mirrors X2 default


def dynamic_incubation_decision(
    *,
    days_in_phase: int,
    n_trades_closed: int,
    psr_live: float | None,
    psr_walkforward: float | None,
    live_brier: float | None = None,
    walkforward_brier: float | None = None,
    criteria: DynamicIncubationCriteria | None = None,
) -> tuple[Decision, list[str]]:
    """Decide between promote/continue/demote and return the blocker list.

    The blocker list is intended for the operator's dashboard so the
    decision is auditable.
    """
    crit = criteria or DynamicIncubationCriteria()
    blockers: list[str] = []

    # Demote first — a blown live/wf ratio overrides any pending promote.
    if live_brier is not None and walkforward_brier is not None:
        ratio = expected_vs_realized_ratio(live_brier, walkforward_brier)
        if ratio is None:
            # Both inputs were provided but the ratio is undefined
            # (walkforward_brier <= 0 or non-finite). Treat as a blocker
            # rather than silently allowing promotion.
            blockers.append("live_vs_wf_brier_ratio_undefined")
        elif ratio > crit.demote_ratio_threshold:
            return (
                "demote",
                [
                    f"live_vs_wf_brier_ratio={ratio:.3f} "
                    f"> threshold={crit.demote_ratio_threshold:.3f}"
                ],
            )

    # Hard calendar floor.
    if days_in_phase < crit.min_phase_days:
        blockers.append(
            f"days_in_phase={days_in_phase} < min={crit.min_phase_days}"
        )
    # Sample-size floor.
    if n_trades_closed < crit.min_trades_closed:
        blockers.append(
            f"n_trades_closed={n_trades_closed} < min={crit.min_trades_closed}"
        )
    # PSR threshold.
    if psr_live is None or psr_walkforward is None:
        blockers.append("psr_live_or_walkforward_missing")
    else:
        if psr_live < psr_walkforward - crit.psr_margin:
            blockers.append(
                f"psr_live={psr_live:.3f} < "
                f"psr_walkforward={psr_walkforward:.3f} - margin={crit.psr_margin:.3f}"
            )

    if not blockers:
        return ("promote", [])
    return ("continue", blockers)


__all__ = [
    "Decision",
    "DynamicIncubationCriteria",
    "dynamic_incubation_decision",
    "expected_vs_realized_ratio",
]
