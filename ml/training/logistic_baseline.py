"""Pure-numpy logistic regression baseline (always-on, no heavy deps)."""
from __future__ import annotations

from typing import Any

import numpy as np

from ml.training.base import BaseFamilyTrainer


def _sigmoid(z: np.ndarray) -> np.ndarray:
    out = np.empty_like(z, dtype=float)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


class LogisticBaseline(BaseFamilyTrainer):
    """L2-regularised logistic regression with batch gradient descent.

    Deterministic given a seed; trains in O(iterations * n * d) and is fast
    enough to be the always-on default fallback for live-data smoke tests.
    """

    backend = "logistic"

    def __init__(
        self,
        *,
        n_folds: int = 5,
        embargo: int = 1,
        seed: int = 0,
        l2: float = 1e-2,
        learning_rate: float = 0.05,
        max_iter: int = 500,
        tol: float = 1e-6,
    ) -> None:
        super().__init__(n_folds=n_folds, embargo=embargo, seed=seed)
        self.l2 = float(l2)
        self.learning_rate = float(learning_rate)
        self.max_iter = int(max_iter)
        self.tol = float(tol)

    def _fit_one(self, X: np.ndarray, y: np.ndarray) -> Any:
        rng = np.random.default_rng(self.seed)
        n, d = X.shape
        # Standardise (mean/std persisted in payload).
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std < 1e-9] = 1.0
        Xn = (X - mean) / std
        # Augment with bias column.
        Xb = np.hstack([Xn, np.ones((n, 1))])
        w = rng.normal(0.0, 0.01, size=Xb.shape[1])
        prev_loss = np.inf
        for _ in range(self.max_iter):
            z = Xb @ w
            p = _sigmoid(z)
            grad = Xb.T @ (p - y) / n + self.l2 * np.concatenate([w[:-1], [0.0]])
            w -= self.learning_rate * grad
            # log loss
            eps = 1e-15
            p_clip = np.clip(p, eps, 1.0 - eps)
            loss = -float(np.mean(y * np.log(p_clip) + (1.0 - y) * np.log(1.0 - p_clip)))
            if abs(prev_loss - loss) < self.tol:
                break
            prev_loss = loss
        return {"w": w, "mean": mean, "std": std}

    def _predict_proba(self, payload: Any, X: np.ndarray) -> np.ndarray:
        Xn = (X - payload["mean"]) / payload["std"]
        Xb = np.hstack([Xn, np.ones((Xn.shape[0], 1))])
        return _sigmoid(Xb @ payload["w"])


__all__ = ["LogisticBaseline"]
