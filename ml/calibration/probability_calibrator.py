"""Calibrators: Platt scaling + isotonic regression (pure numpy)."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

from ml.metrics import brier_score, log_loss


class ProbabilityCalibrator(ABC):
    """Common calibrator interface."""

    name: str = "base"

    @abstractmethod
    def fit(self, raw_scores: Sequence[float], y_true: Sequence[float]) -> ProbabilityCalibrator:
        ...

    @abstractmethod
    def transform(self, raw_scores: Sequence[float]) -> np.ndarray:
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        ...


@dataclass
class PlattCalibrator(ProbabilityCalibrator):
    """Sigmoid (Platt) calibration: P = 1 / (1 + exp(-(a*x + b))).

    Fitted with gradient descent + backtracking line search on the binary
    cross-entropy using Platt-smoothed targets (Lin-Lin-Weng 2007), for up
    to 2000 iterations. Numerically stable for arbitrary score scales.
    """

    a: float = 0.0
    b: float = 0.0
    name: str = "platt"

    def fit(self, raw_scores: Sequence[float], y_true: Sequence[float]) -> PlattCalibrator:
        """Fit on (raw_scores, y_true) via GD + backtracking line search."""
        x = np.asarray(raw_scores, dtype=float)
        y = np.asarray(y_true, dtype=float)
        if x.size == 0:
            raise ValueError("PlattCalibrator.fit: empty raw_scores")
        if x.shape != y.shape:
            raise ValueError(
                f"PlattCalibrator.fit: shape mismatch raw_scores={x.shape} y_true={y.shape}"
            )
        n = float(x.size)
        prior1 = float((y > 0.5).sum())
        prior0 = n - prior1
        hi = (prior1 + 1.0) / (prior1 + 2.0)
        lo = 1.0 / (prior0 + 2.0)
        t = np.where(y > 0.5, hi, lo)

        def stable_sigmoid(z: np.ndarray) -> np.ndarray:
            return np.where(z >= 0, 1.0 / (1.0 + np.exp(-z)), np.exp(z) / (1.0 + np.exp(z)))

        def loss(a_: float, b_: float) -> float:
            z = a_ * x + b_
            log1pexp = np.where(z >= 0, z + np.log1p(np.exp(-z)), np.log1p(np.exp(z)))
            return float(np.sum(log1pexp - t * z))

        a = 0.0
        b = float(np.log((prior0 + 1.0) / (prior1 + 1.0)))
        f_prev = loss(a, b)
        lr = 1.0 / max(1.0, float(np.mean(x * x)) + 1.0)
        for _ in range(2000):
            z = a * x + b
            p = stable_sigmoid(z)
            grad_a = float(np.sum(x * (p - t))) / n
            grad_b = float(np.sum(p - t)) / n
            step = lr
            for _ in range(20):
                a_new = a - step * grad_a
                b_new = b - step * grad_b
                f_new = loss(a_new, b_new)
                if f_new < f_prev - 1e-12:
                    a, b, f_prev = a_new, b_new, f_new
                    lr = min(lr * 1.1, 10.0)
                    break
                step *= 0.5
            else:
                break
            if abs(grad_a) < 1e-8 and abs(grad_b) < 1e-8:
                break
        self.a = float(a)
        self.b = float(b)
        return self

    def transform(self, raw_scores: Sequence[float]) -> np.ndarray:
        x = np.asarray(raw_scores, dtype=float)
        z = self.a * x + self.b
        return np.where(z >= 0, 1.0 / (1.0 + np.exp(-z)), np.exp(z) / (1.0 + np.exp(z)))

    @property
    def version(self) -> str:
        h = hashlib.sha256(f"platt:{self.a:.9f}:{self.b:.9f}".encode()).hexdigest()
        return f"platt-{h[:12]}"


@dataclass
class IsotonicCalibrator(ProbabilityCalibrator):
    """Isotonic regression via Pool-Adjacent-Violators."""

    x_breaks: np.ndarray | None = None
    y_breaks: np.ndarray | None = None
    name: str = "isotonic"

    def fit(self, raw_scores: Sequence[float], y_true: Sequence[float]) -> IsotonicCalibrator:
        x = np.asarray(raw_scores, dtype=float)
        y = np.asarray(y_true, dtype=float)
        if x.size == 0:
            raise ValueError("empty data for isotonic fit")
        # Sort by x, then PAV.
        order = np.argsort(x, kind="mergesort")
        xs = x[order]
        ys = y[order].astype(float).copy()
        weights = np.ones_like(ys)
        # Pool adjacent violators.
        i = 0
        while i < len(ys) - 1:
            if ys[i] > ys[i + 1]:
                # merge into a block
                j = i
                while j >= 0 and ys[j] > ys[j + 1]:
                    new_w = weights[j] + weights[j + 1]
                    new_y = (weights[j] * ys[j] + weights[j + 1] * ys[j + 1]) / new_w
                    ys[j] = new_y
                    ys[j + 1] = new_y
                    weights[j] = new_w
                    weights[j + 1] = new_w
                    j -= 1
                i = max(0, j)
            else:
                i += 1
        # Compress to unique x values.
        uniq_x, inv = np.unique(xs, return_inverse=True)
        agg_y = np.zeros_like(uniq_x, dtype=float)
        cnt = np.zeros_like(uniq_x, dtype=float)
        for k, idx in enumerate(inv):
            agg_y[idx] += ys[k]
            cnt[idx] += 1.0
        agg_y /= np.maximum(cnt, 1.0)
        # Re-enforce monotonic non-decreasing.
        for k in range(1, agg_y.size):
            if agg_y[k] < agg_y[k - 1]:
                agg_y[k] = agg_y[k - 1]
        self.x_breaks = uniq_x
        self.y_breaks = np.clip(agg_y, 0.0, 1.0)
        return self

    def transform(self, raw_scores: Sequence[float]) -> np.ndarray:
        if self.x_breaks is None or self.y_breaks is None:
            raise RuntimeError("calibrator not fitted")
        x = np.asarray(raw_scores, dtype=float)
        return np.interp(
            x,
            self.x_breaks,
            self.y_breaks,
            left=float(self.y_breaks[0]),
            right=float(self.y_breaks[-1]),
        )

    @property
    def version(self) -> str:
        if self.x_breaks is None:
            return "isotonic-unfitted"
        h = hashlib.sha256()
        h.update(self.x_breaks.tobytes())
        h.update(self.y_breaks.tobytes())  # type: ignore[union-attr]
        return f"isotonic-{h.hexdigest()[:12]}"


def evaluate_calibrator(
    cal: ProbabilityCalibrator,
    raw_scores: Sequence[float],
    y_true: Sequence[float],
) -> dict[str, float]:
    p = cal.transform(raw_scores)
    return {"brier": brier_score(y_true, p), "log_loss": log_loss(y_true, p)}


__all__ = [
    "IsotonicCalibrator",
    "PlattCalibrator",
    "ProbabilityCalibrator",
    "evaluate_calibrator",
]
