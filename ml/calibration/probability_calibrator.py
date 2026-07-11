"""Calibrators: Platt scaling + isotonic regression (pure numpy)."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

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
        # Aggregate ties in x into one weighted point (weighted mean, summed
        # weight), then run PAV on the unique-x sequence. Aggregating first is
        # what makes the pooled means correct — pooling raw duplicate rows and
        # only afterwards averaging (the previous bug) double-counts weight.
        order = np.argsort(x, kind="mergesort")
        xs = x[order]
        ys = y[order].astype(float)
        uniq_x, inv, counts = np.unique(xs, return_inverse=True, return_counts=True)
        sum_y = np.zeros(uniq_x.size, dtype=float)
        np.add.at(sum_y, inv, ys)
        agg_y = sum_y / counts  # mean label per unique score
        # Pool-Adjacent-Violators with proper block bookkeeping: each block
        # carries its pooled value, total weight, and member count. A block is
        # merged left only while it violates monotonicity; the pooled value is
        # the weight-preserving mean, so the fitted total equals the label total.
        block_val: list[float] = []
        block_w: list[float] = []
        block_n: list[int] = []
        for val, wgt in zip(agg_y, counts.astype(float)):
            cur_v = float(val)
            cur_w = float(wgt)
            cur_n = 1
            while block_val and block_val[-1] > cur_v:
                pv = block_val.pop()
                pw = block_w.pop()
                pn = block_n.pop()
                cur_v = (pv * pw + cur_v * cur_w) / (pw + cur_w)
                cur_w += pw
                cur_n += pn
            block_val.append(cur_v)
            block_w.append(cur_w)
            block_n.append(cur_n)
        y_fit = np.empty(uniq_x.size, dtype=float)
        pos = 0
        for v, n in zip(block_val, block_n):
            y_fit[pos : pos + n] = v
            pos += n
        self.x_breaks = uniq_x
        self.y_breaks = np.clip(y_fit, 0.0, 1.0)
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
