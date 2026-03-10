from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
import sys
import time as time_module
from typing import Any, Iterable, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategy_config import LONG_DIP_MAX_GAP_PCT, LONG_DIP_MIN_GAP_PCT, LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME, LONG_DIP_MIN_PREMARKET_TRADE_COUNT, LONG_DIP_MIN_PREMARKET_VOLUME, LONG_DIP_MIN_PREVIOUS_CLOSE, LONG_DIP_POSITION_BUDGET_USD, LONG_DIP_TOP_N
from scripts.generate_databento_watchlist import LongDipConfig, build_daily_watchlists, load_watchlist_inputs


DEFAULT_WATCHLIST_CSV = REPO_ROOT / "reports" / "databento_watchlist_top5_pre1530.csv"
DEFAULT_PREVIEW_JSON = REPO_ROOT / "reports" / "ibkr_watchlist_preview.json"
DEFAULT_CANCEL_UNFILLED_AFTER = "15:30:20"
DEFAULT_TIME_STOP_AFTER = "15:31:00"
DEFAULT_SCHEDULE_TIMEZONE = "Europe/Berlin"
DEFAULT_RECONNECT_MAX_ATTEMPTS = 3
DEFAULT_RECONNECT_WAIT_SECONDS = 2.0
TERMINAL_ORDER_STATUSES = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(api[_-]?key=)([^&\s]+)", flags=re.IGNORECASE),
    re.compile(r"(token=)([^&\s]+)", flags=re.IGNORECASE),
    re.compile(r"(Authorization:\s*Bearer\s+)([^\s]+)", flags=re.IGNORECASE),
)


@dataclass(frozen=True)
class IBKRConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 71
    account: str | None = None
    timeout_seconds: float = 10.0
    readonly: bool = False


@dataclass(frozen=True)
class IBKRExecutionConfig:
    tif: str = "DAY"
    outside_rth: bool = False
    currency: str = "USD"
    exchange: str = "SMART"
    exit_mode: str = "tp-stop"
    cancel_unfilled_after: str | None = DEFAULT_CANCEL_UNFILLED_AFTER
    time_stop_after: str | None = DEFAULT_TIME_STOP_AFTER
    clock_timezone: str = DEFAULT_SCHEDULE_TIMEZONE


@dataclass(frozen=True)
class IBKROrderIntent:
    trade_date: date
    symbol: str
    watchlist_rank: int
    level_tag: str
    quantity: int
    entry_limit: float
    take_profit: float
    stop_loss: float
    trailing_stop_pct: float
    trailing_stop_anchor: float
    premarket_last: float
    gap_pct: float
    tif: str
    outside_rth: bool
    exit_mode: str
    order_ref: str


def _normalize_trade_date(value: Any) -> date:
    normalized = pd.to_datetime(value, errors="raise")
    if hasattr(normalized, "date"):
        return cast(date, normalized.date())
    raise ValueError(f"Unable to normalize trade date from {value!r}")


def _parse_symbol_filter(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _normalize_schedule_value(raw: str | None) -> str | None:
    if raw is None:
        return None
    normalized = raw.strip()
    if not normalized:
        return None
    if normalized.lower() in {"none", "off", "disable", "disabled"}:
        return None
    return normalized


def _parse_time_of_day(raw: str | None) -> time | None:
    normalized = _normalize_schedule_value(raw)
    if normalized is None:
        return None
    parts = normalized.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError(f"Invalid time-of-day value {raw!r}. Expected HH:MM or HH:MM:SS.")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    return time(hour=hour, minute=minute, second=second)


def _resolve_trigger_datetime(trade_date: date, trigger_at: str | None, timezone_name: str) -> datetime | None:
    parsed_time = _parse_time_of_day(trigger_at)
    if parsed_time is None:
        return None
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    return datetime.combine(trade_date, parsed_time, tzinfo=timezone)


def _sleep_until(target: datetime | None) -> None:
    if target is None:
        return
    while True:
        remaining = (target - datetime.now(target.tzinfo)).total_seconds()
        if remaining <= 0:
            return
        time_module.sleep(min(remaining, 1.0))


def _is_live_order_status(status: str) -> bool:
    return status not in TERMINAL_ORDER_STATUSES


def _normalize_symbol_filter(symbols: Iterable[str] | None) -> set[str]:
    return {str(item).upper() for item in (symbols or []) if str(item).strip()}


def _normalize_order_ref_filter(order_refs: Iterable[str] | None) -> set[str]:
    return {str(item) for item in (order_refs or []) if str(item).strip()}


def _looks_like_connection_error(exc: Exception) -> bool:
    rendered = str(exc).lower()
    return any(
        token in rendered
        for token in (
            "not connected",
            "connection",
            "disconnect",
            "socket",
            "broken pipe",
            "peer closed",
            "eof",
        )
    )


def _sanitize_error_text(text: str) -> str:
    redacted = str(text)
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(r"\1***", redacted)
    return redacted


def _as_valid_price(value: Any, *, field_name: str) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{field_name} must be a finite number > 0, got {value!r}")
    return numeric


def _as_valid_nonnegative_fraction(value: Any, *, field_name: str) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{field_name} must be a finite number >= 0, got {value!r}")
    return numeric


def _attempt_ibkr_reconnect(
    ib: Any,
    *,
    connection_cfg: IBKRConnectionConfig,
    max_attempts: int,
    wait_seconds: float,
    reason: str,
) -> dict[str, Any]:
    if max_attempts <= 0:
        return {
            "action": "reconnect",
            "status": "disabled",
            "reason": reason,
            "captured_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            "attempts": [],
        }

    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        attempt_started_at = datetime.now(ZoneInfo("UTC"))
        try:
            ib.connect(
                connection_cfg.host,
                connection_cfg.port,
                clientId=connection_cfg.client_id,
                timeout=connection_cfg.timeout_seconds,
                readonly=connection_cfg.readonly,
            )
            connected = bool(ib.isConnected())
            attempts.append(
                {
                    "attempt": attempt,
                    "captured_at": attempt_started_at.isoformat(),
                    "connected": connected,
                    "error": None,
                }
            )
            if connected:
                return {
                    "action": "reconnect",
                    "status": "reconnected",
                    "reason": reason,
                    "captured_at": datetime.now(ZoneInfo("UTC")).isoformat(),
                    "attempts": attempts,
                }
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt,
                    "captured_at": attempt_started_at.isoformat(),
                    "connected": False,
                    "error": _sanitize_error_text(str(exc)),
                }
            )

        if attempt < max_attempts and wait_seconds > 0:
            time_module.sleep(wait_seconds)

    return {
        "action": "reconnect",
        "status": "failed",
        "reason": reason,
        "captured_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "attempts": attempts,
    }


def _call_with_reconnect(
    ib: Any,
    *,
    operation_name: str,
    operation: Any,
    connection_cfg: IBKRConnectionConfig,
    reconnect_max_attempts: int,
    reconnect_wait_seconds: float,
    events: list[dict[str, Any]],
) -> Any:
    if not ib.isConnected():
        reconnect_event = _attempt_ibkr_reconnect(
            ib,
            connection_cfg=connection_cfg,
            max_attempts=reconnect_max_attempts,
            wait_seconds=reconnect_wait_seconds,
            reason=f"{operation_name}:precheck",
        )
        events.append(reconnect_event)
        if reconnect_event["status"] != "reconnected":
            raise RuntimeError(f"IBKR reconnect failed before {operation_name}.")

    try:
        return operation()
    except Exception as exc:
        if ib.isConnected() and not _looks_like_connection_error(exc):
            raise

        reconnect_event = _attempt_ibkr_reconnect(
            ib,
            connection_cfg=connection_cfg,
            max_attempts=reconnect_max_attempts,
            wait_seconds=reconnect_wait_seconds,
            reason=f"{operation_name}:exception:{exc}",
        )
        events.append(reconnect_event)
        if reconnect_event["status"] != "reconnected":
            raise RuntimeError(f"IBKR reconnect failed during {operation_name}: {exc}") from exc
        return operation()


def _coerce_watchlist_trade_dates(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], errors="coerce").dt.date
    normalized["symbol"] = normalized["symbol"].astype(str).str.upper()
    return normalized


def load_watchlist_frame(
    *,
    watchlist_csv: str | Path | None,
    bundle: str | Path | None,
    export_dir: str | Path | None,
    watchlist_cfg: LongDipConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if watchlist_csv is not None:
        csv_path = Path(watchlist_csv).expanduser()
        if not csv_path.exists():
            raise FileNotFoundError(f"Watchlist CSV not found: {csv_path}")
        watchlist = pd.read_csv(csv_path)
        return _coerce_watchlist_trade_dates(watchlist), {
            "source": "watchlist_csv",
            "watchlist_csv": str(csv_path),
        }

    daily, prem, diagnostics, metadata = load_watchlist_inputs(bundle=bundle, export_dir=export_dir)
    watchlist = build_daily_watchlists(daily=daily, prem=prem, diagnostics=diagnostics, cfg=watchlist_cfg)
    return watchlist, metadata


def resolve_trade_date(watchlist: pd.DataFrame, requested_trade_date: str | None) -> date:
    if watchlist.empty:
        raise ValueError("Watchlist is empty; no trade date can be resolved.")
    available_dates = sorted({_normalize_trade_date(item) for item in watchlist["trade_date"].dropna().tolist()})
    if requested_trade_date is None:
        return available_dates[-1]
    trade_date = _normalize_trade_date(requested_trade_date)
    if trade_date not in available_dates:
        rendered_dates = ", ".join(str(item) for item in available_dates)
        raise ValueError(f"Trade date {trade_date} not present in watchlist. Available: {rendered_dates}")
    return trade_date


def filter_watchlist(
    watchlist: pd.DataFrame,
    *,
    trade_date: date,
    symbols: Iterable[str] | None = None,
    top_n: int | None = None,
) -> pd.DataFrame:
    filtered = watchlist.loc[watchlist["trade_date"] == trade_date].copy()
    symbol_filter = {item.upper() for item in (symbols or [])}
    if symbol_filter:
        filtered = filtered.loc[filtered["symbol"].isin(symbol_filter)].copy()
    filtered = filtered.sort_values(["watchlist_rank", "symbol"], ascending=[True, True]).reset_index(drop=True)
    if top_n is not None and top_n > 0:
        filtered = filtered.head(top_n).copy()
    return filtered


def build_order_intents(watchlist: pd.DataFrame, execution_cfg: IBKRExecutionConfig) -> list[IBKROrderIntent]:
    intents: list[IBKROrderIntent] = []
    for _, row in watchlist.iterrows():
        for level_tag in ("l1", "l2", "l3"):
            quantity = int(row.get(f"{level_tag}_quantity", 0) or 0)
            if quantity <= 0:
                continue
            symbol = str(row["symbol"]).upper()
            trade_date = _normalize_trade_date(row["trade_date"])
            rank = int(row["watchlist_rank"])
            order_ref = f"skipp-{trade_date.isoformat()}-{symbol}-{level_tag.upper()}"

            entry_limit = round(_as_valid_price(row[f"{level_tag}_limit_buy"], field_name=f"{level_tag}_limit_buy"), 4)
            take_profit = round(_as_valid_price(row[f"{level_tag}_take_profit"], field_name=f"{level_tag}_take_profit"), 4)
            stop_loss = round(_as_valid_price(row[f"{level_tag}_stop_loss"], field_name=f"{level_tag}_stop_loss"), 4)
            trailing_stop_pct = _as_valid_nonnegative_fraction(
                row[f"{level_tag}_trailing_stop_pct"],
                field_name=f"{level_tag}_trailing_stop_pct",
            )
            trailing_stop_anchor = round(
                _as_valid_price(row[f"{level_tag}_trailing_stop_anchor"], field_name=f"{level_tag}_trailing_stop_anchor"),
                4,
            )
            intents.append(
                IBKROrderIntent(
                    trade_date=trade_date,
                    symbol=symbol,
                    watchlist_rank=rank,
                    level_tag=level_tag.upper(),
                    quantity=quantity,
                    entry_limit=entry_limit,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                    trailing_stop_pct=trailing_stop_pct,
                    trailing_stop_anchor=trailing_stop_anchor,
                    premarket_last=round(_as_valid_price(row["premarket_last"], field_name="premarket_last"), 4),
                    gap_pct=float(row["prev_close_to_premarket_pct"]),
                    tif=execution_cfg.tif,
                    outside_rth=execution_cfg.outside_rth,
                    exit_mode=execution_cfg.exit_mode,
                    order_ref=order_ref,
                )
            )
    return intents


def build_preview_payload(
    intents: list[IBKROrderIntent],
    *,
    connection_cfg: IBKRConnectionConfig | None,
    source_metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": source_metadata,
        "connection": None if connection_cfg is None else asdict(connection_cfg),
        "order_count": len(intents),
        "orders": [asdict(intent) for intent in intents],
    }


def _import_ibkr_types() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from ib_insync import IB, LimitOrder, MarketOrder, Order, Stock
    except ImportError as exc:  # pragma: no cover - exercised manually in runtime
        raise RuntimeError(
            "ib_insync is not installed. Install dependencies with `pip install -r requirements.txt`."
        ) from exc
    return IB, Stock, LimitOrder, MarketOrder, Order


def check_ibkr_connection(connection_cfg: IBKRConnectionConfig) -> dict[str, Any]:
    IB, _, _, _, _ = _import_ibkr_types()
    ib = IB()
    try:
        ib.connect(
            connection_cfg.host,
            connection_cfg.port,
            clientId=connection_cfg.client_id,
            timeout=connection_cfg.timeout_seconds,
            readonly=connection_cfg.readonly,
        )
        return {
            "connected": ib.isConnected(),
            "host": connection_cfg.host,
            "port": connection_cfg.port,
            "client_id": connection_cfg.client_id,
            "server_version": ib.client.serverVersion(),
            "accounts": list(ib.wrapper.accounts),
            "next_order_id": ib.client.getReqId(),
        }
    finally:
        if ib.isConnected():
            ib.disconnect()


def _apply_common_order_fields(
    order: Any,
    intent: IBKROrderIntent,
    connection_cfg: IBKRConnectionConfig,
    *,
    order_ref: str,
) -> None:
    order.tif = intent.tif
    order.outsideRth = intent.outside_rth
    order.orderRef = order_ref
    if connection_cfg.account:
        order.account = connection_cfg.account


def _build_tp_trail_orders(
    *,
    ib: Any,
    LimitOrder: Any,
    Order: Any,
    intent: IBKROrderIntent,
    connection_cfg: IBKRConnectionConfig,
) -> list[Any]:
    parent_id = ib.client.getReqId()
    oca_group = f"{intent.order_ref}-oca"
    parent = LimitOrder("BUY", intent.quantity, intent.entry_limit)
    parent.orderId = parent_id
    parent.transmit = False
    _apply_common_order_fields(parent, intent, connection_cfg, order_ref=f"{intent.order_ref}-entry")

    take_profit = LimitOrder("SELL", intent.quantity, intent.take_profit)
    take_profit.orderId = ib.client.getReqId()
    take_profit.parentId = parent_id
    take_profit.transmit = False
    take_profit.ocaGroup = oca_group
    take_profit.ocaType = 1
    _apply_common_order_fields(take_profit, intent, connection_cfg, order_ref=f"{intent.order_ref}-tp")

    trailing_stop = Order(
        action="SELL",
        orderType="TRAIL",
        totalQuantity=intent.quantity,
        trailingPercent=round(intent.trailing_stop_pct * 100.0, 4),
    )
    trailing_stop.orderId = ib.client.getReqId()
    trailing_stop.parentId = parent_id
    trailing_stop.ocaGroup = oca_group
    trailing_stop.ocaType = 1
    trailing_stop.trailStopPrice = intent.trailing_stop_anchor
    trailing_stop.transmit = True
    _apply_common_order_fields(trailing_stop, intent, connection_cfg, order_ref=f"{intent.order_ref}-trail")
    return [parent, take_profit, trailing_stop]


def monitor_open_orders(
    ib: Any,
    *,
    symbols: Iterable[str] | None = None,
    related_order_refs: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    symbol_filter = _normalize_symbol_filter(symbols)
    ref_filter = _normalize_order_ref_filter(related_order_refs)
    rows: list[dict[str, Any]] = []
    for trade in ib.openTrades():
        contract_symbol = str(getattr(trade.contract, "symbol", "")).upper()
        order_ref = str(getattr(trade.order, "orderRef", ""))
        if symbol_filter and contract_symbol not in symbol_filter:
            continue
        if ref_filter and order_ref not in ref_filter:
            continue
        rows.append(
            {
                "symbol": contract_symbol,
                "order_id": int(getattr(trade.order, "orderId", 0) or 0),
                "perm_id": int(getattr(trade.order, "permId", 0) or 0),
                "parent_id": int(getattr(trade.order, "parentId", 0) or 0),
                "order_ref": order_ref,
                "order_type": str(getattr(trade.order, "orderType", "")),
                "action": str(getattr(trade.order, "action", "")),
                "total_quantity": float(getattr(trade.order, "totalQuantity", 0) or 0),
                "filled": float(getattr(trade.orderStatus, "filled", 0) or 0),
                "remaining": float(getattr(trade.orderStatus, "remaining", 0) or 0),
                "avg_fill_price": float(getattr(trade.orderStatus, "avgFillPrice", 0) or 0),
                "lmt_price": float(getattr(trade.order, "lmtPrice", 0) or 0) if getattr(trade.order, "lmtPrice", None) not in (None, "") else None,
                "aux_price": float(getattr(trade.order, "auxPrice", 0) or 0) if getattr(trade.order, "auxPrice", None) not in (None, "") else None,
                "status": str(getattr(trade.orderStatus, "status", "")),
            }
        )
    rows.sort(key=lambda item: (item["symbol"], item["order_id"], item["order_ref"]))
    return rows


def reconcile_fills_and_positions(
    ib: Any,
    *,
    symbols: Iterable[str] | None = None,
    related_order_refs: Iterable[str] | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    symbol_filter = _normalize_symbol_filter(symbols)
    ref_filter = _normalize_order_ref_filter(related_order_refs)

    fills: list[dict[str, Any]] = []
    for fill in ib.fills():
        contract_symbol = str(getattr(fill.contract, "symbol", "")).upper()
        execution = getattr(fill, "execution", None)
        order_ref = str(getattr(execution, "orderRef", "")) if execution is not None else ""
        if symbol_filter and contract_symbol not in symbol_filter:
            continue
        if ref_filter and order_ref and order_ref not in ref_filter:
            continue
        fills.append(
            {
                "symbol": contract_symbol,
                "order_id": int(getattr(execution, "orderId", 0) or 0),
                "perm_id": int(getattr(execution, "permId", 0) or 0),
                "order_ref": order_ref,
                "side": str(getattr(execution, "side", "")),
                "shares": float(getattr(execution, "shares", 0) or 0),
                "price": float(getattr(execution, "price", 0) or 0),
                "time": str(getattr(execution, "time", "")),
            }
        )

    positions: list[dict[str, Any]] = []
    for position in ib.positions():
        position_symbol = str(getattr(position.contract, "symbol", "")).upper()
        position_account = str(getattr(position, "account", ""))
        if symbol_filter and position_symbol not in symbol_filter:
            continue
        if account and position_account != account:
            continue
        positions.append(
            {
                "symbol": position_symbol,
                "account": position_account,
                "position": float(getattr(position, "position", 0) or 0),
                "avg_cost": float(getattr(position, "avgCost", 0) or 0),
            }
        )

    positions.sort(key=lambda item: (item["symbol"], item["account"]))
    fills.sort(key=lambda item: (item["symbol"], item["order_id"], item["time"]))
    return {
        "open_orders": monitor_open_orders(ib, symbols=symbol_filter, related_order_refs=ref_filter),
        "fills": fills,
        "positions": positions,
    }


def cancel_symbol_orders_after(
    ib: Any,
    *,
    trade_date: date,
    symbol: str,
    entry_order_refs: Iterable[str],
    trigger_at: str | None,
    timezone_name: str,
) -> dict[str, Any]:
    trigger_dt = _resolve_trigger_datetime(trade_date, trigger_at, timezone_name)
    if trigger_dt is None:
        return {"action": "cancel_unfilled", "symbol": symbol, "scheduled": False, "canceled_order_ids": []}

    _sleep_until(trigger_dt)
    ref_filter = set(entry_order_refs)
    canceled_order_ids: list[int] = []
    for trade in ib.openTrades():
        contract_symbol = str(getattr(trade.contract, "symbol", "")).upper()
        order_ref = str(getattr(trade.order, "orderRef", ""))
        status = str(getattr(trade.orderStatus, "status", ""))
        if contract_symbol != symbol.upper() or order_ref not in ref_filter or not _is_live_order_status(status):
            continue
        ib.cancelOrder(trade.order)
        canceled_order_ids.append(int(trade.order.orderId))
    return {
        "action": "cancel_unfilled",
        "symbol": symbol,
        "scheduled": True,
        "trigger_at": trigger_dt.isoformat(),
        "canceled_order_ids": canceled_order_ids,
    }


def flatten_after(
    ib: Any,
    *,
    trade_date: date,
    symbol: str,
    related_order_refs: Iterable[str],
    trigger_at: str | None,
    timezone_name: str,
    connection_cfg: IBKRConnectionConfig,
    execution_cfg: IBKRExecutionConfig,
) -> dict[str, Any]:
    trigger_dt = _resolve_trigger_datetime(trade_date, trigger_at, timezone_name)
    if trigger_dt is None:
        return {"action": "flatten", "symbol": symbol, "scheduled": False, "flattened_quantity": 0}

    _sleep_until(trigger_dt)
    ref_filter = set(related_order_refs)
    canceled_order_ids: list[int] = []
    for trade in ib.openTrades():
        contract_symbol = str(getattr(trade.contract, "symbol", "")).upper()
        order_ref = str(getattr(trade.order, "orderRef", ""))
        status = str(getattr(trade.orderStatus, "status", ""))
        if contract_symbol != symbol.upper() or order_ref not in ref_filter or not _is_live_order_status(status):
            continue
        ib.cancelOrder(trade.order)
        canceled_order_ids.append(int(trade.order.orderId))

    net_quantity = 0.0
    for position in ib.positions():
        position_symbol = str(getattr(position.contract, "symbol", "")).upper()
        account = str(getattr(position, "account", ""))
        if position_symbol != symbol.upper():
            continue
        if connection_cfg.account and account != connection_cfg.account:
            continue
        net_quantity += float(position.position)

    if abs(net_quantity) < 1e-9:
        return {
            "action": "flatten",
            "symbol": symbol,
            "scheduled": True,
            "trigger_at": trigger_dt.isoformat(),
            "canceled_order_ids": canceled_order_ids,
            "flattened_quantity": 0,
            "status": "no_open_position",
        }

    _, Stock, _, MarketOrder, _ = _import_ibkr_types()
    contract = Stock(symbol, execution_cfg.exchange, execution_cfg.currency)
    ib.qualifyContracts(contract)
    flatten_quantity = int(round(abs(net_quantity)))
    action = "SELL" if net_quantity > 0 else "BUY"
    market_order = MarketOrder(action, flatten_quantity)
    market_order.tif = execution_cfg.tif
    market_order.outsideRth = execution_cfg.outside_rth
    market_order.orderRef = f"skipp-{trade_date.isoformat()}-{symbol}-flatten"
    if connection_cfg.account:
        market_order.account = connection_cfg.account
    trade = ib.placeOrder(contract, market_order)
    return {
        "action": "flatten",
        "symbol": symbol,
        "scheduled": True,
        "trigger_at": trigger_dt.isoformat(),
        "canceled_order_ids": canceled_order_ids,
        "flattened_quantity": flatten_quantity,
        "order_id": int(market_order.orderId),
        "status": str(trade.orderStatus.status),
    }


def place_order_intents_with_ib(
    ib: Any,
    intents: list[IBKROrderIntent],
    *,
    connection_cfg: IBKRConnectionConfig,
    execution_cfg: IBKRExecutionConfig,
) -> dict[str, Any]:
    placements: list[dict[str, Any]] = []
    entry_order_refs_by_symbol: dict[str, list[str]] = {}
    all_order_refs_by_symbol: dict[str, list[str]] = {}
    trade_dates_by_symbol: dict[str, str] = {}
    _, Stock, LimitOrder, _, Order = _import_ibkr_types()
    for intent in intents:
        contract = Stock(intent.symbol, execution_cfg.exchange, execution_cfg.currency)
        ib.qualifyContracts(contract)

        if execution_cfg.exit_mode == "tp-stop":
            orders = ib.bracketOrder(
                action="BUY",
                quantity=intent.quantity,
                limitPrice=intent.entry_limit,
                takeProfitPrice=intent.take_profit,
                stopLossPrice=intent.stop_loss,
            )
            suffixes = ("entry", "tp", "sl")
            for order, suffix in zip(orders, suffixes, strict=False):
                order_ref = f"{intent.order_ref}-{suffix}"
                _apply_common_order_fields(order, intent, connection_cfg, order_ref=order_ref)
        elif execution_cfg.exit_mode == "tp-trail":
            orders = _build_tp_trail_orders(
                ib=ib,
                LimitOrder=LimitOrder,
                Order=Order,
                intent=intent,
                connection_cfg=connection_cfg,
            )
        else:  # pragma: no cover - parser constrains choices
            raise ValueError(f"Unsupported exit mode: {execution_cfg.exit_mode}")

        symbol_key = intent.symbol.upper()
        trade_dates_by_symbol[symbol_key] = intent.trade_date.isoformat()
        entry_order_refs_by_symbol.setdefault(symbol_key, []).append(f"{intent.order_ref}-entry")
        all_order_refs_by_symbol.setdefault(symbol_key, []).extend(str(order.orderRef) for order in orders)

        placed_orders = []
        for order in orders:
            trade = ib.placeOrder(contract, order)
            placed_orders.append(
                {
                    "placed_at": datetime.now(ZoneInfo("UTC")).isoformat(),
                    "order_id": int(order.orderId),
                    "perm_id": int(order.permId or 0),
                    "order_ref": str(order.orderRef),
                    "order_type": str(order.orderType),
                    "action": str(order.action),
                    "lmt_price": float(order.lmtPrice) if getattr(order, "lmtPrice", None) not in (None, "") else None,
                    "aux_price": float(order.auxPrice) if getattr(order, "auxPrice", None) not in (None, "") else None,
                    "status": str(trade.orderStatus.status),
                }
            )

        placements.append(
            {
                "symbol": intent.symbol,
                "trade_date": intent.trade_date.isoformat(),
                "level_tag": intent.level_tag,
                "quantity": intent.quantity,
                "exit_mode": execution_cfg.exit_mode,
                "orders": placed_orders,
            }
        )

    return {
        "placements": placements,
        "entry_order_refs_by_symbol": entry_order_refs_by_symbol,
        "all_order_refs_by_symbol": all_order_refs_by_symbol,
        "trade_dates_by_symbol": trade_dates_by_symbol,
    }


def place_order_intents(
    intents: list[IBKROrderIntent],
    *,
    connection_cfg: IBKRConnectionConfig,
    execution_cfg: IBKRExecutionConfig,
) -> dict[str, Any]:
    IB, _, _, _, _ = _import_ibkr_types()
    ib = IB()
    try:
        ib.connect(
            connection_cfg.host,
            connection_cfg.port,
            clientId=connection_cfg.client_id,
            timeout=connection_cfg.timeout_seconds,
            readonly=False,
        )
        return place_order_intents_with_ib(ib, intents, connection_cfg=connection_cfg, execution_cfg=execution_cfg)
    finally:
        if ib.isConnected():
            ib.disconnect()


def supervise_open_execution(
    ib: Any,
    *,
    connection_cfg: IBKRConnectionConfig,
    execution_cfg: IBKRExecutionConfig,
    trade_dates_by_symbol: dict[str, str],
    entry_order_refs_by_symbol: dict[str, list[str]],
    all_order_refs_by_symbol: dict[str, list[str]],
    poll_interval_seconds: float = 1.0,
    timeout_seconds: float = 900.0,
    reconnect_max_attempts: int = DEFAULT_RECONNECT_MAX_ATTEMPTS,
    reconnect_wait_seconds: float = DEFAULT_RECONNECT_WAIT_SECONDS,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    symbols = sorted(trade_dates_by_symbol)
    schedule_timezone = execution_cfg.clock_timezone
    try:
        tz = ZoneInfo(schedule_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {schedule_timezone}") from exc
    now_reference = datetime.now(tz)
    deadline = now_reference + timedelta(seconds=timeout_seconds)

    cancel_done: set[str] = set()
    flatten_done: set[str] = set()
    events: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []

    cancel_schedule = {
        symbol: _resolve_trigger_datetime(_normalize_trade_date(trade_date), execution_cfg.cancel_unfilled_after, schedule_timezone)
        for symbol, trade_date in trade_dates_by_symbol.items()
    }
    flatten_schedule = {
        symbol: _resolve_trigger_datetime(_normalize_trade_date(trade_date), execution_cfg.time_stop_after, schedule_timezone)
        for symbol, trade_date in trade_dates_by_symbol.items()
    }

    while True:
        now = datetime.now(tz)
        snapshot = _call_with_reconnect(
            ib,
            operation_name="reconcile_snapshot",
            operation=lambda: reconcile_fills_and_positions(
                ib,
                symbols=symbols,
                related_order_refs=[ref for refs in all_order_refs_by_symbol.values() for ref in refs],
                account=connection_cfg.account,
            ),
            connection_cfg=connection_cfg,
            reconnect_max_attempts=reconnect_max_attempts,
            reconnect_wait_seconds=reconnect_wait_seconds,
            events=events,
        )
        snapshots.append({"captured_at": now.isoformat(), **snapshot})

        for symbol in symbols:
            cancel_at = cancel_schedule.get(symbol)
            if symbol not in cancel_done and cancel_at is not None and now >= cancel_at:
                events.append(
                    _call_with_reconnect(
                        ib,
                        operation_name=f"cancel_unfilled:{symbol}",
                        operation=lambda symbol=symbol: cancel_symbol_orders_after(
                            ib,
                            trade_date=_normalize_trade_date(trade_dates_by_symbol[symbol]),
                            symbol=symbol,
                            entry_order_refs=entry_order_refs_by_symbol.get(symbol, []),
                            trigger_at=execution_cfg.cancel_unfilled_after,
                            timezone_name=schedule_timezone,
                        ),
                        connection_cfg=connection_cfg,
                        reconnect_max_attempts=reconnect_max_attempts,
                        reconnect_wait_seconds=reconnect_wait_seconds,
                        events=events,
                    )
                )
                cancel_done.add(symbol)

        for symbol in symbols:
            flatten_at = flatten_schedule.get(symbol)
            if symbol not in flatten_done and flatten_at is not None and now >= flatten_at:
                events.append(
                    _call_with_reconnect(
                        ib,
                        operation_name=f"flatten:{symbol}",
                        operation=lambda symbol=symbol: flatten_after(
                            ib,
                            trade_date=_normalize_trade_date(trade_dates_by_symbol[symbol]),
                            symbol=symbol,
                            related_order_refs=all_order_refs_by_symbol.get(symbol, []),
                            trigger_at=execution_cfg.time_stop_after,
                            timezone_name=schedule_timezone,
                            connection_cfg=connection_cfg,
                            execution_cfg=execution_cfg,
                        ),
                        connection_cfg=connection_cfg,
                        reconnect_max_attempts=reconnect_max_attempts,
                        reconnect_wait_seconds=reconnect_wait_seconds,
                        events=events,
                    )
                )
                flatten_done.add(symbol)

        post_action_snapshot = _call_with_reconnect(
            ib,
            operation_name="reconcile_final",
            operation=lambda: reconcile_fills_and_positions(
                ib,
                symbols=symbols,
                related_order_refs=[ref for refs in all_order_refs_by_symbol.values() for ref in refs],
                account=connection_cfg.account,
            ),
            connection_cfg=connection_cfg,
            reconnect_max_attempts=reconnect_max_attempts,
            reconnect_wait_seconds=reconnect_wait_seconds,
            events=events,
        )

        schedules_finished = all(symbol in cancel_done or cancel_schedule.get(symbol) is None for symbol in symbols) and all(
            symbol in flatten_done or flatten_schedule.get(symbol) is None for symbol in symbols
        )
        if schedules_finished and not post_action_snapshot["open_orders"]:
            return {
                "timed_out": False,
                "events": events,
                "snapshots": snapshots,
                "final": post_action_snapshot,
            }

        if now >= deadline:
            return {
                "timed_out": True,
                "events": events,
                "snapshots": snapshots,
                "final": post_action_snapshot,
            }

        time_module.sleep(max(0.1, poll_interval_seconds))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert Databento watchlists into IBKR order previews or live TWS orders.")
    parser.add_argument("--watchlist-csv", default=str(DEFAULT_WATCHLIST_CSV), help="Existing watchlist CSV. If omitted and --bundle is provided, a fresh watchlist is generated in-memory.")
    parser.add_argument("--bundle", default=None, help="Databento bundle manifest or directory. Used when generating a watchlist on the fly.")
    parser.add_argument("--export-dir", default=None, help="Directory with exact named Databento exports if --bundle is not used.")
    parser.add_argument("--trade-date", default=None, help="Trade date to execute, defaults to the latest trade_date in the watchlist.")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbol allowlist.")
    parser.add_argument("--top-n", type=int, default=None, help="Optional limit after filtering the selected trade date.")
    parser.add_argument("--output-json", default=str(DEFAULT_PREVIEW_JSON), help="Dry-run JSON output path.")
    parser.add_argument("--place-orders", action="store_true", help="Actually place orders in TWS/IB Gateway. Default is dry-run only.")
    parser.add_argument("--check-connection", action="store_true", help="Probe the IBKR connection and print handshake metadata.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=71)
    parser.add_argument("--account", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--tif", default="DAY", choices=["DAY", "GTC"])
    parser.add_argument("--outside-rth", action="store_true", help="Allow orders to work outside regular trading hours.")
    parser.add_argument("--exit-mode", default="tp-stop", choices=["tp-stop", "tp-trail"], help="Choose a standard take-profit + stop bracket or take-profit + trailing-stop bracket.")
    parser.add_argument("--cancel-unfilled-after", default=DEFAULT_CANCEL_UNFILLED_AFTER, help="Cancel unfilled entry orders after HH:MM[:SS] in the configured timezone. Use 'off' to disable.")
    parser.add_argument("--time-stop-after", default=DEFAULT_TIME_STOP_AFTER, help="Flatten open positions after HH:MM[:SS] in the configured timezone. Use 'off' to disable.")
    parser.add_argument("--clock-timezone", default=DEFAULT_SCHEDULE_TIMEZONE, help="IANA timezone used for timed cancel/flatten actions.")
    parser.add_argument("--min-gap-pct", type=float, default=LONG_DIP_MIN_GAP_PCT)
    parser.add_argument("--max-gap-pct", type=float, default=LONG_DIP_MAX_GAP_PCT)
    parser.add_argument("--min-previous-close", type=float, default=LONG_DIP_MIN_PREVIOUS_CLOSE)
    parser.add_argument("--min-premarket-dollar-volume", type=float, default=LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME)
    parser.add_argument("--min-premarket-volume", type=int, default=LONG_DIP_MIN_PREMARKET_VOLUME)
    parser.add_argument("--min-premarket-trade-count", type=int, default=LONG_DIP_MIN_PREMARKET_TRADE_COUNT)
    parser.add_argument(
        "--position-budget-usd",
        "--position-budget-eur",
        dest="position_budget_usd",
        type=float,
        default=LONG_DIP_POSITION_BUDGET_USD,
    )
    parser.add_argument("--watchlist-top-n", type=int, default=LONG_DIP_TOP_N, help="Top-N candidates per day when generating watchlists from a bundle.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    connection_cfg = IBKRConnectionConfig(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        account=args.account,
        timeout_seconds=args.timeout_seconds,
        readonly=not args.place_orders,
    )
    execution_cfg = IBKRExecutionConfig(
        tif=args.tif,
        outside_rth=args.outside_rth,
        exit_mode=args.exit_mode,
        cancel_unfilled_after=_normalize_schedule_value(args.cancel_unfilled_after),
        time_stop_after=_normalize_schedule_value(args.time_stop_after),
        clock_timezone=args.clock_timezone,
    )
    max_gap_pct = None if args.max_gap_pct is not None and args.max_gap_pct < 0 else args.max_gap_pct
    watchlist_cfg = LongDipConfig(
        min_gap_pct=args.min_gap_pct,
        max_gap_pct=max_gap_pct,
        min_previous_close=args.min_previous_close,
        min_premarket_dollar_volume=args.min_premarket_dollar_volume,
        min_premarket_volume=args.min_premarket_volume,
        min_premarket_trade_count=args.min_premarket_trade_count,
        position_budget_usd=args.position_budget_usd,
        top_n=args.watchlist_top_n,
    )

    watchlist_csv = None if args.bundle else args.watchlist_csv
    watchlist, source_metadata = load_watchlist_frame(
        watchlist_csv=watchlist_csv,
        bundle=args.bundle,
        export_dir=args.export_dir,
        watchlist_cfg=watchlist_cfg,
    )
    selected_trade_date = resolve_trade_date(watchlist, args.trade_date)
    filtered_watchlist = filter_watchlist(
        watchlist,
        trade_date=selected_trade_date,
        symbols=_parse_symbol_filter(args.symbols),
        top_n=args.top_n,
    )
    intents = build_order_intents(filtered_watchlist, execution_cfg)

    preview_payload = build_preview_payload(
        intents,
        connection_cfg=connection_cfg,
        source_metadata={
            **source_metadata,
            "selected_trade_date": selected_trade_date.isoformat(),
            "symbols": _parse_symbol_filter(args.symbols),
            "top_n": args.top_n,
            "exit_mode": execution_cfg.exit_mode,
            "cancel_unfilled_after": execution_cfg.cancel_unfilled_after,
            "time_stop_after": execution_cfg.time_stop_after,
            "clock_timezone": execution_cfg.clock_timezone,
        },
    )
    output_json = Path(args.output_json).expanduser()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(preview_payload, indent=2, default=str), encoding="utf-8")

    print("WATCHLIST_SOURCE", source_metadata)
    print("SELECTED_TRADE_DATE", selected_trade_date.isoformat())
    print("FILTERED_ROWS", len(filtered_watchlist))
    print("ORDER_INTENTS", len(intents))
    print("PREVIEW_JSON", output_json)

    if args.check_connection:
        connection_payload = check_ibkr_connection(connection_cfg)
        print("IBKR_CONNECTION", json.dumps(connection_payload, indent=2, default=str))

    if not args.place_orders:
        print(json.dumps(preview_payload, indent=2, default=str))
        return

    if not intents:
        print("PLACEMENTS []")
        return

    placements = place_order_intents(intents, connection_cfg=connection_cfg, execution_cfg=execution_cfg)
    print("PLACEMENTS", json.dumps(placements, indent=2, default=str))


if __name__ == "__main__":
    main()