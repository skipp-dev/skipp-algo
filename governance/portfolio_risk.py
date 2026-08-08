"""Portfolio-aware pre-trade decisions with shadow/enforce separation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from governance.portfolio_aggregation import PortfolioProjection, project_portfolio
from governance.portfolio_contract import (
    PortfolioIntent,
    PortfolioRiskContextV1,
    PortfolioSnapshotV1,
)

PORTFOLIO_RISK_LIMITS_SCHEMA_VERSION = "1.0"


class PortfolioRiskMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


class PortfolioRiskVerdict(StrEnum):
    ALLOW = "allow"
    RESIZE = "resize"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class PortfolioRiskLimitsV1:
    mode: PortfolioRiskMode = PortfolioRiskMode.SHADOW
    max_snapshot_age_seconds: float = 120.0
    max_context_age_seconds: float = 345_600.0
    max_open_positions: int = 5
    max_gross_exposure_pct: float = 200.0
    max_single_position_pct: float = 25.0
    max_pending_entry_exposure_pct: float = 100.0
    max_single_trade_risk_pct: float = 1.0
    max_known_portfolio_risk_at_stop_pct: float = 5.0
    min_risk_at_stop_coverage_pct: float = 100.0
    max_sector_exposure_pct: float | None = None
    max_correlated_cluster_exposure_pct: float | None = None
    correlation_threshold: float = 0.80
    min_correlation_coverage_pct: float = 80.0
    schema_version: str = PORTFOLIO_RISK_LIMITS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", PortfolioRiskMode(str(self.mode).lower()))
        if self.schema_version != PORTFOLIO_RISK_LIMITS_SCHEMA_VERSION:
            raise ValueError(f"unsupported portfolio limits schema {self.schema_version!r}")
        if self.max_open_positions < 0:
            raise ValueError("max_open_positions must be non-negative")
        positive_fields = (
            ("max_snapshot_age_seconds", self.max_snapshot_age_seconds),
            ("max_context_age_seconds", self.max_context_age_seconds),
            ("max_gross_exposure_pct", self.max_gross_exposure_pct),
            ("max_single_position_pct", self.max_single_position_pct),
            ("max_pending_entry_exposure_pct", self.max_pending_entry_exposure_pct),
            ("max_single_trade_risk_pct", self.max_single_trade_risk_pct),
            (
                "max_known_portfolio_risk_at_stop_pct",
                self.max_known_portfolio_risk_at_stop_pct,
            ),
        )
        for name, raw_value in positive_fields:
            value = float(raw_value)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        percentage_fields = (
            ("min_risk_at_stop_coverage_pct", self.min_risk_at_stop_coverage_pct),
            ("min_correlation_coverage_pct", self.min_correlation_coverage_pct),
        )
        for name, raw_value in percentage_fields:
            value = float(raw_value)
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} must be in [0, 100]")
        if not 0.0 <= self.correlation_threshold <= 1.0:
            raise ValueError("correlation_threshold must be in [0, 1]")
        optional_caps = (
            ("max_sector_exposure_pct", self.max_sector_exposure_pct),
            (
                "max_correlated_cluster_exposure_pct",
                self.max_correlated_cluster_exposure_pct,
            ),
        )
        for name, value in optional_caps:
            if value is not None and (not math.isfinite(float(value)) or float(value) <= 0.0):
                raise ValueError(f"{name} must be null or finite and positive")

    @classmethod
    def from_json(cls, path: str | Path) -> PortfolioRiskLimitsV1:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("portfolio risk limits must be a JSON object")
        allowed = {item.name for item in fields(cls)}
        metadata = {key for key in payload if str(key).startswith("_")}
        unknown = set(payload) - allowed - metadata
        if unknown:
            raise ValueError(f"unknown portfolio risk limit keys: {sorted(unknown)!r}")
        values = {key: value for key, value in payload.items() if key in allowed}
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        return payload


@dataclass(frozen=True, slots=True)
class PortfolioRiskDecision:
    mode: PortfolioRiskMode
    verdict: PortfolioRiskVerdict
    enforced: bool
    reasons: tuple[str, ...]
    recommended_scale: float | None
    projection: PortfolioProjection
    snapshot_age_seconds: float
    context_available: bool

    @property
    def would_block(self) -> bool:
        return self.verdict is not PortfolioRiskVerdict.ALLOW

    @property
    def permits_submission(self) -> bool:
        return not self.enforced or self.verdict is PortfolioRiskVerdict.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "verdict": self.verdict.value,
            "enforced": self.enforced,
            "would_block": self.would_block,
            "permits_submission": self.permits_submission,
            "reasons": list(self.reasons),
            "recommended_scale": self.recommended_scale,
            "snapshot_age_seconds": self.snapshot_age_seconds,
            "context_available": self.context_available,
            "projection": self.projection.to_dict(),
        }


def _candidate_risk_usd(intents: tuple[PortfolioIntent, ...]) -> float:
    return sum(abs(item.entry_price - item.stop_price) * item.quantity for item in intents)


def _resize_scale(
    projection: PortfolioProjection,
    intents: tuple[PortfolioIntent, ...],
    limits: PortfolioRiskLimitsV1,
    reasons: tuple[str, ...],
) -> float | None:
    scalable = {
        "projected_gross_exposure",
        "single_position_exposure",
        "pending_entry_exposure",
        "single_trade_risk",
        "known_portfolio_risk_at_stop",
    }
    if not reasons or any(reason not in scalable for reason in reasons):
        return None
    if any(item.side.value != "BUY" for item in intents):
        # V1 execution is long-only. Do not publish a mathematically wrong
        # linear resize recommendation for a future offsetting/short batch.
        return None
    if projection.candidate_gross_usd <= 0.0 or projection.equity <= 0.0:
        return None

    scales = [1.0]
    base_gross = projection.projected_gross_usd - projection.candidate_gross_usd
    gross_budget = limits.max_gross_exposure_pct / 100.0 * projection.equity
    scales.append((gross_budget - base_gross) / projection.candidate_gross_usd)

    pending_budget = limits.max_pending_entry_exposure_pct / 100.0 * projection.equity
    scales.append(
        (pending_budget - projection.pending_entry_gross_usd) / projection.candidate_gross_usd
    )

    single_budget = limits.max_single_position_pct / 100.0 * projection.equity
    for item in projection.symbols:
        candidate = abs(item.candidate_notional)
        if candidate <= 0.0:
            continue
        base = abs(item.current_notional + item.pending_entry_notional)
        scales.append((single_budget - base) / candidate)

    max_trade_risk = max(
        (abs(item.entry_price - item.stop_price) * item.quantity for item in intents),
        default=0.0,
    )
    if max_trade_risk > 0.0:
        scales.append(
            (limits.max_single_trade_risk_pct / 100.0 * projection.equity)
            / max_trade_risk
        )

    candidate_risk = _candidate_risk_usd(intents)
    if candidate_risk > 0.0:
        current_known_risk = max(0.0, projection.known_risk_at_stop_usd - candidate_risk)
        risk_budget = limits.max_known_portfolio_risk_at_stop_pct / 100.0 * projection.equity
        scales.append((risk_budget - current_known_risk) / candidate_risk)

    scale = min(scales)
    if not math.isfinite(scale) or scale <= 0.0 or scale >= 1.0:
        return None
    return round(scale, 6)


def evaluate_portfolio_risk(
    snapshot: PortfolioSnapshotV1,
    intents: tuple[PortfolioIntent, ...],
    limits: PortfolioRiskLimitsV1,
    *,
    now: datetime | None = None,
    context: PortfolioRiskContextV1 | None = None,
) -> PortfolioRiskDecision:
    """Evaluate current + projected exposure; shadow mode never blocks submission."""
    decision_at = now or datetime.now(UTC)
    if decision_at.tzinfo is None:
        raise ValueError("portfolio decision time must be timezone-aware")
    decision_at = decision_at.astimezone(UTC)
    age = (decision_at - snapshot.captured_at).total_seconds()
    projection = project_portfolio(
        snapshot,
        intents,
        context=context,
        correlation_threshold=limits.correlation_threshold,
    )
    reasons: list[str] = []

    if age < 0.0:
        reasons.append("snapshot_from_future")
    elif age > limits.max_snapshot_age_seconds:
        reasons.append("snapshot_stale")
    if not snapshot.complete:
        reasons.append("snapshot_incomplete")
    if snapshot.equity <= 0.0:
        reasons.append("non_positive_equity")
    if projection.unknown_working_orders:
        reasons.append("unknown_working_order_role")
    if projection.projected_open_positions > limits.max_open_positions:
        reasons.append("projected_open_positions")
    if projection.projected_gross_pct > limits.max_gross_exposure_pct:
        reasons.append("projected_gross_exposure")
    if projection.max_single_position_pct > limits.max_single_position_pct:
        reasons.append("single_position_exposure")
    if (
        projection.pending_entry_gross_pct + projection.candidate_gross_pct
        > limits.max_pending_entry_exposure_pct
    ):
        reasons.append("pending_entry_exposure")
    if projection.max_single_trade_risk_pct > limits.max_single_trade_risk_pct:
        reasons.append("single_trade_risk")
    if projection.known_risk_at_stop_pct > limits.max_known_portfolio_risk_at_stop_pct:
        reasons.append("known_portfolio_risk_at_stop")
    if projection.risk_at_stop_coverage_pct < limits.min_risk_at_stop_coverage_pct:
        reasons.append("risk_at_stop_coverage")

    context_enabled = (
        limits.max_sector_exposure_pct is not None
        or limits.max_correlated_cluster_exposure_pct is not None
    )
    if context is not None:
        context_age = (decision_at - context.as_of).total_seconds()
        if context_age < 0.0:
            reasons.append("context_from_future")
        elif context_enabled and context_age > limits.max_context_age_seconds:
            reasons.append("context_stale")
    if limits.max_sector_exposure_pct is not None:
        if projection.unknown_sector_symbols:
            reasons.append("sector_context_incomplete")
        elif projection.max_sector_exposure_pct > limits.max_sector_exposure_pct:
            reasons.append("sector_exposure")
    if limits.max_correlated_cluster_exposure_pct is not None:
        if projection.correlation_coverage_pct < limits.min_correlation_coverage_pct:
            reasons.append("correlation_context_incomplete")
        elif (
            projection.max_correlated_cluster_exposure_pct
            > limits.max_correlated_cluster_exposure_pct
        ):
            reasons.append("correlated_cluster_exposure")
    unique_reasons = tuple(dict.fromkeys(reasons))
    scale = _resize_scale(projection, intents, limits, unique_reasons)
    if not unique_reasons:
        verdict = PortfolioRiskVerdict.ALLOW
    elif scale is not None:
        verdict = PortfolioRiskVerdict.RESIZE
    else:
        verdict = PortfolioRiskVerdict.REJECT
    enforced = limits.mode is PortfolioRiskMode.ENFORCE
    return PortfolioRiskDecision(
        mode=limits.mode,
        verdict=verdict,
        enforced=enforced,
        reasons=unique_reasons,
        recommended_scale=scale,
        projection=projection,
        snapshot_age_seconds=age,
        context_available=context is not None,
    )


__all__ = [
    "PORTFOLIO_RISK_LIMITS_SCHEMA_VERSION",
    "PortfolioRiskDecision",
    "PortfolioRiskLimitsV1",
    "PortfolioRiskMode",
    "PortfolioRiskVerdict",
    "evaluate_portfolio_risk",
]
