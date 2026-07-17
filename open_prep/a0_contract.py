"""Provider-neutral, replayable contract for A0 feature snapshots and decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

DETECTOR_VERSION = "a0-contract-v1"
_MIN_PLAUSIBLE_EPOCH = datetime(2000, 1, 1, tzinfo=UTC).timestamp()
_MAX_FUTURE_SKEW_SECONDS = 60.0


class A0ReasonCode(StrEnum):
    """Stable, machine-readable explanation codes for level decisions."""

    CORE_A0_THRESHOLDS = "core_a0_thresholds"
    CORE_A1_THRESHOLDS = "core_a1_thresholds"
    CORE_A1_LARGE_MOVE = "core_a1_large_move"
    CORE_A2_THRESHOLDS = "core_a2_thresholds"
    CORE_A2_LARGE_MOVE = "core_a2_large_move"
    FALLING_KNIFE_DOWNGRADE = "falling_knife_downgrade"
    PDH_BREAKOUT_UPGRADE = "pdh_breakout_upgrade"
    PDL_BREAKDOWN_UPGRADE = "pdl_breakdown_upgrade"
    STALE_VELOCITY_DOWNGRADE = "stale_velocity_downgrade"
    HYSTERESIS_ADJUSTMENT = "hysteresis_adjustment"
    RSI_DIRECTIONAL_UPGRADE = "rsi_directional_upgrade"
    RSI_CONTRA_DOWNGRADE = "rsi_contra_downgrade"
    TECHNICAL_CONTRA_DOWNGRADE = "technical_contra_downgrade"
    TECHNICAL_ALIGNMENT_UPGRADE = "technical_alignment_upgrade"
    COOLDOWN_DOWNGRADE = "cooldown_downgrade"
    MOMENTUM_NOT_CONFIRMED = "momentum_not_confirmed"
    NEWS_CATALYST_UPGRADE = "news_catalyst_upgrade"
    TIME_DECAY_DOWNGRADE = "time_decay_downgrade"
    REQUALIFICATION_DOWNGRADE = "requalification_downgrade"


@dataclass(frozen=True, slots=True)
class A0MarketSnapshot:
    symbol: str
    price: float
    prev_close: float
    change_pct: float
    raw_daily_volume_ratio: float
    expected_volume_fraction: float
    normalized_volume_pace: float
    source: str
    ts_event: float | None
    ts_recv: float
    observed_at: float
    session_date: str
    data_age_ms: float | None
    data_age_unknown: bool


@dataclass(frozen=True, slots=True)
class A0ThresholdContext:
    a0_volume: float
    a1_volume: float
    a2_volume: float
    a0_price: float
    a1_price: float
    a2_price: float


@dataclass(frozen=True, slots=True)
class A0StateContext:
    """Explicit state inputs used by modifiers outside the pure core decider."""

    previous_price: float | None = None
    cooldown_active: bool = False
    volume_regime: str = "NORMAL"


@dataclass(frozen=True, slots=True)
class A0Decision:
    core_level: str | None
    final_level: str | None
    reason_codes: tuple[str, ...]
    decision_at: float
    decision_id: str
    detector_version: str
    snapshot: A0MarketSnapshot

    def with_final_level(
        self,
        final_level: str,
        reason_codes: list[str] | tuple[str, ...],
    ) -> A0Decision:
        reasons = tuple(dict.fromkeys(str(reason) for reason in reason_codes))
        return replace(
            self,
            final_level=final_level,
            reason_codes=reasons,
            decision_id=_decision_id(self.snapshot, final_level, reasons),
        )

    def to_details(self) -> dict[str, Any]:
        snap = self.snapshot
        return {
            "decision_contract_version": 1,
            "detector_version": self.detector_version,
            "core_level": self.core_level,
            "final_level": self.final_level,
            "reason_codes": list(self.reason_codes),
            "decision_id": self.decision_id,
            "decision_basis_id": _snapshot_id(snap),
            "ts_event": snap.ts_event,
            "ts_recv": snap.ts_recv,
            "observed_at": snap.observed_at,
            "decision_at": self.decision_at,
            "data_age_ms": snap.data_age_ms,
            "data_age_unknown": snap.data_age_unknown,
            "source": snap.source,
            "session_date": snap.session_date,
        }


def _normalize_epoch(value: Any, *, observed_at: float) -> float | None:
    try:
        epoch = float(value)
    except (TypeError, ValueError):
        return None
    if epoch >= 1_000_000_000_000:
        epoch /= 1000.0
    if (
        epoch < _MIN_PLAUSIBLE_EPOCH
        or epoch > observed_at + _MAX_FUTURE_SKEW_SECONDS
    ):
        return None
    return epoch


def build_market_snapshot(
    *,
    symbol: str,
    price: float,
    prev_close: float,
    change_pct: float,
    raw_daily_volume_ratio: float,
    expected_volume_fraction: float,
    normalized_volume_pace: float,
    source: str,
    raw_ts_event: Any,
    raw_ts_recv: Any = None,
    observed_at: float,
) -> A0MarketSnapshot:
    """Validate provider timing and create a replayable market snapshot."""
    ts_event = _normalize_epoch(raw_ts_event, observed_at=observed_at)
    ts_recv = _normalize_epoch(raw_ts_recv, observed_at=observed_at) or observed_at
    session_epoch = ts_event if ts_event is not None else observed_at
    session_date = datetime.fromtimestamp(
        session_epoch, ZoneInfo("America/New_York")
    ).date().isoformat()
    data_age_ms = (
        round(max(0.0, observed_at - ts_event) * 1000.0, 3)
        if ts_event is not None
        else None
    )
    return A0MarketSnapshot(
        symbol=symbol.strip().upper(),
        price=float(price),
        prev_close=float(prev_close),
        change_pct=float(change_pct),
        raw_daily_volume_ratio=float(raw_daily_volume_ratio),
        expected_volume_fraction=float(expected_volume_fraction),
        normalized_volume_pace=float(normalized_volume_pace),
        source=source.strip().lower() or "unknown",
        ts_event=ts_event,
        ts_recv=ts_recv,
        observed_at=observed_at,
        session_date=session_date,
        data_age_ms=data_age_ms,
        data_age_unknown=ts_event is None,
    )


def decide_core_level(
    snapshot: A0MarketSnapshot,
    thresholds: A0ThresholdContext,
    *,
    decision_at: float | None = None,
) -> A0Decision:
    """Apply the provider-neutral threshold ladder without mutable state."""
    volume_pace = snapshot.normalized_volume_pace
    abs_change = abs(snapshot.change_pct)
    level: str | None = None
    reason: A0ReasonCode | None = None
    if volume_pace >= thresholds.a0_volume and abs_change >= thresholds.a0_price:
        level, reason = "A0", A0ReasonCode.CORE_A0_THRESHOLDS
    elif volume_pace >= thresholds.a1_volume and abs_change >= thresholds.a1_price:
        level, reason = "A1", A0ReasonCode.CORE_A1_THRESHOLDS
    elif abs_change >= thresholds.a0_price * 1.2:
        level, reason = "A1", A0ReasonCode.CORE_A1_LARGE_MOVE
    elif volume_pace >= thresholds.a2_volume and abs_change >= thresholds.a2_price:
        level, reason = "A2", A0ReasonCode.CORE_A2_THRESHOLDS
    elif abs_change >= thresholds.a1_price * 1.5:
        level, reason = "A2", A0ReasonCode.CORE_A2_LARGE_MOVE
    reasons = (str(reason),) if reason is not None else ()
    decided_at = snapshot.observed_at if decision_at is None else decision_at
    return A0Decision(
        core_level=level,
        final_level=level,
        reason_codes=reasons,
        decision_at=decided_at,
        decision_id=_decision_id(snapshot, level, reasons),
        detector_version=DETECTOR_VERSION,
        snapshot=snapshot,
    )


def _decision_id(
    snapshot: A0MarketSnapshot,
    final_level: str | None,
    reason_codes: tuple[str, ...],
) -> str:
    """Stable identifier for the same provider snapshot and semantic result."""
    identity = {
        "decision_basis_id": _snapshot_id(snapshot),
        "final_level": final_level,
        "reason_codes": reason_codes,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _snapshot_id(snapshot: A0MarketSnapshot) -> str:
    identity = {
        "detector_version": DETECTOR_VERSION,
        "source": snapshot.source,
        "symbol": snapshot.symbol,
        "session_date": snapshot.session_date,
        "ts_event": snapshot.ts_event,
        "price": snapshot.price,
        "prev_close": snapshot.prev_close,
        "raw_daily_volume_ratio": snapshot.raw_daily_volume_ratio,
        "expected_volume_fraction": snapshot.expected_volume_fraction,
        "normalized_volume_pace": snapshot.normalized_volume_pace,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def amend_decision_details(
    details: dict[str, Any],
    *,
    final_level: str,
    reason_code: A0ReasonCode,
) -> None:
    """Amend a stateful decision in place while preserving deterministic IDs."""
    reasons = list(details.get("reason_codes") or [])
    reason = str(reason_code)
    if reason not in reasons:
        reasons.append(reason)
    basis_value = details.get("decision_basis_id")
    if basis_value is None:
        basis_value = details.get("decision_id")
    basis_id = "" if basis_value is None else str(basis_value)
    identity = {
        "decision_basis_id": basis_id,
        "final_level": final_level,
        "reason_codes": tuple(reasons),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    details["final_level"] = final_level
    details["reason_codes"] = reasons
    details["decision_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
