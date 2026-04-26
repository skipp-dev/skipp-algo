"""LightGBM trainer (optional dependency)."""
from __future__ import annotations

from typing import Any

import numpy as np

from ml.training.base import BaseFamilyTrainer

try:  # pragma: no cover
    import lightgbm as lgb  # type: ignore

    _HAS_LGB = True
except Exception:  # pragma: no cover
    lgb = None  # type: ignore
    _HAS_LGB = False


class LGBMFamilyTrainer(BaseFamilyTrainer):
    """LightGBM-backed family trainer.

    Branch on ``LGBMFamilyTrainer.available`` to fall back to
    ``LogisticBaseline`` when LightGBM is absent.
    """

    backend = "lightgbm"
    available: bool = _HAS_LGB

    def __init__(
        self,
        *,
        n_folds: int = 5,
        embargo: int = 1,
        seed: int = 0,
        num_leaves: int = 31,
        learning_rate: float = 0.05,
        n_estimators: int = 200,
        feature_fraction: float = 0.8,
        bagging_fraction: float = 0.8,
        reg_lambda: float = 1.0,
    ) -> None:
        if not _HAS_LGB:
            raise RuntimeError(
                "lightgbm is not installed. Install via 'pip install -r requirements-ml.txt' "
                "or use ml.training.LogisticBaseline."
            )
        super().__init__(n_folds=n_folds, embargo=embargo, seed=seed)
        self.params = {
            "num_leaves": int(num_leaves),
            "learning_rate": float(learning_rate),
            "n_estimators": int(n_estimators),
            "feature_fraction": float(feature_fraction),
            "bagging_fraction": float(bagging_fraction),
            "reg_lambda": float(reg_lambda),
            "objective": "binary",
            "metric": "binary_logloss",
            "random_state": int(seed),
            "verbose": -1,
        }

    def _fit_one(self, X: np.ndarray, y: np.ndarray) -> Any:  # pragma: no cover
        clf = lgb.LGBMClassifier(**self.params)
        clf.fit(X, y)
        return clf

    @staticmethod
    def _predict_proba(payload: Any, X: np.ndarray) -> np.ndarray:  # pragma: no cover
        return payload.predict_proba(X)[:, 1]


__all__ = ["LGBMFamilyTrainer"]
