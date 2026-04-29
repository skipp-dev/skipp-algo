"""Conformal Prediction wrappers (Sprint C10.1).

Brier-style calibration tunes probabilities but offers no formal
*coverage* guarantee — i.e. no statement of "this prediction set
contains the true label with probability ≥ 1-α". Conformal Prediction
(Vovk, Shafer, Wasserman 2005) closes that gap.

This module ships:

- ``SplitConformalClassifier`` (Vovk-style split conformal) — calibrates
  on a held-out set, returns a prediction set per row plus a coverage
  estimator. Distribution-free, exchangeability-only.

- ``AdaptiveConformalClassifier`` (Romano-Patterson, "Adaptive
  Prediction Sets" 2020) — class-conditional conformity score that
  produces tighter sets while preserving marginal coverage.

Numpy-only.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c101
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ConformalReport:
    alpha: float
    n_calibration: int
    empirical_coverage: float
    average_set_size: float
    quantile: float


def _empirical_coverage(sets: list[set[int]], y: np.ndarray) -> float:
    return float(
        sum(1 for s, label in zip(sets, y, strict=False) if int(label) in s) / max(1, y.size)
    )


def _average_set_size(sets: list[set[int]]) -> float:
    if not sets:
        return 0.0
    return float(sum(len(s) for s in sets) / len(sets))


@dataclass
class SplitConformalClassifier:
    """Vovk split-conformal classifier wrapper.

    Wraps any binary classifier exposing ``predict_proba(X) -> (n, 2)``
    or ``(n,)`` for the positive-class probability. ``calibrate(...)``
    fits the conformity-score quantile on a held-out set; ``predict_set``
    returns per-row prediction *sets* (subsets of {0, 1}) at miscoverage
    α.

    Coverage guarantee under exchangeability:
    ``P(y in set) ≥ 1 - α``.
    """

    alpha: float = 0.1
    quantile_: float | None = None
    n_calibration_: int = 0

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha < 1.0):
            raise ValueError(f"alpha must be in (0, 1), got {self.alpha}")

    def _to_p1(self, probs: np.ndarray) -> np.ndarray:
        probs = np.asarray(probs, dtype=float)
        if probs.ndim == 2 and probs.shape[1] == 2:
            return probs[:, 1]
        if probs.ndim == 1:
            return probs
        raise ValueError(f"Unsupported probs shape {probs.shape}")

    def calibrate(self, probs_cal: np.ndarray, y_cal: np.ndarray) -> SplitConformalClassifier:
        p1 = self._to_p1(probs_cal)
        y = np.asarray(y_cal, dtype=int)
        if p1.shape[0] != y.shape[0]:
            raise ValueError("calibration prob/label length mismatch")
        if p1.size == 0:
            raise ValueError("calibration set is empty")
        # Conformity score: 1 - p_correct = "how non-conforming was this".
        scores = np.where(y == 1, 1.0 - p1, p1)
        n = scores.size
        # Finite-sample quantile (Vovk):  ceil((n+1)(1-alpha)) / n
        k = int(np.ceil((n + 1) * (1.0 - self.alpha)))
        k = min(max(k, 1), n)
        self.quantile_ = float(np.sort(scores)[k - 1])
        self.n_calibration_ = int(n)
        return self

    def predict_set(self, probs_test: np.ndarray) -> list[set[int]]:
        if self.quantile_ is None:
            raise RuntimeError("SplitConformalClassifier is not calibrated")
        p1 = self._to_p1(probs_test)
        q = self.quantile_
        out: list[set[int]] = []
        for p in p1:
            s: set[int] = set()
            # label==1: nonconformity = 1-p1; include if 1-p1 <= q
            if (1.0 - p) <= q:
                s.add(1)
            # label==0: nonconformity = p1; include if p1 <= q
            if p <= q:
                s.add(0)
            if not s:
                # Forbidden by construction (q in [0, 1]); guard belt+suspenders.
                s.add(1 if p >= 0.5 else 0)
            out.append(s)
        return out

    def evaluate(self, probs_test: np.ndarray, y_test: np.ndarray) -> ConformalReport:
        sets = self.predict_set(probs_test)
        return ConformalReport(
            alpha=self.alpha,
            n_calibration=self.n_calibration_,
            empirical_coverage=_empirical_coverage(sets, np.asarray(y_test)),
            average_set_size=_average_set_size(sets),
            quantile=float(self.quantile_) if self.quantile_ is not None else float("nan"),
        )


@dataclass
class AdaptiveConformalClassifier:
    """Adaptive conformal (Romano-Patterson 2020) — class-conditional quantile.

    Computes a separate conformity threshold per class on the calibration
    set. Tightens prediction sets relative to split-conformal when one
    class is much rarer than the other (typical in setup-promotion
    pipelines), at the cost of one extra hyperparameter (per-class α).
    """

    alpha: float = 0.1
    quantile_pos_: float | None = None
    quantile_neg_: float | None = None
    n_calibration_: int = 0

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha < 1.0):
            raise ValueError(f"alpha must be in (0, 1), got {self.alpha}")

    def _to_p1(self, probs: np.ndarray) -> np.ndarray:
        probs = np.asarray(probs, dtype=float)
        if probs.ndim == 1:
            return probs
        if probs.ndim == 2 and probs.shape[1] == 2:
            return probs[:, 1]
        raise ValueError(f"Unsupported probs shape {probs.shape}")

    def _q(self, scores: np.ndarray) -> float:
        n = scores.size
        if n == 0:
            return 1.0
        k = int(np.ceil((n + 1) * (1.0 - self.alpha)))
        k = min(max(k, 1), n)
        return float(np.sort(scores)[k - 1])

    def calibrate(
        self, probs_cal: np.ndarray, y_cal: np.ndarray
    ) -> AdaptiveConformalClassifier:
        p1 = self._to_p1(probs_cal)
        y = np.asarray(y_cal, dtype=int)
        if p1.shape[0] != y.shape[0]:
            raise ValueError("calibration prob/label length mismatch")
        pos_scores = 1.0 - p1[y == 1]
        neg_scores = p1[y == 0]
        self.quantile_pos_ = self._q(pos_scores)
        self.quantile_neg_ = self._q(neg_scores)
        self.n_calibration_ = int(y.size)
        return self

    def predict_set(self, probs_test: np.ndarray) -> list[set[int]]:
        if self.quantile_pos_ is None or self.quantile_neg_ is None:
            raise RuntimeError("AdaptiveConformalClassifier is not calibrated")
        p1 = self._to_p1(probs_test)
        out: list[set[int]] = []
        for p in p1:
            s: set[int] = set()
            if (1.0 - p) <= self.quantile_pos_:
                s.add(1)
            if p <= self.quantile_neg_:
                s.add(0)
            if not s:
                s.add(1 if p >= 0.5 else 0)
            out.append(s)
        return out

    def evaluate(self, probs_test: np.ndarray, y_test: np.ndarray) -> ConformalReport:
        sets = self.predict_set(probs_test)
        return ConformalReport(
            alpha=self.alpha,
            n_calibration=self.n_calibration_,
            empirical_coverage=_empirical_coverage(sets, np.asarray(y_test)),
            average_set_size=_average_set_size(sets),
            quantile=float("nan"),  # two quantiles; surface separately if needed
        )


__all__ = [
    "AdaptiveConformalClassifier",
    "ConformalReport",
    "SplitConformalClassifier",
]
