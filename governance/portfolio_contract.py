"""Versioned contracts for broker-derived portfolio risk state.

The portfolio layer is deliberately downstream of signal scoring.  It does not
decide whether a setup is attractive; it answers whether the account can carry
the resulting exposure.  All money values are expressed in the snapshot's base
currency (USD in the initial contract).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Self

PORTFOLIO_SNAPSHOT_SCHEMA_VERSION = "1.0"
PORTFOLIO_CONTEXT_SCHEMA_VERSION = "1.0"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class WorkingOrderRole(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"
    UNKNOWN = "unknown"


def _finite(value: float, *, field_name: str, positive: bool = False) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    if positive and numeric <= 0.0:
        raise ValueError(f"{field_name} must be positive, got {value!r}")
    return numeric


def _symbol(value: str) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("symbol must be non-empty")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    account: str
    quantity: float
    avg_cost: float
    market_price: float | None
    currency: str = "USD"
    stop_price: float | None = None
    sector: str | None = None
    strategy_families: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "account", str(self.account).strip())
        object.__setattr__(self, "quantity", _finite(self.quantity, field_name="quantity"))
        object.__setattr__(self, "avg_cost", _finite(self.avg_cost, field_name="avg_cost"))
        if self.market_price is not None:
            object.__setattr__(
                self,
                "market_price",
                _finite(self.market_price, field_name="market_price", positive=True),
            )
        if self.stop_price is not None:
            object.__setattr__(
                self,
                "stop_price",
                _finite(self.stop_price, field_name="stop_price", positive=True),
            )
        object.__setattr__(self, "currency", str(self.currency).strip().upper())
        object.__setattr__(
            self,
            "strategy_families",
            tuple(sorted({str(item).strip() for item in self.strategy_families if str(item).strip()})),
        )


@dataclass(frozen=True, slots=True)
class WorkingOrderSnapshot:
    order_id: int
    order_ref: str
    symbol: str
    account: str
    side: Side
    total_quantity: float
    remaining_quantity: float
    reference_price: float | None
    role: WorkingOrderRole
    parent_id: int = 0
    strategy_family: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "account", str(self.account).strip())
        object.__setattr__(self, "order_ref", str(self.order_ref).strip())
        object.__setattr__(self, "side", Side(str(self.side).upper()))
        object.__setattr__(self, "role", WorkingOrderRole(str(self.role).lower()))
        total = _finite(self.total_quantity, field_name="total_quantity")
        remaining = _finite(self.remaining_quantity, field_name="remaining_quantity")
        if total < 0.0 or remaining < 0.0 or remaining > total:
            raise ValueError("working-order quantities must satisfy 0 <= remaining <= total")
        object.__setattr__(self, "total_quantity", total)
        object.__setattr__(self, "remaining_quantity", remaining)
        if self.reference_price is not None:
            object.__setattr__(
                self,
                "reference_price",
                _finite(self.reference_price, field_name="reference_price", positive=True),
            )


@dataclass(frozen=True, slots=True)
class PortfolioIntent:
    intent_id: str
    symbol: str
    account: str
    side: Side
    quantity: float
    entry_price: float
    stop_price: float
    strategy_family: str | None = None
    sector: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", str(self.intent_id).strip())
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "account", str(self.account).strip())
        object.__setattr__(self, "side", Side(str(self.side).upper()))
        object.__setattr__(
            self,
            "quantity",
            _finite(self.quantity, field_name="quantity", positive=True),
        )
        object.__setattr__(
            self,
            "entry_price",
            _finite(self.entry_price, field_name="entry_price", positive=True),
        )
        object.__setattr__(
            self,
            "stop_price",
            _finite(self.stop_price, field_name="stop_price", positive=True),
        )
        if not self.intent_id:
            raise ValueError("intent_id must be non-empty")


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotV1:
    snapshot_id: str
    captured_at: datetime
    account: str
    base_currency: str
    equity: float
    available_funds: float | None
    positions: tuple[PositionSnapshot, ...] = ()
    working_orders: tuple[WorkingOrderSnapshot, ...] = ()
    source: str = "unknown"
    complete: bool = True
    missing_fields: tuple[str, ...] = ()
    schema_version: str = PORTFOLIO_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PORTFOLIO_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported portfolio snapshot schema {self.schema_version!r}")
        object.__setattr__(self, "captured_at", _aware_utc(self.captured_at))
        object.__setattr__(self, "account", str(self.account).strip())
        object.__setattr__(self, "base_currency", str(self.base_currency).strip().upper())
        object.__setattr__(self, "equity", _finite(self.equity, field_name="equity"))
        if self.available_funds is not None:
            object.__setattr__(
                self,
                "available_funds",
                _finite(self.available_funds, field_name="available_funds"),
            )
        if not self.account:
            raise ValueError("portfolio snapshot account must be non-empty")
        if not self.base_currency:
            raise ValueError("portfolio snapshot base_currency must be non-empty")
        foreign_positions = {p.account for p in self.positions if p.account != self.account}
        foreign_orders = {o.account for o in self.working_orders if o.account != self.account}
        if foreign_positions or foreign_orders:
            raise ValueError(
                "portfolio snapshot mixes accounts: "
                f"positions={sorted(foreign_positions)!r}, orders={sorted(foreign_orders)!r}"
            )
        object.__setattr__(self, "missing_fields", tuple(sorted(set(self.missing_fields))))
        if self.complete and self.missing_fields:
            raise ValueError("complete portfolio snapshot cannot declare missing_fields")
        if self.complete:
            missing_prices = sorted(
                item.symbol
                for item in self.positions
                if item.quantity != 0.0 and item.market_price is None
            )
            foreign_currencies = sorted(
                f"{item.symbol}:{item.currency}"
                for item in self.positions
                if item.currency != self.base_currency
            )
            unsafe_orders = sorted(
                item.order_id
                for item in self.working_orders
                if item.role is WorkingOrderRole.UNKNOWN
                or (item.role is WorkingOrderRole.ENTRY and item.reference_price is None)
            )
            if missing_prices or foreign_currencies or unsafe_orders:
                raise ValueError(
                    "complete portfolio snapshot has unmeasurable state: "
                    f"missing_prices={missing_prices!r}, "
                    f"foreign_currencies={foreign_currencies!r}, "
                    f"unsafe_orders={unsafe_orders!r}"
                )

    @classmethod
    def build(
        cls,
        *,
        captured_at: datetime,
        account: str,
        base_currency: str,
        equity: float,
        available_funds: float | None,
        positions: tuple[PositionSnapshot, ...] = (),
        working_orders: tuple[WorkingOrderSnapshot, ...] = (),
        source: str,
        complete: bool,
        missing_fields: tuple[str, ...] = (),
    ) -> Self:
        ordered_positions = tuple(sorted(positions, key=lambda item: (item.account, item.symbol)))
        ordered_orders = tuple(
            sorted(working_orders, key=lambda item: (item.account, item.symbol, item.order_id))
        )
        payload = {
            "captured_at": _aware_utc(captured_at).isoformat(),
            "account": account,
            "base_currency": base_currency,
            "equity": equity,
            "available_funds": available_funds,
            "positions": [asdict(item) for item in ordered_positions],
            "working_orders": [asdict(item) for item in ordered_orders],
            "source": source,
            "complete": complete,
            "missing_fields": sorted(set(missing_fields)),
            "schema_version": PORTFOLIO_SNAPSHOT_SCHEMA_VERSION,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        snapshot_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return cls(
            snapshot_id=snapshot_id,
            captured_at=captured_at,
            account=account,
            base_currency=base_currency,
            equity=equity,
            available_funds=available_funds,
            positions=ordered_positions,
            working_orders=ordered_orders,
            source=source,
            complete=complete,
            missing_fields=missing_fields,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "captured_at": self.captured_at.isoformat(),
            "account": self.account,
            "base_currency": self.base_currency,
            "equity": self.equity,
            "available_funds": self.available_funds,
            "positions": [asdict(item) for item in self.positions],
            "working_orders": [
                {
                    **asdict(item),
                    "side": item.side.value,
                    "role": item.role.value,
                }
                for item in self.working_orders
            ],
            "source": self.source,
            "complete": self.complete,
            "missing_fields": list(self.missing_fields),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        positions = []
        for raw in payload.get("positions", []):
            positions.append(PositionSnapshot(**raw))
        orders = [WorkingOrderSnapshot(**raw) for raw in payload.get("working_orders", [])]
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            snapshot_id=str(payload["snapshot_id"]),
            captured_at=datetime.fromisoformat(str(payload["captured_at"])),
            account=str(payload["account"]),
            base_currency=str(payload["base_currency"]),
            equity=float(payload["equity"]),
            available_funds=(
                None if payload.get("available_funds") is None else float(payload["available_funds"])
            ),
            positions=tuple(positions),
            working_orders=tuple(orders),
            source=str(payload.get("source", "unknown")),
            complete=bool(payload.get("complete", False)),
            missing_fields=tuple(str(item) for item in payload.get("missing_fields", [])),
        )


@dataclass(frozen=True, slots=True)
class PortfolioRiskContextV1:
    as_of: datetime
    sector_by_symbol: Mapping[str, str] = field(default_factory=dict)
    pair_correlations: Mapping[str, float] = field(default_factory=dict)
    observations_by_pair: Mapping[str, int] = field(default_factory=dict)
    source: str = "unknown"
    complete: bool = False
    missing_symbols: tuple[str, ...] = ()
    schema_version: str = PORTFOLIO_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PORTFOLIO_CONTEXT_SCHEMA_VERSION:
            raise ValueError(f"unsupported portfolio context schema {self.schema_version!r}")
        object.__setattr__(self, "as_of", _aware_utc(self.as_of))
        sectors = {_symbol(key): str(value).strip() for key, value in self.sector_by_symbol.items()}
        object.__setattr__(self, "sector_by_symbol", MappingProxyType(sectors))
        correlations: dict[str, float] = {}
        for pair, raw in self.pair_correlations.items():
            value = _finite(raw, field_name=f"pair_correlations[{pair}]")
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"correlation for {pair!r} must be in [-1, 1]")
            correlations[str(pair)] = value
        object.__setattr__(self, "pair_correlations", MappingProxyType(correlations))
        observations = {str(pair): int(count) for pair, count in self.observations_by_pair.items()}
        if any(count < 0 for count in observations.values()):
            raise ValueError("observations_by_pair cannot contain negative counts")
        object.__setattr__(self, "observations_by_pair", MappingProxyType(observations))
        object.__setattr__(self, "missing_symbols", tuple(sorted({_symbol(x) for x in self.missing_symbols})))

    @staticmethod
    def pair_key(left: str, right: str) -> str:
        return "::".join(sorted((_symbol(left), _symbol(right))))

    def correlation(self, left: str, right: str) -> float | None:
        if _symbol(left) == _symbol(right):
            return 1.0
        return self.pair_correlations.get(self.pair_key(left, right))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "as_of": self.as_of.isoformat(),
            "sector_by_symbol": dict(sorted(self.sector_by_symbol.items())),
            "pair_correlations": dict(sorted(self.pair_correlations.items())),
            "observations_by_pair": dict(sorted(self.observations_by_pair.items())),
            "source": self.source,
            "complete": self.complete,
            "missing_symbols": list(self.missing_symbols),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            as_of=datetime.fromisoformat(str(payload["as_of"])),
            sector_by_symbol={
                str(key): str(value)
                for key, value in dict(payload.get("sector_by_symbol", {})).items()
            },
            pair_correlations={
                str(key): float(value)
                for key, value in dict(payload.get("pair_correlations", {})).items()
            },
            observations_by_pair={
                str(key): int(value)
                for key, value in dict(payload.get("observations_by_pair", {})).items()
            },
            source=str(payload.get("source", "unknown")),
            complete=bool(payload.get("complete", False)),
            missing_symbols=tuple(str(item) for item in payload.get("missing_symbols", [])),
        )


__all__ = [
    "PORTFOLIO_CONTEXT_SCHEMA_VERSION",
    "PORTFOLIO_SNAPSHOT_SCHEMA_VERSION",
    "PortfolioIntent",
    "PortfolioRiskContextV1",
    "PortfolioSnapshotV1",
    "PositionSnapshot",
    "Side",
    "WorkingOrderRole",
    "WorkingOrderSnapshot",
]
