"""ML probability-distribution drift detector (mirrors C9 contract)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ml.metrics import population_stability_index


@dataclass(frozen=True)
class MLDriftAlert:
    family: str
    psi: float
    severity: str  # "ok", "warn", "alarm"
    threshold_warn: float
    threshold_alarm: float
    n_reference: int
    n_live: int


class MLDriftDetector:
    """Two-tier PSI detector on calibrated probability outputs."""

    def __init__(self, *, warn: float = 0.10, alarm: float = 0.20, n_bins: int = 10) -> None:
        if not 0 < warn < alarm:
            raise ValueError("require 0 < warn < alarm")
        self.warn = float(warn)
        self.alarm = float(alarm)
        self.n_bins = int(n_bins)

    def evaluate(
        self,
        family: str,
        reference_probs: Sequence[float],
        live_probs: Sequence[float],
    ) -> MLDriftAlert:
        psi = population_stability_index(reference_probs, live_probs, n_bins=self.n_bins)
        if psi >= self.alarm:
            severity = "alarm"
        elif psi >= self.warn:
            severity = "warn"
        else:
            severity = "ok"
        return MLDriftAlert(
            family=family,
            psi=psi,
            severity=severity,
            threshold_warn=self.warn,
            threshold_alarm=self.alarm,
            n_reference=len(reference_probs),
            n_live=len(live_probs),
        )


__all__ = ["MLDriftAlert", "MLDriftDetector"]
