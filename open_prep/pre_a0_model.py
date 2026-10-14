"""Deterministic PRE-A0 baselines, calibration, artifacts, and shadow scoring."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

PRE_A0_MODEL_CONTRACT_VERSION = "pre-a0-model-v1"


class ModelStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    INVALID = "invalid"
    INCOMPATIBLE = "incompatible"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class LinearModel:
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    feature_min: tuple[float, ...]
    feature_max: tuple[float, ...]

    def raw_score(self, features: Mapping[str, float]) -> float:
        return self.intercept + sum(
            coefficient * float(features[name])
            for name, coefficient in zip(self.feature_names, self.coefficients, strict=True)
        )

    def probability(self, features: Mapping[str, float]) -> float:
        return _sigmoid(self.raw_score(features))


@dataclass(frozen=True, slots=True)
class MonotoneStump:
    feature: str
    threshold: float
    contribution: float


@dataclass(frozen=True, slots=True)
class MonotoneBoostModel:
    """Small gradient-boosted ensemble of non-negative decision stumps."""

    feature_names: tuple[str, ...]
    base_logit: float
    stumps: tuple[MonotoneStump, ...]

    def probability(self, features: Mapping[str, float]) -> float:
        score = self.base_logit + sum(
            stump.contribution
            for stump in self.stumps
            if float(features[stump.feature]) >= stump.threshold
        )
        return _sigmoid(score)


@dataclass(frozen=True, slots=True)
class PlattCalibration:
    slope: float
    intercept: float
    fitted_samples: int
    version: str = "platt-v1"

    def apply(self, raw_score: float) -> float:
        return _sigmoid(self.slope * raw_score + self.intercept)


@dataclass(frozen=True, slots=True)
class PreA0ModelArtifact:
    contract_version: str
    artifact_id: str
    schema_version: str
    feature_version: str
    split_manifest_sha256: str
    trained_from: str
    trained_through: str
    calibrated_from: str
    calibrated_through: str
    review_after: str
    horizons: tuple[int, ...]
    market_sessions: tuple[str, ...]
    direction_strategy: str
    model: LinearModel
    calibration: PlattCalibration | None
    metrics: dict[str, float]
    gates: dict[str, bool]
    fallback: str = "disable_pre_a0_only"

    @property
    def is_calibrated(self) -> bool:
        return self.calibration is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ShadowScore:
    status: ModelStatus
    probability: float | None
    is_calibrated: bool
    horizon_s: int
    inference_ms: float
    missing_features: tuple[str, ...]
    out_of_range_features: tuple[str, ...]
    artifact_id: str | None
    reason: str | None


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def base_rate(labels: Sequence[int], weights: Sequence[float] | None = None) -> float:
    if not labels:
        raise ValueError("labels must not be empty")
    sample_weights = list(weights) if weights is not None else [1.0] * len(labels)
    if len(sample_weights) != len(labels) or sum(sample_weights) <= 0:
        raise ValueError("invalid sample weights")
    return sum(label * weight for label, weight in zip(labels, sample_weights, strict=True)) / sum(
        sample_weights
    )


def train_logistic_regression(
    rows: Sequence[Mapping[str, float]],
    labels: Sequence[int],
    feature_names: Sequence[str],
    *,
    sample_weights: Sequence[float] | None = None,
    learning_rate: float = 0.05,
    iterations: int = 1_000,
    l2: float = 0.001,
) -> LinearModel:
    """Fit a small deterministic logistic baseline with batch gradient descent."""
    if not rows or len(rows) != len(labels):
        raise ValueError("rows and labels must be non-empty and aligned")
    names = tuple(feature_names)
    if not names:
        raise ValueError("feature_names must not be empty")
    matrix = [[float(row[name]) for name in names] for row in rows]
    weights = list(sample_weights) if sample_weights is not None else [1.0] * len(rows)
    if len(weights) != len(rows) or sum(weights) <= 0:
        raise ValueError("invalid sample weights")
    coefficients = [0.0] * len(names)
    intercept = math.log(max(base_rate(labels, weights), 1e-6) / max(1 - base_rate(labels, weights), 1e-6))
    denominator = sum(weights)
    for _ in range(iterations):
        gradient = [0.0] * len(names)
        intercept_gradient = 0.0
        for values, label, weight in zip(matrix, labels, weights, strict=True):
            prediction = _sigmoid(intercept + sum(c * value for c, value in zip(coefficients, values, strict=True)))
            error = (prediction - label) * weight
            intercept_gradient += error
            for index, value in enumerate(values):
                gradient[index] += error * value
        intercept -= learning_rate * intercept_gradient / denominator
        coefficients = [
            coefficient - learning_rate * (gradient[index] / denominator + l2 * coefficient)
            for index, coefficient in enumerate(coefficients)
        ]
    columns = list(zip(*matrix, strict=True))
    return LinearModel(
        names,
        tuple(coefficients),
        intercept,
        tuple(min(column) for column in columns),
        tuple(max(column) for column in columns),
    )


def train_monotone_stump_boost(
    rows: Sequence[Mapping[str, float]],
    labels: Sequence[int],
    feature_names: Sequence[str],
    *,
    iterations: int = 30,
    learning_rate: float = 0.2,
) -> MonotoneBoostModel:
    """Fit monotone positive stumps using deterministic logistic residuals."""
    if not rows or len(rows) != len(labels):
        raise ValueError("rows and labels must be non-empty and aligned")
    names = tuple(feature_names)
    rate = min(max(base_rate(labels), 1e-6), 1 - 1e-6)
    base_logit = math.log(rate / (1 - rate))
    scores = [base_logit] * len(rows)
    stumps: list[MonotoneStump] = []
    candidates = [
        (name, threshold)
        for name in names
        for threshold in sorted({float(row[name]) for row in rows})[1:]
    ]
    for _ in range(iterations):
        residuals = [label - _sigmoid(score) for label, score in zip(labels, scores, strict=True)]
        best: tuple[float, str, float, tuple[int, ...]] | None = None
        for name, threshold in candidates:
            members = tuple(index for index, row in enumerate(rows) if float(row[name]) >= threshold)
            if not members:
                continue
            gradient = sum(residuals[index] for index in members) / len(members)
            candidate = (gradient, name, threshold, members)
            if gradient > 0 and (best is None or candidate[:3] > best[:3]):
                best = candidate
        if best is None:
            break
        contribution = learning_rate * best[0]
        stumps.append(MonotoneStump(best[1], best[2], contribution))
        for index in best[3]:
            scores[index] += contribution
    return MonotoneBoostModel(names, base_logit, tuple(stumps))


def fit_platt_calibration(
    raw_scores: Sequence[float], labels: Sequence[int], *, iterations: int = 1_000
) -> PlattCalibration:
    if len(raw_scores) != len(labels) or len(labels) < 20 or len(set(labels)) < 2:
        raise ValueError("calibration requires at least 20 samples from both classes")
    slope, intercept = 1.0, 0.0
    for _ in range(iterations):
        slope_gradient = 0.0
        intercept_gradient = 0.0
        for score, label in zip(raw_scores, labels, strict=True):
            error = _sigmoid(slope * score + intercept) - label
            slope_gradient += error * score
            intercept_gradient += error
        slope -= 0.05 * slope_gradient / len(labels)
        intercept -= 0.05 * intercept_gradient / len(labels)
    return PlattCalibration(slope, intercept, len(labels))


def brier_score(probabilities: Sequence[float], labels: Sequence[int]) -> float:
    if not probabilities or len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must be non-empty and aligned")
    return sum((probability - label) ** 2 for probability, label in zip(probabilities, labels, strict=True)) / len(labels)


def expected_calibration_error(
    probabilities: Sequence[float], labels: Sequence[int], *, bins: int = 10
) -> float:
    if not probabilities or len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must be non-empty and aligned")
    error = 0.0
    for bin_index in range(bins):
        lower, upper = bin_index / bins, (bin_index + 1) / bins
        members = [
            (probability, label)
            for probability, label in zip(probabilities, labels, strict=True)
            if lower <= probability < upper or (bin_index == bins - 1 and probability == 1.0)
        ]
        if members:
            confidence = sum(item[0] for item in members) / len(members)
            accuracy = sum(item[1] for item in members) / len(members)
            error += len(members) / len(labels) * abs(confidence - accuracy)
    return error


def average_precision(probabilities: Sequence[float], labels: Sequence[int]) -> float:
    if not probabilities or len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must be non-empty and aligned")
    positives = sum(labels)
    if positives == 0:
        return 0.0
    ranked = sorted(zip(probabilities, labels, strict=True), reverse=True)
    true_positives = 0
    precision_sum = 0.0
    for rank, (_, label) in enumerate(ranked, start=1):
        if label:
            true_positives += 1
            precision_sum += true_positives / rank
    return precision_sum / positives


def reliability_bins(
    probabilities: Sequence[float], labels: Sequence[int], *, bins: int = 10
) -> list[dict[str, float | int]]:
    output: list[dict[str, float | int]] = []
    for bin_index in range(bins):
        lower, upper = bin_index / bins, (bin_index + 1) / bins
        members = [
            (probability, label)
            for probability, label in zip(probabilities, labels, strict=True)
            if lower <= probability < upper or (bin_index == bins - 1 and probability == 1)
        ]
        if members:
            output.append(
                {
                    "lower": lower,
                    "upper": upper,
                    "count": len(members),
                    "mean_probability": sum(row[0] for row in members) / len(members),
                    "observed_rate": sum(row[1] for row in members) / len(members),
                }
            )
    return output


def make_artifact(
    model: LinearModel,
    calibration: PlattCalibration | None,
    *,
    schema_version: str,
    feature_version: str,
    split_manifest_sha256: str,
    trained_window: tuple[str, str],
    calibrated_window: tuple[str, str],
    review_after: str,
    horizons: Sequence[int],
    metrics: Mapping[str, float],
    gates: Mapping[str, bool],
) -> PreA0ModelArtifact:
    artifact_id = compute_artifact_id(
        contract_version=PRE_A0_MODEL_CONTRACT_VERSION,
        schema_version=schema_version,
        feature_version=feature_version,
        split_manifest_sha256=split_manifest_sha256,
        model=model,
        calibration=calibration,
    )
    return PreA0ModelArtifact(
        PRE_A0_MODEL_CONTRACT_VERSION,
        artifact_id,
        schema_version,
        feature_version,
        split_manifest_sha256,
        trained_window[0],
        trained_window[1],
        calibrated_window[0],
        calibrated_window[1],
        review_after,
        tuple(sorted(set(horizons))),
        ("regular",),
        "shared_model_with_direction_feature",
        model,
        calibration,
        dict(metrics),
        dict(gates),
    )


def compute_artifact_id(
    *,
    contract_version: str,
    schema_version: str,
    feature_version: str,
    split_manifest_sha256: str,
    model: LinearModel,
    calibration: PlattCalibration | None,
) -> str:
    """Return the canonical, content-derived identity of a PRE-A0 model."""
    identity = {
        "contract": contract_version,
        "schema": schema_version,
        "feature": feature_version,
        "split": split_manifest_sha256,
        "model": asdict(model),
        "calibration": asdict(calibration) if calibration else None,
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]


def verify_artifact_id(artifact: PreA0ModelArtifact) -> bool:
    """Verify that the declared artifact ID still matches canonical content."""
    return artifact.artifact_id == compute_artifact_id(
        contract_version=artifact.contract_version,
        schema_version=artifact.schema_version,
        feature_version=artifact.feature_version,
        split_manifest_sha256=artifact.split_manifest_sha256,
        model=artifact.model,
        calibration=artifact.calibration,
    )


def parse_artifact(payload: Mapping[str, Any]) -> PreA0ModelArtifact:
    model = LinearModel(**payload["model"])
    calibration_payload = payload.get("calibration")
    calibration = PlattCalibration(**calibration_payload) if calibration_payload else None
    values = dict(payload)
    values["model"] = model
    values["calibration"] = calibration
    for field in ("horizons", "market_sessions"):
        values[field] = tuple(values[field])
    return PreA0ModelArtifact(**values)


def load_artifact(
    path: Path,
    *,
    expected_schema: str,
    expected_feature_version: str,
    now: datetime | None = None,
) -> tuple[ModelStatus, PreA0ModelArtifact | None, str | None]:
    if not Path(path).is_file():
        return ModelStatus.MISSING, None, "artifact_missing"
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        artifact = parse_artifact(payload)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return ModelStatus.INVALID, None, f"artifact_invalid:{type(exc).__name__}"
    if not verify_artifact_id(artifact):
        return ModelStatus.INVALID, None, "artifact_identity_mismatch"
    if (
        artifact.contract_version != PRE_A0_MODEL_CONTRACT_VERSION
        or artifact.schema_version != expected_schema
        or artifact.feature_version != expected_feature_version
    ):
        return ModelStatus.INCOMPATIBLE, None, "artifact_incompatible"
    check_time = now or datetime.now(UTC)
    try:
        review_after = datetime.fromisoformat(artifact.review_after.replace("Z", "+00:00"))
    except ValueError:
        return ModelStatus.INVALID, None, "review_after_invalid"
    if check_time > review_after:
        return ModelStatus.EXPIRED, None, "artifact_expired"
    return ModelStatus.READY, artifact, None


class PreA0ShadowScorer:
    """Fail-closed scorer that cannot mutate or suppress the A0 path."""

    def __init__(self, status: ModelStatus, artifact: PreA0ModelArtifact | None, reason: str | None = None) -> None:
        self.status = status
        self.artifact = artifact
        self.reason = reason

    def score(self, features: Mapping[str, float], *, horizon_s: int) -> ShadowScore:
        started = time.perf_counter()
        if self.status is not ModelStatus.READY or self.artifact is None:
            return ShadowScore(self.status, None, False, horizon_s, 0.0, (), (), None, self.reason)
        model = self.artifact.model
        missing = tuple(name for name in model.feature_names if name not in features)
        if horizon_s not in self.artifact.horizons or missing:
            elapsed = (time.perf_counter() - started) * 1_000
            return ShadowScore(ModelStatus.INCOMPATIBLE, None, False, horizon_s, elapsed, missing, (), self.artifact.artifact_id, "unsupported_input")
        out_of_range = tuple(
            name
            for name, minimum, maximum in zip(model.feature_names, model.feature_min, model.feature_max, strict=True)
            if float(features[name]) < minimum or float(features[name]) > maximum
        )
        raw = model.raw_score(features)
        probability = self.artifact.calibration.apply(raw) if self.artifact.calibration else _sigmoid(raw)
        elapsed = (time.perf_counter() - started) * 1_000
        return ShadowScore(
            ModelStatus.READY,
            probability,
            self.artifact.is_calibrated,
            horizon_s,
            elapsed,
            (),
            out_of_range,
            self.artifact.artifact_id,
            "feature_out_of_range" if out_of_range else None,
        )
