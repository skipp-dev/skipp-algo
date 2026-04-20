"""OV7 — Enrichment A/B experiment framework.

Provides deterministic, symbol-level experiment assignment so that
enrichment domain flags can be varied between *control* and *treatment*
arms without external randomisation infrastructure.

Usage
-----
::

    from scripts.smc_ab_experiment import Experiment

    exp = Experiment(
        name="news-benzinga-uplift",
        treatment_overrides={"enrich_news": True},
        control_overrides={"enrich_news": False},
        salt="news-benzinga-uplift-2026",
        split_pct=50,
    )

    arm = exp.assign("AAPL")          # -> "treatment" | "control"
    flags = exp.resolve_flags("AAPL") # -> {"enrich_news": True}  (for treatment)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Experiment:
    """A single enrichment A/B experiment definition.

    Parameters
    ----------
    name:
        Human-readable experiment identifier (e.g. ``"news-benzinga-uplift"``).
    treatment_overrides:
        ``enrich_*`` flag overrides applied to symbols assigned to treatment.
    control_overrides:
        ``enrich_*`` flag overrides applied to control-arm symbols.
        Defaults to empty dict (= baseline flags unchanged).
    salt:
        Hash salt for deterministic assignment.  Change this to re-randomise.
    split_pct:
        Percentage of symbols assigned to treatment (0–100).
    """

    name: str
    treatment_overrides: dict[str, bool]
    control_overrides: dict[str, bool] = field(default_factory=dict)
    salt: str = ""
    split_pct: int = 50

    def __post_init__(self) -> None:
        if not 0 <= self.split_pct <= 100:
            raise ValueError(f"split_pct must be 0–100, got {self.split_pct}")
        if not self.name:
            raise ValueError("Experiment name must be non-empty")

    def _hash_bucket(self, symbol: str) -> int:
        """Return a 0–99 bucket for *symbol* using deterministic SHA-256."""
        payload = f"{self.salt or self.name}:{symbol}"
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return int(digest[:8], 16) % 100

    def assign(self, symbol: str) -> str:
        """Return ``"treatment"`` or ``"control"`` for *symbol*."""
        return "treatment" if self._hash_bucket(symbol) < self.split_pct else "control"

    def resolve_flags(self, symbol: str) -> dict[str, bool]:
        """Return the ``enrich_*`` overrides for *symbol*'s assigned arm."""
        if self.assign(symbol) == "treatment":
            return dict(self.treatment_overrides)
        return dict(self.control_overrides)

    def tag(self, symbol: str) -> dict[str, str]:
        """Return provenance metadata to embed in the manifest."""
        return {
            "experiment_name": self.name,
            "experiment_arm": self.assign(symbol),
        }


def load_experiment(path: Path) -> Experiment:
    """Load an experiment definition from a JSON file.

    Expected schema::

        {
            "name": "news-benzinga-uplift",
            "treatment_overrides": {"enrich_news": true},
            "control_overrides": {"enrich_news": false},
            "salt": "news-benzinga-uplift-2026",
            "split_pct": 50
        }
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Experiment(
        name=raw["name"],
        treatment_overrides=raw.get("treatment_overrides", {}),
        control_overrides=raw.get("control_overrides", {}),
        salt=raw.get("salt", ""),
        split_pct=raw.get("split_pct", 50),
    )


def apply_experiment_flags(
    base_flags: dict[str, Any],
    experiment: Experiment | None,
    symbol: str,
) -> dict[str, Any]:
    """Merge experiment overrides into *base_flags* for a single *symbol*.

    Returns a **copy** with the relevant arm's overrides applied.
    If *experiment* is ``None``, returns the original flags unchanged.
    """
    if experiment is None:
        return dict(base_flags)
    merged = dict(base_flags)
    merged.update(experiment.resolve_flags(symbol))
    return merged


def summarize_assignment(
    experiment: Experiment,
    symbols: list[str],
) -> dict[str, Any]:
    """Return a summary dict of arm assignments for *symbols*."""
    treatment = sorted(s for s in symbols if experiment.assign(s) == "treatment")
    control = sorted(s for s in symbols if experiment.assign(s) == "control")
    return {
        "experiment": experiment.name,
        "split_pct": experiment.split_pct,
        "total_symbols": len(symbols),
        "treatment_count": len(treatment),
        "control_count": len(control),
        "treatment_symbols": treatment,
        "control_symbols": control,
    }
