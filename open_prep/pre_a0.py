"""Deterministic, replayable PRE-A0 feature and ETA baseline.

PRE-A0 is an unconfirmed early-warning state.  It is intentionally kept
separate from the confirmed A0 decision contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any

from .a0_contract import A0MarketSnapshot, A0ThresholdContext

PRE_A0_FEATURE_VERSION = "pre-a0-features-v1"
PRE_A0_DETECTOR_VERSION = "pre-a0-eta-v1"
_WINDOWS = (5, 15, 30)
_EPSILON = 1e-9


class PreA0State(IntEnum):
    NONE = 0
    WATCH = 1
    BUILDING = 2
    IMMINENT = 3


class PreA0Reason(StrEnum):
    BELOW_WATCH_GATE = "below_watch_gate"
    WATCH_GATE_REACHED = "watch_gate_reached"
    BOTH_AXES_PROGRESSING = "both_axes_progressing"
    ETA_WITHIN_HORIZON = "eta_within_horizon"
    PRICE_NOT_PROGRESSING = "price_not_progressing"
    VOLUME_NOT_PROGRESSING = "volume_not_progressing"
    STALE_DATA = "stale_data"
    GAP_OR_UNKNOWN_COMPLETENESS = "gap_or_unknown_completeness"
    DIRECTION_REVERSAL = "direction_reversal"
    INACTIVITY_RESET = "inactivity_reset"
    HYSTERESIS_HOLD = "hysteresis_hold"


@dataclass(frozen=True, slots=True)
class PreA0Observation:
    market: A0MarketSnapshot
    cumulative_volume: int
    gap_complete: bool = True
    pdh: float | None = None
    pdl: float | None = None


@dataclass(frozen=True, slots=True)
class PreA0Features:
    feature_version: str
    symbol: str
    session_date: str
    observed_at: float
    direction: str
    price_progress: float
    volume_progress: float
    price_distance_pct: float
    volume_distance_pace: float
    price_slopes: tuple[tuple[int, float | None], ...]
    volume_pace_slopes: tuple[tuple[int, float | None], ...]
    incremental_volume_rates: tuple[tuple[int, float | None], ...]
    price_acceleration: float | None
    volume_acceleration: float | None
    direction_stability: float
    data_age_ms: float | None
    data_age_unknown: bool
    gap_complete: bool
    pdh_distance_pct: float | None
    pdl_distance_pct: float | None

    def slope(self, axis: str, window_s: int) -> float | None:
        rows = self.price_slopes if axis == "price" else self.volume_pace_slopes
        return dict(rows).get(window_s)


@dataclass(frozen=True, slots=True)
class PreA0Estimate:
    state: PreA0State
    direction: str
    eta_low_s: float | None
    eta_high_s: float | None
    horizon_s: int | None
    expires_at: float | None
    reason_codes: tuple[str, ...]
    features: PreA0Features
    detector_version: str = PRE_A0_DETECTOR_VERSION
    is_calibrated: bool = False

    def to_operator_payload(self) -> dict[str, Any]:
        """Serialize an explicitly unconfirmed payload with no probability."""
        identity = {
            "detector_version": self.detector_version,
            "symbol": self.features.symbol,
            "observed_at": self.features.observed_at,
            "direction": self.direction,
            "state": self.state.name,
            "reasons": self.reason_codes,
        }
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        return {
            "kind": "PRE_A0",
            "level": None,
            "confirmed": False,
            "is_calibrated": False,
            "detector_version": self.detector_version,
            "feature_version": self.features.feature_version,
            "decision_id": hashlib.sha256(canonical.encode()).hexdigest()[:24],
            "symbol": self.features.symbol,
            "session_date": self.features.session_date,
            "observed_at": self.features.observed_at,
            "state": self.state.name,
            "direction": self.direction,
            "horizon_s": self.horizon_s,
            "eta_low_s": self.eta_low_s,
            "eta_high_s": self.eta_high_s,
            "expires_at": self.expires_at,
            "data_age_ms": self.features.data_age_ms,
            "reason_codes": list(self.reason_codes),
        }


def _direction(change_pct: float) -> str:
    if change_pct > 0:
        return "up"
    if change_pct < 0:
        return "down"
    return "flat"


def _progress(obs: PreA0Observation, thresholds: A0ThresholdContext) -> tuple[float, float]:
    return (
        abs(obs.market.change_pct) / max(thresholds.a0_price, _EPSILON),
        obs.market.normalized_volume_pace / max(thresholds.a0_volume, _EPSILON),
    )


def _window_rows(
    history: Sequence[PreA0Observation], now: float, window_s: int
) -> list[PreA0Observation]:
    return [row for row in history if now - window_s <= row.market.observed_at <= now]


def _robust_slope(points: Iterable[tuple[float, float]]) -> float | None:
    rows = sorted(points)
    slopes: list[float] = []
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            delta = right[0] - left[0]
            if delta > 0:
                slopes.append((right[1] - left[1]) / delta)
    return statistics.median(slopes) if slopes else None


def _volume_rate(rows: Sequence[PreA0Observation]) -> float | None:
    if len(rows) < 2:
        return None
    elapsed = rows[-1].market.observed_at - rows[0].market.observed_at
    delta = rows[-1].cumulative_volume - rows[0].cumulative_volume
    return max(0.0, delta / elapsed) if elapsed > 0 and delta >= 0 else None


def build_pre_a0_features(
    history: Sequence[PreA0Observation], thresholds: A0ThresholdContext
) -> PreA0Features:
    """Build trailing-only features; future observations are rejected."""
    if not history:
        raise ValueError("history must not be empty")
    rows = sorted(history, key=lambda item: item.market.observed_at)
    current = rows[-1]
    now = current.market.observed_at
    symbol = current.market.symbol
    session = current.market.session_date
    if any(row.market.observed_at > now for row in rows):
        raise ValueError("future observation detected")
    if any(row.market.symbol != symbol or row.market.session_date != session for row in rows):
        raise ValueError("history crosses symbol or session boundary")

    current_price, current_volume = _progress(current, thresholds)
    price_slopes: list[tuple[int, float | None]] = []
    volume_slopes: list[tuple[int, float | None]] = []
    volume_rates: list[tuple[int, float | None]] = []
    for window in _WINDOWS:
        window_rows = _window_rows(rows, now, window)
        progress_rows = [
            (row.market.observed_at, _progress(row, thresholds)) for row in window_rows
        ]
        price_slopes.append(
            (window, _robust_slope((ts, values[0]) for ts, values in progress_rows))
        )
        volume_slopes.append(
            (window, _robust_slope((ts, values[1]) for ts, values in progress_rows))
        )
        volume_rates.append((window, _volume_rate(window_rows)))

    directions = [_direction(row.market.change_pct) for row in rows[-30:]]
    current_direction = _direction(current.market.change_pct)
    directional = [value for value in directions if value != "flat"]
    stability = (
        directional.count(current_direction) / len(directional) if directional else 0.0
    )
    price = current.market.price
    return PreA0Features(
        feature_version=PRE_A0_FEATURE_VERSION,
        symbol=symbol,
        session_date=session,
        observed_at=now,
        direction=current_direction,
        price_progress=current_price,
        volume_progress=current_volume,
        price_distance_pct=max(0.0, thresholds.a0_price - abs(current.market.change_pct)),
        volume_distance_pace=max(
            0.0, thresholds.a0_volume - current.market.normalized_volume_pace
        ),
        price_slopes=tuple(price_slopes),
        volume_pace_slopes=tuple(volume_slopes),
        incremental_volume_rates=tuple(volume_rates),
        price_acceleration=_acceleration(price_slopes),
        volume_acceleration=_acceleration(volume_slopes),
        direction_stability=stability,
        data_age_ms=current.market.data_age_ms,
        data_age_unknown=current.market.data_age_unknown,
        gap_complete=current.gap_complete,
        pdh_distance_pct=(current.pdh / price - 1.0) * 100.0 if current.pdh and price else None,
        pdl_distance_pct=(price / current.pdl - 1.0) * 100.0 if current.pdl and price else None,
    )


def _acceleration(rows: Sequence[tuple[int, float | None]]) -> float | None:
    values = dict(rows)
    short, long = values.get(5), values.get(30)
    return short - long if short is not None and long is not None else None


def _eta_range(features: PreA0Features) -> tuple[float | None, float | None]:
    estimates: list[float] = []
    for window in _WINDOWS:
        price_slope = features.slope("price", window)
        volume_slope = features.slope("volume", window)
        if price_slope is None or volume_slope is None:
            continue
        if price_slope <= _EPSILON or volume_slope <= _EPSILON:
            continue
        price_eta = max(0.0, 1.0 - features.price_progress) / price_slope
        volume_eta = max(0.0, 1.0 - features.volume_progress) / volume_slope
        eta = max(price_eta, volume_eta)
        if math.isfinite(eta):
            estimates.append(eta)
    if not estimates:
        return None, None
    return round(min(estimates), 3), round(max(estimates), 3)


class PreA0Machine:
    """Stateful hysteresis wrapper around the deterministic trailing baseline."""

    def __init__(self, *, max_data_age_ms: float = 5_000, inactivity_s: float = 45) -> None:
        self.max_data_age_ms = float(max_data_age_ms)
        self.inactivity_s = float(inactivity_s)
        self._last: PreA0Estimate | None = None

    def evaluate(self, features: PreA0Features) -> PreA0Estimate:
        reasons: list[str] = []
        previous = self._last
        invalid = (
            features.data_age_unknown
            or features.data_age_ms is None
            or features.data_age_ms > self.max_data_age_ms
            or not features.gap_complete
        )
        if invalid:
            reasons.append(
                str(PreA0Reason.GAP_OR_UNKNOWN_COMPLETENESS)
                if not features.gap_complete or features.data_age_unknown
                else str(PreA0Reason.STALE_DATA)
            )
            estimate = self._make(features, PreA0State.NONE, None, None, reasons)
            self._last = estimate
            return estimate

        reversed_direction = bool(
            previous
            and previous.direction not in {"flat", features.direction}
            and features.direction != "flat"
        )
        inactive = bool(
            previous
            and features.observed_at - previous.features.observed_at > self.inactivity_s
        )
        if reversed_direction or inactive:
            reasons.append(
                str(PreA0Reason.DIRECTION_REVERSAL)
                if reversed_direction
                else str(PreA0Reason.INACTIVITY_RESET)
            )
            estimate = self._make(features, PreA0State.NONE, None, None, reasons)
            self._last = estimate
            return estimate

        eta_low, eta_high = _eta_range(features)
        price_slope = features.slope("price", 15)
        volume_slope = features.slope("volume", 15)
        if price_slope is None or price_slope <= _EPSILON:
            reasons.append(str(PreA0Reason.PRICE_NOT_PROGRESSING))
        if volume_slope is None or volume_slope <= _EPSILON:
            reasons.append(str(PreA0Reason.VOLUME_NOT_PROGRESSING))

        minimum = min(features.price_progress, features.volume_progress)
        state = PreA0State.NONE
        if minimum >= 0.50:
            state = PreA0State.WATCH
            reasons.append(str(PreA0Reason.WATCH_GATE_REACHED))
        else:
            reasons.append(str(PreA0Reason.BELOW_WATCH_GATE))
        if minimum >= 0.70 and eta_high is not None and features.direction_stability >= 0.75:
            state = PreA0State.BUILDING
            reasons.append(str(PreA0Reason.BOTH_AXES_PROGRESSING))
        if minimum >= 0.75 and eta_high is not None and eta_high <= 180:
            state = PreA0State.IMMINENT
            reasons.append(str(PreA0Reason.ETA_WITHIN_HORIZON))

        if previous and state < previous.state and minimum >= 0.45:
            state = PreA0State(max(int(state), int(previous.state) - 1))
            reasons.append(str(PreA0Reason.HYSTERESIS_HOLD))
        estimate = self._make(features, state, eta_low, eta_high, reasons)
        self._last = estimate
        return estimate

    @staticmethod
    def _make(
        features: PreA0Features,
        state: PreA0State,
        eta_low: float | None,
        eta_high: float | None,
        reasons: Sequence[str],
    ) -> PreA0Estimate:
        horizon = None
        if eta_high is not None:
            horizon = next((value for value in (30, 60, 180) if eta_high <= value), None)
        expires = features.observed_at + horizon if state > PreA0State.NONE and horizon else None
        return PreA0Estimate(
            state=state,
            direction=features.direction,
            eta_low_s=eta_low,
            eta_high_s=eta_high,
            horizon_s=horizon,
            expires_at=expires,
            reason_codes=tuple(dict.fromkeys(reasons)),
            features=features,
        )
