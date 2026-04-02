"""Probabilistic signal-quality scoring for SMC events.

Implements Brier Score and Log Score for calibrating predicted
probabilities against observed outcomes.

Current scope covers the four core SMC families with deterministic labels:
    - BOS follow-through
    - OB mitigation
    - FVG mitigation / fill
    - Sweep reversal

Integration:
    - Consumed by benchmark scripts and CI gates.
    - Produces versionable JSON artifacts per symbol+timeframe.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]
_FAMILY_ORDER: tuple[EventFamily, ...] = ("BOS", "OB", "FVG", "SWEEP")


@dataclass(slots=True, frozen=True)
class ScoredEvent:
    """A single scored prediction."""

    event_id: str
    family: EventFamily
    predicted_prob: float  # model's predicted probability of outcome
    outcome: bool          # True = event realized (e.g., sweep led to reversal)
    timestamp: float


@dataclass(slots=True)
class FamilyScoringMetrics:
    """Family-level probabilistic scoring summary."""

    family: EventFamily
    n_events: int = 0
    brier_score: float = float("nan")
    log_score: float = float("nan")
    hit_rate: float = float("nan")


@dataclass(slots=True)
class ScoringResult:
    """Aggregate scoring result for a set of predictions."""

    generated_at: float = field(default_factory=time.time)
    n_events: int = 0
    brier_score: float = float("nan")
    log_score: float = float("nan")
    hit_rate: float = float("nan")
    family_metrics: dict[EventFamily, FamilyScoringMetrics] = field(default_factory=dict)
    events: list[ScoredEvent] = field(default_factory=list)


def _normalize_market_direction(raw: str) -> str:
    normalized = str(raw).strip().upper()
    if normalized in {"UP", "BULL", "BULLISH"}:
        return "BULLISH"
    if normalized in {"DOWN", "BEAR", "BEARISH"}:
        return "BEARISH"
    return "NEUTRAL"


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


def label_bos_follow_through(
    bos_price: float,
    direction: str,
    subsequent_highs: list[float],
    subsequent_lows: list[float],
    *,
    threshold_pct: float = 0.003,
) -> bool:
    """Label whether a BOS produced directional follow-through.

    ``direction`` may be ``UP``/``DOWN`` or any bullish/bearish synonym.
    """
    if bos_price <= 0:
        return False

    normalized_direction = _normalize_market_direction(direction)
    if normalized_direction == "BULLISH":
        return any((high - bos_price) / bos_price >= threshold_pct for high in subsequent_highs)
    if normalized_direction == "BEARISH":
        return any((bos_price - low) / bos_price >= threshold_pct for low in subsequent_lows)
    return False


def _zone_touch_before_invalidation(
    zone_low: float,
    zone_high: float,
    direction: str,
    subsequent_highs: list[float],
    subsequent_lows: list[float],
    subsequent_closes: list[float],
) -> bool:
    if zone_low <= 0 or zone_high <= 0 or zone_high < zone_low:
        return False

    normalized_direction = _normalize_market_direction(direction)
    if normalized_direction not in {"BULLISH", "BEARISH"}:
        return False

    bar_count = max(len(subsequent_closes), len(subsequent_highs), len(subsequent_lows))
    if bar_count == 0:
        return False

    touch_idx: int | None = None
    invalid_idx: int | None = None
    for idx in range(bar_count):
        close = subsequent_closes[idx] if idx < len(subsequent_closes) else None
        high = subsequent_highs[idx] if idx < len(subsequent_highs) else None
        low = subsequent_lows[idx] if idx < len(subsequent_lows) else None

        if normalized_direction == "BEARISH":
            if touch_idx is None and high is not None and zone_low <= high <= zone_high:
                touch_idx = idx
            if invalid_idx is None and close is not None and close > zone_high:
                invalid_idx = idx
        else:
            if touch_idx is None and low is not None and zone_low <= low <= zone_high:
                touch_idx = idx
            if invalid_idx is None and close is not None and close < zone_low:
                invalid_idx = idx

    return touch_idx is not None and (invalid_idx is None or touch_idx <= invalid_idx)


def label_orderblock_mitigation(
    zone_low: float,
    zone_high: float,
    direction: str,
    subsequent_highs: list[float],
    subsequent_lows: list[float],
    subsequent_closes: list[float],
) -> bool:
    """Label whether an order block was mitigated before invalidation."""
    return _zone_touch_before_invalidation(
        zone_low,
        zone_high,
        direction,
        subsequent_highs,
        subsequent_lows,
        subsequent_closes,
    )


def label_fvg_mitigation(
    zone_low: float,
    zone_high: float,
    direction: str,
    subsequent_highs: list[float],
    subsequent_lows: list[float],
    subsequent_closes: list[float],
) -> bool:
    """Label whether an FVG was tagged/filled before invalidation."""
    return _zone_touch_before_invalidation(
        zone_low,
        zone_high,
        direction,
        subsequent_highs,
        subsequent_lows,
        subsequent_closes,
    )


def _summarize_scored_events(events: list[ScoredEvent]) -> tuple[int, float, float, float]:
    if not events:
        return 0, float("nan"), float("nan"), float("nan")

    predictions = [(e.predicted_prob, e.outcome) for e in events]
    hits = sum(1 for _, outcome in predictions if outcome)
    return (
        len(events),
        round(brier_score(predictions), 6),
        round(log_score(predictions), 6),
        round(hits / len(events), 4),
    )


def score_events(events: list[ScoredEvent]) -> ScoringResult:
    """Score a list of predicted events."""
    if not events:
        return ScoringResult()

    family_metrics: dict[EventFamily, FamilyScoringMetrics] = {}
    for family in _FAMILY_ORDER:
        family_events = [event for event in events if event.family == family]
        if not family_events:
            continue
        n_events, family_brier, family_log, family_hit_rate = _summarize_scored_events(family_events)
        family_metrics[family] = FamilyScoringMetrics(
            family=family,
            n_events=n_events,
            brier_score=family_brier,
            log_score=family_log,
            hit_rate=family_hit_rate,
        )

    n_events, aggregate_brier, aggregate_log, aggregate_hit_rate = _summarize_scored_events(events)

    return ScoringResult(
        n_events=n_events,
        brier_score=aggregate_brier,
        log_score=aggregate_log,
        hit_rate=aggregate_hit_rate,
        family_metrics=family_metrics,
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
        "generated_at": result.generated_at,
        "n_events": result.n_events,
        "brier_score": result.brier_score,
        "log_score": result.log_score,
        "hit_rate": result.hit_rate,
        "aggregate": {
            "n_events": result.n_events,
            "brier_score": result.brier_score,
            "log_score": result.log_score,
            "hit_rate": result.hit_rate,
        },
        "family_metrics": {
            family: asdict(metrics)
            for family, metrics in result.family_metrics.items()
        },
    }
    filename = f"scoring_{symbol}_{timeframe}.json"
    path = output_dir / filename
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
