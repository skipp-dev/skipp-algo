"""Almgren-Chriss style slippage / market-impact calibrator.

Pure-numpy Bayesian linear regression with a half-normal prior on the impact
coefficients (preventing negative impact estimates).

Posterior:
    beta | y, X ~ N(mu, Sigma)
where::

    Sigma = (X^T X / sigma^2 + Lambda)^{-1}
    mu    = Sigma (X^T y / sigma^2)

The half-normal prior is implemented by simply rejecting negative coefficients
in the posterior mean (the half-normal restricted to the positive orthant);
posterior covariance is the symmetric Gaussian one (good enough for a
deployment-ready scaffolding — replace with full HMC if needed later).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from rl.types import SlippageEstimate


@dataclass
class AlmgrenChrissCalibrator:
    """Bayesian linear-regression slippage estimator.

    Coefficients (in order) correspond to the feature vector emitted by
    ``TradeBlotter.to_features_targets``:

    - ``beta_perm`` : permanent impact (signed % of volume).
    - ``beta_temp`` : temporary impact (sqrt of duration).
    - ``beta_abs``  : convexity term (abs signed % of volume).
    """

    prior_precision: float = 1.0
    noise_variance: float = 25.0  # 5 bps stdev default
    fitted: bool = False
    mean_: np.ndarray | None = None
    cov_: np.ndarray | None = None
    n_train_: int = 0

    def fit(self, X: np.ndarray, y_bps: np.ndarray) -> AlmgrenChrissCalibrator:
        if self.prior_precision <= 0:
            raise ValueError("prior_precision must be > 0")
        if self.noise_variance <= 0:
            # Zero observation noise is a degenerate Bayesian prior
            # (infinite-precision likelihood); the previous defensive
            # ``max(noise_variance, 1e-9)`` floor silently produced a
            # near-singular Sigma_inv. Require strict positivity instead.
            raise ValueError("noise_variance must be > 0")
        X = np.asarray(X, dtype=float)
        y = np.asarray(y_bps, dtype=float)
        if X.ndim != 2 or X.shape[0] != y.shape[0]:
            raise ValueError(f"shape mismatch: X={X.shape} y={y.shape}")
        if X.shape[0] < X.shape[1]:
            raise ValueError("need at least as many trades as features")
        d = X.shape[1]
        Lambda = self.prior_precision * np.eye(d)
        sigma2 = self.noise_variance
        Sigma_inv = X.T @ X / sigma2 + Lambda
        rhs = (X.T @ y) / sigma2
        try:
            chol = np.linalg.cholesky(Sigma_inv)
            mu = np.linalg.solve(chol.T, np.linalg.solve(chol, rhs))
            Sigma = np.linalg.solve(chol.T, np.linalg.solve(chol, np.eye(d)))
        except np.linalg.LinAlgError:
            mu = np.linalg.solve(Sigma_inv, rhs)
            Sigma = np.linalg.solve(Sigma_inv, np.eye(d))
        # Apply half-normal prior by clipping at zero on the impact dims.
        mu = np.maximum(mu, 0.0)
        self.mean_ = mu
        self.cov_ = Sigma
        self.fitted = True
        self.n_train_ = int(X.shape[0])
        return self

    def predict_bps(self, x: np.ndarray) -> SlippageEstimate:
        if not self.fitted or self.mean_ is None or self.cov_ is None:
            raise RuntimeError("calibrator not fitted")
        x = np.asarray(x, dtype=float).reshape(-1)
        if x.shape[0] != self.mean_.shape[0]:
            raise ValueError(f"feature dim mismatch: x={x.shape[0]} fit={self.mean_.shape[0]}")
        mean = float(x @ self.mean_)
        var = float(x @ self.cov_ @ x) + self.noise_variance
        std = math.sqrt(max(var, 0.0))
        # Permanent impact: signed pct of volume term (index 0).
        # Temporary impact: sqrt-duration term (index 1).
        perm = float(self.mean_[0] * x[0]) if x.shape[0] >= 1 else 0.0
        temp = float(self.mean_[1] * x[1]) if x.shape[0] >= 2 else 0.0
        return SlippageEstimate(
            expected_bps=mean,
            permanent_impact_bps=perm,
            temporary_impact_bps=temp,
            confidence_low_bps=mean - 1.96 * std,
            confidence_high_bps=mean + 1.96 * std,
        )

    def predict_batch_bps(self, X: np.ndarray) -> np.ndarray:
        if not self.fitted or self.mean_ is None:
            raise RuntimeError("calibrator not fitted")
        X = np.asarray(X, dtype=float)
        return X @ self.mean_

    def mae(self, X: np.ndarray, y_bps: np.ndarray) -> float:
        return float(np.mean(np.abs(self.predict_batch_bps(X) - np.asarray(y_bps, float))))

    def rmse(self, X: np.ndarray, y_bps: np.ndarray) -> float:
        diff = self.predict_batch_bps(X) - np.asarray(y_bps, float)
        return float(np.sqrt(np.mean(diff * diff)))


__all__ = ["AlmgrenChrissCalibrator"]
