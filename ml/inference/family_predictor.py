"""FamilyPredictor with hot-reload + atomic-swap semantics.

Supports per-family ``(FittedModel, ProbabilityCalibrator)`` pairs. Models can
be swapped in atomically by the training cron without restarting the consumer
process.
"""
from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from ml.calibration.probability_calibrator import ProbabilityCalibrator
from ml.training.base import FittedModel
from ml.types import EventFamily, MLPrediction


@dataclass(frozen=True)
class ModelArtifact:
    fitted: FittedModel
    calibrator: ProbabilityCalibrator


class FamilyPredictor:
    """Thread-safe registry of per-family models with atomic swap.

    Lookup is O(1); swap is a single dict assignment under a lock so live
    inference threads never observe a torn ``(model, calibrator)`` pair.
    """

    def __init__(self) -> None:
        self._artifacts: dict[EventFamily, ModelArtifact] = {}
        self._lock = threading.RLock()

    def register(self, family: EventFamily, artifact: ModelArtifact) -> None:
        if artifact.fitted.family != family:
            raise ValueError(
                f"family mismatch: artifact.fitted.family={artifact.fitted.family} vs {family}"
            )
        with self._lock:
            self._artifacts[family] = artifact

    def swap(self, new_artifacts: Mapping[EventFamily, ModelArtifact]) -> None:
        """Atomic swap of the entire registry (used by the training cron)."""
        snapshot = dict(new_artifacts)
        for fam, art in snapshot.items():
            if art.fitted.family != fam:
                raise ValueError(f"family mismatch on swap: {fam} vs {art.fitted.family}")
        with self._lock:
            self._artifacts = snapshot

    def families(self) -> tuple[EventFamily, ...]:
        with self._lock:
            return tuple(self._artifacts.keys())

    def predict(self, family: EventFamily, features: np.ndarray) -> MLPrediction:
        with self._lock:
            artifact = self._artifacts.get(family)
        if artifact is None:
            raise KeyError(f"no model registered for family {family!r}")
        if features.ndim == 1:
            features = features.reshape(1, -1)
        if features.shape[0] != 1:
            raise ValueError("predict() expects a single event row; use predict_batch")
        raw = float(artifact.fitted.predict_proba(features)[0])
        prob = float(artifact.calibrator.transform([raw])[0])
        return MLPrediction(
            family=family,
            probability=prob,
            raw_score=raw,
            model_version=artifact.fitted.model_version,
            calibrator_version=artifact.calibrator.version,
        )

    def predict_batch(
        self, family: EventFamily, features: np.ndarray
    ) -> tuple[MLPrediction, ...]:
        with self._lock:
            artifact = self._artifacts.get(family)
        if artifact is None:
            raise KeyError(f"no model registered for family {family!r}")
        if features.ndim != 2:
            raise ValueError("predict_batch expects a 2-D feature matrix")
        raws = artifact.fitted.predict_proba(features)
        probs = artifact.calibrator.transform(raws)
        return tuple(
            MLPrediction(
                family=family,
                probability=float(p),
                raw_score=float(r),
                model_version=artifact.fitted.model_version,
                calibrator_version=artifact.calibrator.version,
            )
            for p, r in zip(probs, raws, strict=False)
        )


__all__ = ["FamilyPredictor", "ModelArtifact"]
