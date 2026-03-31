"""Probabilistic signal-quality scoring for SMC events.

Implements Brier Score and Log Score for calibrating predicted
probabilities against observed outcomes.

MVP scope: **Sweep-reversal** label — did a sweep lead to a
directional reversal within *N* bars?

Integration:
  - Consumed by benchmark scripts and CI gates.
  - Produces versionable JSON artifacts per symbol+timeframe.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]


@dataclass(slots=True, frozen=True)
class ScoredEvent:
    """A single scored prediction."""

    event_id: str
    family: EventFamily
    predicted_prob: float  # model's predicted probability of outcome
    outcome: bool          # True = event realized (e.g., sweep led to reversal)
    timestamp: float


@dataclass(slots=True)
class ScoringResult:
    """Aggregate scoring result for a set of predictions."""

    n_events: int = 0
    brier_score: float = float("nan")
    log_score: float = float("nan")
    hit_rate: float = float("nan")
    events: list[ScoredEvent] = field(default_factory=list)


def brier_score(predictions: list[tuple[float, bool]]) -> float:
    """Compute Brier Score: mean squared error of probabilities vs outcomes.

    Lower is better.  Range: [0, 1].
    """
    if not predictions:
        return float("nan")
    total = sum((p - (1.0 if o else 0.0)) ** 2 for p, o in predictions)
    return total / len(predictions)


def log_score(predictions: list[tuple[float, bool]]) -> float:
    """Compute Log Score (negative log-likelihood per prediction).

    Lower is better (less negative).
    Clips probabilities to [1e-15, 1-1e-15] to avoid -inf.
    """
    if not predictions:
        return float("nan")
    eps = 1e-15
    total = 0.0
    for p, o in predictions:
        p_clipped = max(eps, min(1 - eps, p))
        if o:
            total += math.log(p_clipped)
        else:
            total += math.log(1 - p_clipped)
    return -total / len(predictions)


def label_sweep_reversal(
    sweep_price: float,
    sweep_side: str,
    subsequent_closes: list[float],
    *,
    threshold_pct: float = 0.005,
) -> bool:
    """Label whether a sweep led to a reversal.

    Parameters
    ----------
    sweep_price:
        Price at the sweep event.
    sweep_side:
        ``"BUY_SIDE"`` or ``"SELL_SIDE"``.
    subsequent_closes:
        Close prices of the *N* bars after the sweep.
    threshold_pct:
        Minimum price movement required to count as reversal.
    """
    if not subsequent_closes:
        return False

    if sweep_side == "SELL_SIDE":
        # Sell-side sweep → reversal = price moves UP
        return any((c - sweep_price) / sweep_price >= threshold_pct for c in subsequent_closes)
    else:
        # Buy-side sweep → reversal = price moves DOWN
        return any((sweep_price - c) / sweep_price >= threshold_pct for c in subsequent_closes)


def score_events(events: list[ScoredEvent]) -> ScoringResult:
    """Score a list of predicted events."""
    if not events:
        return ScoringResult()

    predictions = [(e.predicted_prob, e.outcome) for e in events]
    hits = sum(1 for _, o in predictions if o)

    return ScoringResult(
        n_events=len(events),
        brier_score=round(brier_score(predictions), 6),
        log_score=round(log_score(predictions), 6),
        hit_rate=round(hits / len(events), 4),
        events=list(events),
    )


def export_scoring_artifact(
    result: ScoringResult,
    *,
    symbol: str,
    timeframe: str,
    output_dir: Path,
    schema_version: str,
) -> Path:
    """Write a versionable scoring artifact to *output_dir*.

    Returns the path to the written JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "symbol": symbol,
        "timeframe": timeframe,
        "n_events": result.n_events,
        "brier_score": result.brier_score,
        "log_score": result.log_score,
        "hit_rate": result.hit_rate,
    }
    filename = f"scoring_{symbol}_{timeframe}.json"
    path = output_dir / filename
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
