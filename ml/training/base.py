"""Trainer base classes + shared dataset structure."""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np

from ml.metrics import brier_score, log_loss, roc_auc
from ml.types import EventFamily, TrainingReport
from ml.walkforward import walk_forward_splits


@dataclass(frozen=True)
class FamilyDataset:
    """Per-family training matrix.

    ``X`` shape (n_samples, n_features); ``y`` shape (n_samples,) with values
    in {0, 1}; ``feature_names`` length n_features.
    """

    family: EventFamily
    X: np.ndarray
    y: np.ndarray
    feature_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.X.ndim != 2:
            raise ValueError(f"X must be 2-D, got shape {self.X.shape}")
        if self.y.ndim != 1 or self.y.shape[0] != self.X.shape[0]:
            raise ValueError(f"y shape {self.y.shape} incompatible with X {self.X.shape}")
        if len(self.feature_names) != self.X.shape[1]:
            raise ValueError(
                f"feature_names ({len(self.feature_names)}) must match n_features ({self.X.shape[1]})"
            )

    @property
    def features_sha(self) -> str:
        h = hashlib.sha256()
        h.update(json.dumps(list(self.feature_names), sort_keys=True).encode("utf-8"))
        return h.hexdigest()


@dataclass(frozen=True)
class FittedModel:
    family: EventFamily
    backend: str
    model_version: str
    feature_names: tuple[str, ...]
    payload: Any  # backend-specific (np.ndarray for logistic, Booster for xgb)
    extra: dict[str, Any]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self.extra["predict_proba"](X)


class BaseFamilyTrainer(ABC):
    """Common walk-forward training driver.

    Subclasses implement ``_fit_one`` (single fold) and ``_predict_proba``.
    """

    backend: str = "base"

    def __init__(self, *, n_folds: int = 5, embargo: int = 1, seed: int = 0) -> None:
        self.n_folds = int(n_folds)
        self.embargo = int(embargo)
        self.seed = int(seed)

    @abstractmethod
    def _fit_one(self, X: np.ndarray, y: np.ndarray) -> Any:
        """Fit on a single training split; return backend payload."""

    @staticmethod
    @abstractmethod
    def _predict_proba(payload: Any, X: np.ndarray) -> np.ndarray:
        """Return P(y=1) for each row of X."""

    def fit(self, dataset: FamilyDataset) -> tuple[FittedModel, TrainingReport]:
        X = dataset.X
        y = dataset.y
        folds = walk_forward_splits(
            n_samples=X.shape[0], n_folds=self.n_folds, embargo=self.embargo
        )
        fold_metrics: list[dict[str, float]] = []
        for fold in folds:
            payload = self._fit_one(X[fold.train_idx], y[fold.train_idx])
            preds = self._predict_proba(payload, X[fold.val_idx])
            fold_metrics.append(
                {
                    "n_train": float(fold.train_idx.size),
                    "n_val": float(fold.val_idx.size),
                    "brier": brier_score(y[fold.val_idx], preds),
                    "log_loss": log_loss(y[fold.val_idx], preds),
                    "auc": roc_auc(y[fold.val_idx], preds),
                }
            )
        # Final fit on full series for production payload.
        final_payload = self._fit_one(X, y)
        in_sample = self._predict_proba(final_payload, X)

        def avg(key: str) -> float:
            return float(np.mean([m[key] for m in fold_metrics]))

        version = self._make_version(dataset)

        # ``predict_proba`` closes over the *backend-class* (not ``self``) so
        # the FittedModel artifact stays self-contained: detached from the
        # trainer instance, picklable, and re-bindable to a freshly-imported
        # backend type without keeping the trainer alive.
        backend_predict = type(self)._predict_proba
        fitted = FittedModel(
            family=dataset.family,
            backend=self.backend,
            model_version=version,
            feature_names=dataset.feature_names,
            payload=final_payload,
            extra={
                "predict_proba": _make_predict_proba(backend_predict, final_payload),
                "in_sample_metrics": {
                    "scope": "in_sample_only",
                    "brier": brier_score(y, in_sample),
                },
            },
        )
        report = TrainingReport(
            family=dataset.family,
            n_train=int(X.shape[0]),
            n_val=int(sum(f.val_idx.size for f in folds)),
            brier=avg("brier"),
            log_loss=avg("log_loss"),
            auc=avg("auc"),
            model_version=version,
            backend=self.backend,
            fold_metrics=tuple(fold_metrics),
        )
        return fitted, report

    def _make_version(self, dataset: FamilyDataset) -> str:
        return _hash_version(self.backend, dataset, self.seed)


def _hash_version(backend: str, dataset: FamilyDataset, seed: int) -> str:
    h = hashlib.sha256()
    h.update(backend.encode())
    h.update(dataset.family.encode())
    h.update(dataset.features_sha.encode())
    h.update(str(seed).encode())
    h.update(str(dataset.X.shape).encode())
    return f"{backend}-{dataset.family.lower()}-{h.hexdigest()[:12]}"


def _make_predict_proba(backend_predict, payload):
    """Build a self-contained predict_proba bound to ``payload`` only.

    ``backend_predict`` is the (now staticmethod) ``_predict_proba`` callable
    on the backend class. The returned closure captures only ``payload`` and
    the static function — not the trainer instance, keeping the FittedModel
    artifact picklable and decoupled from the live trainer object.
    """

    def _predict(X_new: np.ndarray) -> np.ndarray:
        return backend_predict(payload, X_new)

    return _predict


__all__ = ["BaseFamilyTrainer", "FamilyDataset", "FittedModel"]
