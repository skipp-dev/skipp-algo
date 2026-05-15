from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml.training import FamilyDataset  # noqa: E402
from ml.types import EventFamily, TrainingReport  # noqa: E402

DEFAULT_RESEARCH_FAMILIES: tuple[EventFamily, ...] = ("BOS", "OB", "FVG", "SWEEP")
_FAMILY_BIAS: dict[EventFamily, float] = {
    "BOS": 0.45,
    "OB": -0.10,
    "FVG": 0.25,
    "SWEEP": 0.15,
}


def iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_families(raw: str | None) -> tuple[EventFamily, ...]:
    if raw is None or not raw.strip():
        return DEFAULT_RESEARCH_FAMILIES

    seen: set[str] = set()
    families: list[EventFamily] = []
    for chunk in raw.split(","):
        label = chunk.strip().upper()
        if not label or label in seen:
            continue
        if label not in DEFAULT_RESEARCH_FAMILIES:
            allowed = ", ".join(DEFAULT_RESEARCH_FAMILIES)
            raise ValueError(f"unknown family {label!r}; expected one of: {allowed}")
        seen.add(label)
        families.append(cast(EventFamily, label))
    return tuple(families) or DEFAULT_RESEARCH_FAMILIES


def make_synthetic_family_dataset(
    family: EventFamily,
    *,
    n_samples: int = 900,
    n_features: int = 16,
    seed: int = 0,
    noise_scale: float = 0.40,
) -> FamilyDataset:
    if n_samples < 100:
        raise ValueError("n_samples must be >= 100 for walk-forward research")
    if n_features < 4:
        raise ValueError("n_features must be >= 4")

    family_seed = seed + 97 * (DEFAULT_RESEARCH_FAMILIES.index(family) + 1)
    rng = np.random.default_rng(family_seed)
    X = rng.normal(0.0, 1.0, size=(n_samples, n_features))
    weights = rng.normal(0.0, 0.65, size=n_features)
    weights[:4] += np.asarray([1.20, -0.90, 0.75, 0.55], dtype=float)
    interaction = 0.35 * X[:, 0] * X[:, 1]
    nonlinear = 0.20 * np.tanh(X[:, 2])
    logits = (X @ weights) / max(1.0, np.sqrt(n_features))
    logits += interaction + nonlinear + _FAMILY_BIAS[family]
    logits += rng.normal(0.0, noise_scale, size=n_samples)
    probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -20.0, 20.0)))
    y = (rng.uniform(size=n_samples) < probs).astype(float)
    feature_names = tuple(f"f{i:02d}" for i in range(n_features))
    return FamilyDataset(family=family, X=X, y=y, feature_names=feature_names)


def build_dataset_bundle(
    families: tuple[EventFamily, ...],
    *,
    n_samples: int = 900,
    n_features: int = 16,
    seed: int = 0,
) -> dict[EventFamily, FamilyDataset]:
    bundle: dict[EventFamily, FamilyDataset] = {}
    for idx, family in enumerate(families):
        bundle[family] = make_synthetic_family_dataset(
            family,
            n_samples=n_samples,
            n_features=n_features,
            seed=seed + idx * 17,
        )
    return bundle


def summarise_reports(reports: list[TrainingReport]) -> dict[str, float]:
    if not reports:
        raise ValueError("expected at least one training report")
    return {
        "mean_brier": float(np.mean([report.brier for report in reports])),
        "mean_log_loss": float(np.mean([report.log_loss for report in reports])),
        "mean_auc": float(np.mean([report.auc for report in reports])),
    }


__all__ = [
    "DEFAULT_RESEARCH_FAMILIES",
    "build_dataset_bundle",
    "iso_now",
    "make_synthetic_family_dataset",
    "parse_families",
    "summarise_reports",
]