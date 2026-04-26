"""Typed contracts for the ml/ layer.

Stdlib-only so importing ``ml.types`` never pulls heavy deps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]


@dataclass(frozen=True)
class MLPrediction:
    """Single inference output for one event.

    ``probability`` is the calibrated P(profitable) in [0, 1].
    ``raw_score`` is the pre-calibration model output (same scale on
    well-behaved models, but kept separate so calibration regressions are
    visible to drift watchdogs).
    """

    family: EventFamily
    probability: float
    raw_score: float
    model_version: str
    calibrator_version: str
    schema_version: str = "v1"
    features_sha: str = ""

    def __post_init__(self) -> None:  # pragma: no cover - trivial guard
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(
                f"probability out of range: {self.probability!r} (family={self.family})"
            )


@dataclass(frozen=True)
class TrainingReport:
    """Walk-forward summary returned by every trainer."""

    family: EventFamily
    n_train: int
    n_val: int
    brier: float
    log_loss: float
    auc: float
    model_version: str
    backend: str  # "logistic", "xgboost", "lightgbm"
    fold_metrics: tuple[Mapping[str, float], ...] = field(default_factory=tuple)
