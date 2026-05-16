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

_VALID_DEVICES = {"auto", "cpu", "cuda"}


def _normalise_device(device: str) -> str:
    value = device.strip().lower()
    if value not in _VALID_DEVICES:
        raise ValueError(f"device must be one of {_VALID_DEVICES}, got {device!r}")
    return value


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
        device: str = "auto",
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
        self.requested_device = _normalise_device(device)
        self.resolved_device = "pending"
        self.device_fallback_reason: str | None = None

    def _candidate_devices(self) -> tuple[str, ...]:
        if self.device_fallback_reason is not None and self.resolved_device == "cpu":
            return ("cpu",)
        if self.requested_device == "cpu":
            return ("cpu",)
        if self.requested_device == "cuda":
            return ("cuda", "cpu")
        return ("cuda", "cpu")

    def _classifier_for_device(self, device: str) -> Any:
        params = dict(self.params)
        params["device_type"] = "gpu" if device == "cuda" else "cpu"
        return lgb.LGBMClassifier(**params)

    def _fit_one(self, X: np.ndarray, y: np.ndarray) -> Any:  # pragma: no cover
        last_exc: Exception | None = None
        for device in self._candidate_devices():
            try:
                clf = self._classifier_for_device(device)
                clf.fit(X, y)
                self.resolved_device = device
                if device == "cpu" and self.requested_device == "cuda":
                    self.device_fallback_reason = "requested_cuda_unavailable"
                elif device == "cpu" and self.requested_device == "auto":
                    self.device_fallback_reason = "auto_cuda_unavailable"
                return clf
            except Exception as exc:
                last_exc = exc
                if device == "cpu":
                    break
        if last_exc is None:
            raise RuntimeError("lightgbm training did not start")
        raise RuntimeError(
            f"lightgbm training failed (requested_device={self.requested_device}): {last_exc}"
        ) from last_exc

    @staticmethod
    def _predict_proba(payload: Any, X: np.ndarray) -> np.ndarray:  # pragma: no cover
        return payload.predict_proba(X)[:, 1]


__all__ = ["LGBMFamilyTrainer"]
