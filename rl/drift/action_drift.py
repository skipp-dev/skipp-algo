"""PSI-based drift detection on RL ExecutionAction distributions.

Monitors the live distribution of ``slice_size`` choices vs the reference
distribution captured during training. Mirrors ``ml.drift.MLDriftDetector``
but on action quantiles rather than feature/probability bins.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from collections.abc import Sequence

import numpy as np


def _psi(reference: np.ndarray, live: np.ndarray, n_bins: int) -> float:
    """Population Stability Index on equal-frequency reference quantiles.

    Vendored locally so the rl/ pipeline has no soft dependency on the
    optional ml/ package; identical formula to ``ml.metrics.population_stability_index``.
    """
    reference = np.asarray(reference, dtype=float)
    live = np.asarray(live, dtype=float)
    if reference.size == 0 or live.size == 0:
        return 0.0
    qs = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.quantile(reference, qs)
    # Guard against repeated edges from concentrated/constant references —
    # ``np.histogram`` requires strictly-increasing bins.
    edges = np.unique(edges)
    if edges.size <= 1:
        edges = np.array([-np.inf, np.inf], dtype=float)
    else:
        edges = edges.astype(float, copy=True)
        edges[0] = -np.inf
        edges[-1] = np.inf
    eps = 1e-6
    ref_hist, _ = np.histogram(reference, bins=edges)
    live_hist, _ = np.histogram(live, bins=edges)
    ref_p = ref_hist / max(ref_hist.sum(), 1) + eps
    live_p = live_hist / max(live_hist.sum(), 1) + eps
    return float(np.sum((live_p - ref_p) * np.log(live_p / ref_p)))

Severity = Literal["ok", "warn", "alarm"]


@dataclass(frozen=True)
class RLDriftAlert:
    psi: float
    severity: Severity
    threshold_warn: float
    threshold_alarm: float
    n_reference: int
    n_live: int


@dataclass
class RLDriftDetector:
    warn: float = 0.15
    alarm: float = 0.20
    n_bins: int = 10

    def check(self, reference_slices: Sequence[float], live_slices: Sequence[float]) -> RLDriftAlert:
        ref = np.asarray(reference_slices, dtype=float)
        live = np.asarray(live_slices, dtype=float)
        psi = float(_psi(ref, live, n_bins=self.n_bins))
        if psi >= self.alarm:
            sev: Severity = "alarm"
        elif psi >= self.warn:
            sev = "warn"
        else:
            sev = "ok"
        return RLDriftAlert(
            psi=psi,
            severity=sev,
            threshold_warn=self.warn,
            threshold_alarm=self.alarm,
            n_reference=int(ref.size),
            n_live=int(live.size),
        )


__all__ = ["RLDriftAlert", "RLDriftDetector"]
