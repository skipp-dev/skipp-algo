"""Stacked meta-learner over per-family probabilities (Sprint C10.1).

The C10 ML layer produces one probability per setup family
(BOS/CHOCH/OB/FVG-quality). When two families fire on the same bar
their information is currently combined by ``mean(probs)`` — fine when
the families are independent, lossy when their joint occurrence is
itself predictive (e.g. BOS + OB co-occurrence is a stronger setup
than either alone).

This module fits a *constrained logistic meta-learner* over the
per-family probability vector, with weights constrained to non-negative
and summing to 1 plus an optional intercept-free flag. Constraints
keep the meta-learner monotone and interpretable while still letting
it down-weight noisy families and up-weight informative ones.

Numpy-only (no scipy). Solves the constrained LR via projected
gradient descent — small enough for the per-family vector dimension
(K=4 today) that convergence is trivial.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c101
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class MetaLearnerReport:
    weights: tuple[float, ...]
    intercept: float
    baseline_brier: float
    stacked_brier: float
    brier_improvement_pct: float
    n_train: int
    n_val: int
    n_iter: int
    converged: bool


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


def _project_simplex(w: np.ndarray) -> np.ndarray:
    """Project w onto the probability simplex {w >= 0, sum w = 1} (Duchi08)."""
    n = w.size
    u = np.sort(w)[::-1]
    cssv = np.cumsum(u) - 1.0
    idx = np.arange(1, n + 1)
    rho = np.where(u - cssv / idx > 0)[0]
    if rho.size == 0:
        return np.full(n, 1.0 / n)
    rho_max = rho[-1]
    theta = cssv[rho_max] / float(rho_max + 1)
    return np.maximum(w - theta, 0.0)


def _brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1.0 - eps)
    return np.log(p / (1.0 - p))


def mean_of_family_baseline(P: np.ndarray) -> np.ndarray:
    """Per-row mean across families — the C10 default combiner."""
    if P.size == 0:
        return np.zeros(0)
    return P.mean(axis=1)


@dataclass
class StackedMetaLearner:
    """Constrained logistic meta-learner over per-family probabilities.

    Parameters
    ----------
    learning_rate, max_iter, tol:
        Projected-gradient hyperparameters.
    fit_intercept:
        When True learns an unconstrained scalar bias; weights still
        live on the simplex. Defaults to True.
    seed:
        Reproducible weight init.
    """

    learning_rate: float = 0.1
    max_iter: int = 2000
    tol: float = 1e-7
    fit_intercept: bool = True
    seed: int = 0
    weights_: np.ndarray | None = None
    intercept_: float = 0.0
    n_iter_: int = 0
    converged_: bool = False

    def fit(self, P: np.ndarray, y: np.ndarray) -> "StackedMetaLearner":
        """Fit on (n_samples, n_families) probabilities and binary labels."""
        P = np.asarray(P, dtype=float)
        y = np.asarray(y, dtype=float)
        if P.ndim != 2:
            raise ValueError(f"P must be 2D, got shape {P.shape}")
        if P.shape[0] != y.shape[0]:
            raise ValueError("len(P) must equal len(y)")
        n, k = P.shape
        rng = np.random.default_rng(self.seed)
        # Stack on logits so weights act in log-odds space; with w=(1,0,...)
        # and b=0 the meta-learner exactly reproduces the leading family's
        # probability (instead of sigmoid-compressing it).
        L = _logit(P)
        w = np.full(k, 1.0 / k)
        b = 0.0
        prev_loss = np.inf
        converged = False
        for it in range(1, self.max_iter + 1):
            z = L @ w + b
            p = _sigmoid(z)
            err = p - y
            grad_w = (L.T @ err) / max(1, n)
            grad_b = float(np.mean(err))
            w_new = w - self.learning_rate * grad_w
            w_new = _project_simplex(w_new)
            b_new = b - self.learning_rate * grad_b if self.fit_intercept else 0.0
            # Tiny noise on first iter prevents deterministic ties when
            # all families produce identical probs.
            if it == 1:
                w_new = _project_simplex(
                    w_new + 1e-9 * rng.standard_normal(k)
                )
            loss = float(
                np.mean(
                    -y * np.log(np.clip(p, 1e-12, 1.0))
                    - (1.0 - y) * np.log(np.clip(1.0 - p, 1e-12, 1.0))
                )
            )
            if abs(prev_loss - loss) < self.tol:
                converged = True
                w, b = w_new, b_new
                self.n_iter_ = it
                break
            w, b = w_new, b_new
            prev_loss = loss
        else:
            self.n_iter_ = self.max_iter
        self.weights_ = w
        self.intercept_ = float(b)
        self.converged_ = converged
        return self

    def predict_proba(self, P: np.ndarray) -> np.ndarray:
        if self.weights_ is None:
            raise RuntimeError("StackedMetaLearner is not fitted")
        P = np.asarray(P, dtype=float)
        L = _logit(P)
        return _sigmoid(L @ self.weights_ + self.intercept_)

    def evaluate(
        self, P_val: np.ndarray, y_val: np.ndarray, *, n_train: int
    ) -> MetaLearnerReport:
        if self.weights_ is None:
            raise RuntimeError("StackedMetaLearner is not fitted")
        baseline = mean_of_family_baseline(P_val)
        stacked = self.predict_proba(P_val)
        b_baseline = _brier(y_val, baseline)
        b_stacked = _brier(y_val, stacked)
        improvement = (
            (b_baseline - b_stacked) / b_baseline * 100.0
            if b_baseline > 0.0
            else 0.0
        )
        return MetaLearnerReport(
            weights=tuple(float(x) for x in self.weights_),
            intercept=float(self.intercept_),
            baseline_brier=b_baseline,
            stacked_brier=b_stacked,
            brier_improvement_pct=float(improvement),
            n_train=int(n_train),
            n_val=int(P_val.shape[0]),
            n_iter=int(self.n_iter_),
            converged=bool(self.converged_),
        )


__all__ = ["MetaLearnerReport", "StackedMetaLearner", "mean_of_family_baseline"]
