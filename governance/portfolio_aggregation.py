"""Deterministic current and projected portfolio aggregation.

The projector assumes every working entry and every candidate intent fills in
full.  This is intentionally conservative and avoids pretending that a fill
probability model is a safety control.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from governance.portfolio_contract import (
    PortfolioIntent,
    PortfolioRiskContextV1,
    PortfolioSnapshotV1,
    WorkingOrderRole,
)


@dataclass(frozen=True, slots=True)
class SymbolExposure:
    symbol: str
    current_quantity: float
    projected_quantity: float
    current_notional: float
    pending_entry_notional: float
    candidate_notional: float
    projected_notional: float
    sector: str | None
    strategy_families: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "current_quantity": self.current_quantity,
            "projected_quantity": self.projected_quantity,
            "current_notional": self.current_notional,
            "pending_entry_notional": self.pending_entry_notional,
            "candidate_notional": self.candidate_notional,
            "projected_notional": self.projected_notional,
            "sector": self.sector,
            "strategy_families": list(self.strategy_families),
        }


@dataclass(frozen=True, slots=True)
class CorrelatedCluster:
    symbols: tuple[str, ...]
    gross_exposure_usd: float
    gross_exposure_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": list(self.symbols),
            "gross_exposure_usd": self.gross_exposure_usd,
            "gross_exposure_pct": self.gross_exposure_pct,
        }


@dataclass(frozen=True, slots=True)
class PortfolioProjection:
    snapshot_id: str
    account: str
    equity: float
    current_open_positions: int
    projected_open_positions: int
    current_gross_usd: float
    current_gross_pct: float
    current_net_usd: float
    current_net_pct: float
    pending_entry_gross_usd: float
    pending_entry_gross_pct: float
    candidate_gross_usd: float
    candidate_gross_pct: float
    projected_gross_usd: float
    projected_gross_pct: float
    projected_net_usd: float
    projected_net_pct: float
    known_risk_at_stop_usd: float
    known_risk_at_stop_pct: float
    risk_at_stop_coverage_pct: float
    max_single_trade_risk_pct: float
    symbols: tuple[SymbolExposure, ...]
    sector_gross_pct: dict[str, float]
    unknown_sector_symbols: tuple[str, ...]
    correlated_clusters: tuple[CorrelatedCluster, ...]
    correlation_coverage_pct: float
    unknown_working_orders: tuple[int, ...]

    @property
    def max_single_position_pct(self) -> float:
        if self.equity <= 0.0 or not self.symbols:
            return 0.0
        return max(abs(item.projected_notional) / self.equity * 100.0 for item in self.symbols)

    @property
    def max_sector_exposure_pct(self) -> float:
        return max(self.sector_gross_pct.values(), default=0.0)

    @property
    def max_correlated_cluster_exposure_pct(self) -> float:
        return max((cluster.gross_exposure_pct for cluster in self.correlated_clusters), default=0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "account": self.account,
            "equity": self.equity,
            "current_open_positions": self.current_open_positions,
            "projected_open_positions": self.projected_open_positions,
            "current_gross_usd": self.current_gross_usd,
            "current_gross_pct": self.current_gross_pct,
            "current_net_usd": self.current_net_usd,
            "current_net_pct": self.current_net_pct,
            "pending_entry_gross_usd": self.pending_entry_gross_usd,
            "pending_entry_gross_pct": self.pending_entry_gross_pct,
            "candidate_gross_usd": self.candidate_gross_usd,
            "candidate_gross_pct": self.candidate_gross_pct,
            "projected_gross_usd": self.projected_gross_usd,
            "projected_gross_pct": self.projected_gross_pct,
            "projected_net_usd": self.projected_net_usd,
            "projected_net_pct": self.projected_net_pct,
            "known_risk_at_stop_usd": self.known_risk_at_stop_usd,
            "known_risk_at_stop_pct": self.known_risk_at_stop_pct,
            "risk_at_stop_coverage_pct": self.risk_at_stop_coverage_pct,
            "max_single_trade_risk_pct": self.max_single_trade_risk_pct,
            "max_single_position_pct": self.max_single_position_pct,
            "sector_gross_pct": dict(sorted(self.sector_gross_pct.items())),
            "max_sector_exposure_pct": self.max_sector_exposure_pct,
            "unknown_sector_symbols": list(self.unknown_sector_symbols),
            "correlated_clusters": [item.to_dict() for item in self.correlated_clusters],
            "max_correlated_cluster_exposure_pct": self.max_correlated_cluster_exposure_pct,
            "correlation_coverage_pct": self.correlation_coverage_pct,
            "unknown_working_orders": list(self.unknown_working_orders),
            "symbols": [item.to_dict() for item in self.symbols],
        }


@dataclass(slots=True)
class _MutableExposure:
    current_quantity: float = 0.0
    projected_quantity: float = 0.0
    current_notional: float = 0.0
    pending_entry_notional: float = 0.0
    candidate_notional: float = 0.0
    sector: str | None = None
    families: set[str] | None = None

    def family_set(self) -> set[str]:
        if self.families is None:
            self.families = set()
        return self.families


def _pct(value: float, equity: float) -> float:
    return value / equity * 100.0 if equity > 0.0 else 0.0


def _correlated_clusters(
    exposures: tuple[SymbolExposure, ...],
    *,
    equity: float,
    context: PortfolioRiskContextV1 | None,
    threshold: float,
) -> tuple[tuple[CorrelatedCluster, ...], float]:
    active = [item for item in exposures if abs(item.projected_notional) > 0.0]
    if len(active) < 2:
        return (), 100.0
    required_pairs = len(active) * (len(active) - 1) // 2
    if context is None:
        return (), 0.0

    parent = {item.symbol: item.symbol for item in active}

    def find(symbol: str) -> str:
        while parent[symbol] != symbol:
            parent[symbol] = parent[parent[symbol]]
            symbol = parent[symbol]
        return symbol

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    observed = 0
    for idx, left in enumerate(active):
        for right in active[idx + 1 :]:
            correlation = context.correlation(left.symbol, right.symbol)
            if correlation is None:
                continue
            observed += 1
            if abs(correlation) >= threshold:
                union(left.symbol, right.symbol)

    grouped: dict[str, list[SymbolExposure]] = {}
    for item in active:
        grouped.setdefault(find(item.symbol), []).append(item)
    clusters = []
    for members in grouped.values():
        if len(members) < 2:
            continue
        gross = sum(abs(item.projected_notional) for item in members)
        clusters.append(
            CorrelatedCluster(
                symbols=tuple(sorted(item.symbol for item in members)),
                gross_exposure_usd=gross,
                gross_exposure_pct=_pct(gross, equity),
            )
        )
    clusters.sort(key=lambda item: (-item.gross_exposure_usd, item.symbols))
    return tuple(clusters), observed / required_pairs * 100.0


def project_portfolio(
    snapshot: PortfolioSnapshotV1,
    intents: tuple[PortfolioIntent, ...],
    *,
    context: PortfolioRiskContextV1 | None = None,
    correlation_threshold: float = 0.80,
) -> PortfolioProjection:
    """Aggregate broker state and conservatively project a full intent fill."""
    if not 0.0 <= correlation_threshold <= 1.0:
        raise ValueError("correlation_threshold must be in [0, 1]")
    for intent in intents:
        if intent.account != snapshot.account:
            raise ValueError(
                f"intent {intent.intent_id!r} belongs to {intent.account!r}, "
                f"snapshot belongs to {snapshot.account!r}"
            )

    rows: dict[str, _MutableExposure] = {}
    known_risk = 0.0
    risk_basis = 0.0
    covered_risk_basis = 0.0
    max_single_trade_risk = 0.0

    for position in snapshot.positions:
        row = rows.setdefault(position.symbol, _MutableExposure())
        row.current_quantity += position.quantity
        row.projected_quantity += position.quantity
        if position.market_price is not None:
            notional = position.quantity * position.market_price
            row.current_notional += notional
            risk_basis += abs(notional)
            if position.stop_price is not None:
                known_risk += abs(position.market_price - position.stop_price) * abs(position.quantity)
                covered_risk_basis += abs(notional)
        row.sector = position.sector or row.sector
        row.family_set().update(position.strategy_families)

    unknown_orders: list[int] = []
    for order in snapshot.working_orders:
        if order.remaining_quantity <= 0.0:
            continue
        if order.role is WorkingOrderRole.UNKNOWN:
            unknown_orders.append(order.order_id)
            continue
        if order.role is WorkingOrderRole.EXIT:
            continue
        row = rows.setdefault(order.symbol, _MutableExposure())
        signed_quantity = order.side.sign * order.remaining_quantity
        row.projected_quantity += signed_quantity
        if order.reference_price is not None:
            notional = signed_quantity * order.reference_price
            row.pending_entry_notional += notional
            risk_basis += abs(notional)
        if order.strategy_family:
            row.family_set().add(order.strategy_family)

    for intent in intents:
        row = rows.setdefault(intent.symbol, _MutableExposure())
        signed_quantity = intent.side.sign * intent.quantity
        notional = signed_quantity * intent.entry_price
        row.projected_quantity += signed_quantity
        row.candidate_notional += notional
        row.sector = intent.sector or row.sector
        if intent.strategy_family:
            row.family_set().add(intent.strategy_family)
        trade_risk = abs(intent.entry_price - intent.stop_price) * intent.quantity
        known_risk += trade_risk
        risk_basis += abs(notional)
        covered_risk_basis += abs(notional)
        max_single_trade_risk = max(max_single_trade_risk, _pct(trade_risk, snapshot.equity))

    exposures: list[SymbolExposure] = []
    for symbol, row in sorted(rows.items()):
        sector = row.sector
        if sector is None and context is not None:
            sector = context.sector_by_symbol.get(symbol)
        projected_notional = row.current_notional + row.pending_entry_notional + row.candidate_notional
        exposures.append(
            SymbolExposure(
                symbol=symbol,
                current_quantity=row.current_quantity,
                projected_quantity=row.projected_quantity,
                current_notional=row.current_notional,
                pending_entry_notional=row.pending_entry_notional,
                candidate_notional=row.candidate_notional,
                projected_notional=projected_notional,
                sector=sector,
                strategy_families=tuple(sorted(row.family_set())),
            )
        )
    frozen_exposures = tuple(exposures)

    current_gross = sum(abs(item.current_notional) for item in frozen_exposures)
    current_net = sum(item.current_notional for item in frozen_exposures)
    pending_gross = sum(abs(item.pending_entry_notional) for item in frozen_exposures)
    candidate_gross = sum(abs(item.candidate_notional) for item in frozen_exposures)
    projected_gross = sum(abs(item.projected_notional) for item in frozen_exposures)
    projected_net = sum(item.projected_notional for item in frozen_exposures)

    sector_gross_usd: dict[str, float] = {}
    unknown_sectors: list[str] = []
    for item in frozen_exposures:
        if abs(item.projected_notional) <= 0.0:
            continue
        if item.sector is None:
            unknown_sectors.append(item.symbol)
            continue
        sector_gross_usd[item.sector] = sector_gross_usd.get(item.sector, 0.0) + abs(
            item.projected_notional
        )
    sector_gross_pct = {
        sector: _pct(notional, snapshot.equity)
        for sector, notional in sector_gross_usd.items()
    }
    clusters, correlation_coverage = _correlated_clusters(
        frozen_exposures,
        equity=snapshot.equity,
        context=context,
        threshold=correlation_threshold,
    )

    return PortfolioProjection(
        snapshot_id=snapshot.snapshot_id,
        account=snapshot.account,
        equity=snapshot.equity,
        current_open_positions=sum(abs(item.current_quantity) > 0.0 for item in frozen_exposures),
        projected_open_positions=sum(abs(item.projected_quantity) > 0.0 for item in frozen_exposures),
        current_gross_usd=current_gross,
        current_gross_pct=_pct(current_gross, snapshot.equity),
        current_net_usd=current_net,
        current_net_pct=_pct(current_net, snapshot.equity),
        pending_entry_gross_usd=pending_gross,
        pending_entry_gross_pct=_pct(pending_gross, snapshot.equity),
        candidate_gross_usd=candidate_gross,
        candidate_gross_pct=_pct(candidate_gross, snapshot.equity),
        projected_gross_usd=projected_gross,
        projected_gross_pct=_pct(projected_gross, snapshot.equity),
        projected_net_usd=projected_net,
        projected_net_pct=_pct(projected_net, snapshot.equity),
        known_risk_at_stop_usd=known_risk,
        known_risk_at_stop_pct=_pct(known_risk, snapshot.equity),
        risk_at_stop_coverage_pct=(
            covered_risk_basis / risk_basis * 100.0 if risk_basis > 0.0 else 100.0
        ),
        max_single_trade_risk_pct=max_single_trade_risk,
        symbols=frozen_exposures,
        sector_gross_pct=sector_gross_pct,
        unknown_sector_symbols=tuple(sorted(unknown_sectors)),
        correlated_clusters=clusters,
        correlation_coverage_pct=correlation_coverage,
        unknown_working_orders=tuple(sorted(unknown_orders)),
    )


__all__ = [
    "CorrelatedCluster",
    "PortfolioProjection",
    "SymbolExposure",
    "project_portfolio",
]
