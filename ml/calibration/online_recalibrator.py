"""Online recalibration trigger (PSI-based)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ml.metrics import brier_score, population_stability_index


@dataclass(frozen=True)
class RecalibrationDecision:
    refit: bool
    psi: float
    brier_regret: float
    reason: str


class OnlineRecalibrator:
    """Decides whether the live model's calibrator should be refit.

    Triggers refit when either:
      * PSI(reference_probs, live_probs) > ``psi_threshold``, or
      * Brier-regret > ``brier_regret_threshold``.

    Auto-rollback semantics live one layer up; this class only emits the
    refit decision.
    """

    def __init__(
        self,
        *,
        psi_threshold: float = 0.20,
        brier_regret_threshold: float = 0.02,
        n_bins: int = 10,
    ) -> None:
        self.psi_threshold = float(psi_threshold)
        self.brier_regret_threshold = float(brier_regret_threshold)
        self.n_bins = int(n_bins)

    def evaluate(
        self,
        reference_probs: Sequence[float],
        live_probs: Sequence[float],
        live_outcomes: Sequence[float],
        reference_brier: float,
    ) -> RecalibrationDecision:
        psi = population_stability_index(reference_probs, live_probs, n_bins=self.n_bins)
        live_brier = brier_score(live_outcomes, live_probs)
        regret = live_brier - reference_brier
        if psi > self.psi_threshold:
            return RecalibrationDecision(True, psi, regret, f"psi {psi:.3f} > {self.psi_threshold}")
        if regret > self.brier_regret_threshold:
            return RecalibrationDecision(
                True, psi, regret, f"brier_regret {regret:.4f} > {self.brier_regret_threshold}"
            )
        return RecalibrationDecision(False, psi, regret, "stable")


__all__ = ["OnlineRecalibrator", "RecalibrationDecision"]
