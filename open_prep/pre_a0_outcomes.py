"""Deterministic outcome matching and daily metrics for PRE-A0 episodes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .pre_a0 import PreA0Estimate, PreA0State


@dataclass(frozen=True, slots=True)
class ConfirmedA0:
    symbol: str
    occurred_at: float
    direction: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreA0Outcome:
    decision_id: str
    symbol: str
    direction: str
    y_30: bool
    y_60: bool
    y_180: bool
    time_to_a0_s: float | None
    abort_cause: str | None


def evaluate_outcomes(
    estimates: Iterable[PreA0Estimate], confirmed: Iterable[ConfirmedA0]
) -> list[PreA0Outcome]:
    events = sorted(confirmed, key=lambda item: item.occurred_at)
    outcomes: list[PreA0Outcome] = []
    for estimate in estimates:
        if estimate.state is PreA0State.NONE:
            continue
        payload = estimate.to_operator_payload()
        matching = next(
            (
                event
                for event in events
                if event.symbol == estimate.features.symbol
                and event.direction == estimate.direction
                and 0 <= event.occurred_at - estimate.features.observed_at <= 180
            ),
            None,
        )
        lead = (
            matching.occurred_at - estimate.features.observed_at if matching else None
        )
        outcomes.append(
            PreA0Outcome(
                decision_id=str(payload["decision_id"]),
                symbol=estimate.features.symbol,
                direction=estimate.direction,
                y_30=lead is not None and lead <= 30,
                y_60=lead is not None and lead <= 60,
                y_180=lead is not None,
                time_to_a0_s=lead,
                abort_cause=None if matching else "no_same_direction_a0_within_180s",
            )
        )
    return outcomes


def summarize_outcomes(
    outcomes: Iterable[PreA0Outcome],
    *,
    session_seconds: float,
    eligible_a0_by_horizon: dict[int, int] | None = None,
) -> dict[str, object]:
    rows = list(outcomes)
    eligible = eligible_a0_by_horizon or {}
    report: dict[str, object] = {
        "episodes": len(rows),
        "alerts_per_hour": len(rows) / max(session_seconds / 3600.0, 1e-9),
        "repeat_alerts": max(0, len(rows) - len({(row.symbol, row.direction, row.time_to_a0_s) for row in rows})),
    }
    labels_by_horizon = {
        30: [row.y_30 for row in rows],
        60: [row.y_60 for row in rows],
        180: [row.y_180 for row in rows],
    }
    for horizon in (30, 60, 180):
        horizon_labels = labels_by_horizon[horizon]
        hits = sum(horizon_labels)
        leads = [
            row.time_to_a0_s
            for row, matched in zip(rows, horizon_labels, strict=True)
            if matched
        ]
        report[f"precision_{horizon}"] = hits / len(rows) if rows else 0.0
        report[f"recall_{horizon}"] = (
            hits / eligible[horizon] if eligible.get(horizon, 0) > 0 else None
        )
        report[f"mean_lead_{horizon}_s"] = sum(leads) / len(leads) if leads else None
    return report
