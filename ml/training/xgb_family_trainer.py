"""XGBoost trainer (optional dependency)."""
from __future__ import annotations

from typing import Any

import numpy as np

from ml.training.base import BaseFamilyTrainer

try:  # pragma: no cover - exercised in environments with xgboost
    import xgboost as xgb  # type: ignore

    _HAS_XGB = True
except Exception:  # pragma: no cover - the absence is the tested path locally
    xgb = None  # type: ignore
    _HAS_XGB = False


class XGBFamilyTrainer(BaseFamilyTrainer):
    """Gradient-boosted-tree trainer.

    Falls back to a clear ``RuntimeError`` at instantiation time when xgboost
    is not installed — callers should branch on ``XGBFamilyTrainer.available``
    and use ``LogisticBaseline`` otherwise.
    """

    backend = "xgboost"
    available: bool = _HAS_XGB

    def __init__(
        self,
        *,
        n_folds: int = 5,
        embargo: int = 1,
        seed: int = 0,
        max_depth: int = 4,
        learning_rate: float = 0.05,
        n_estimators: int = 200,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_lambda: float = 1.0,
    ) -> None:
        if not _HAS_XGB:
            raise RuntimeError(
                "xgboost is not installed. Install via 'pip install -r requirements-ml.txt' "
                "or use ml.training.LogisticBaseline."
            )
        super().__init__(n_folds=n_folds, embargo=embargo, seed=seed)
        self.params = {
            "max_depth": int(max_depth),
            "learning_rate": float(learning_rate),
            "n_estimators": int(n_estimators),
            "subsample": float(subsample),
            "colsample_bytree": float(colsample_bytree),
            "reg_lambda": float(reg_lambda),
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "random_state": int(seed),
            "tree_method": "hist",
        }

    def _fit_one(self, X: np.ndarray, y: np.ndarray) -> Any:  # pragma: no cover
        clf = xgb.XGBClassifier(**self.params)
        clf.fit(X, y, verbose=False)
        return clf

    def _predict_proba(self, payload: Any, X: np.ndarray) -> np.ndarray:  # pragma: no cover
        return payload.predict_proba(X)[:, 1]


__all__ = ["XGBFamilyTrainer"]
