"""XGBoost trainer (optional dependency)."""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from ml.training.base import BaseFamilyTrainer

try:  # pragma: no cover - exercised in environments with xgboost
    import xgboost as xgb  # type: ignore

    _HAS_XGB = True
except Exception:  # pragma: no cover - the absence is the tested path locally
    xgb = None  # type: ignore
    _HAS_XGB = False

_VALID_DEVICES = {"auto", "cpu", "cuda"}


def _normalise_device(device: str) -> str:
    value = device.strip().lower()
    if value not in _VALID_DEVICES:
        raise ValueError(f"device must be one of {_VALID_DEVICES}, got {device!r}")
    return value


def _coerce_runtime_device(value: object) -> str | None:
    if value is None:
        return None
    normalised = str(value).strip().lower()
    if not normalised:
        return None
    if normalised.startswith("cuda") or normalised.startswith("gpu"):
        return "cuda"
    if normalised.startswith("cpu"):
        return "cpu"
    return None


def _resolved_booster_device(payload: Any) -> str | None:
    if not hasattr(payload, "get_booster"):
        return None

    try:
        booster = payload.get_booster()
    except Exception:
        return None
    if booster is None or not hasattr(booster, "save_config"):
        return None

    try:
        config = json.loads(booster.save_config())
    except Exception:
        return None

    learner = config.get("learner", {}) if isinstance(config, dict) else {}
    generic_param = learner.get("generic_param", {}) if isinstance(learner, dict) else {}
    if not isinstance(generic_param, dict):
        return None
    return _coerce_runtime_device(generic_param.get("device"))


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
        device: str = "auto",
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
        if device == "cuda":
            params["device"] = "cuda"
        else:
            params.pop("device", None)
        return xgb.XGBClassifier(**params)

    def _fit_one(self, X: np.ndarray, y: np.ndarray) -> Any:  # pragma: no cover
        last_exc: Exception | None = None
        for device in self._candidate_devices():
            try:
                clf = self._classifier_for_device(device)
                clf.fit(X, y, verbose=False)
                resolved_device = _resolved_booster_device(clf) or device
                self.resolved_device = resolved_device
                if resolved_device == "cpu" and self.requested_device == "cuda":
                    self.device_fallback_reason = "requested_cuda_unavailable"
                elif resolved_device == "cpu" and self.requested_device == "auto":
                    self.device_fallback_reason = "auto_cuda_unavailable"
                return clf
            except Exception as exc:
                last_exc = exc
                if device == "cpu":
                    break
        if last_exc is None:
            raise RuntimeError("xgboost training did not start")
        raise RuntimeError(
            f"xgboost training failed (requested_device={self.requested_device}): {last_exc}"
        ) from last_exc

    @staticmethod
    def _predict_proba(payload: Any, X: np.ndarray) -> np.ndarray:  # pragma: no cover
        return payload.predict_proba(X)[:, 1]


__all__ = ["XGBFamilyTrainer"]
