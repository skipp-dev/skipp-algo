from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor

IBKR_PREVIEW_JSON = Path(__file__).resolve().parents[2] / "reports" / "ibkr_watchlist_preview_2026-03-06.json"


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="ibkr_watchlist_preview_json",
        path_hint="reports/ibkr_watchlist_preview_2026-03-06.json",
        capabilities=SourceCapabilities(
            has_structure=False,
            has_meta=True,
            structure_mode="none",
            meta_mode="partial",
        ),
        notes=[
            "Real repo watchlist preview source emitted by IBKR preview flow.",
            "Contains symbol-level order metadata but no explicit BOS/OB/FVG/sweep structure events.",
        ],
    )


def _load_payload() -> dict[str, Any]:
    if not IBKR_PREVIEW_JSON.exists():
        raise FileNotFoundError(f"ibkr preview source not found: {IBKR_PREVIEW_JSON}")
    payload = json.loads(IBKR_PREVIEW_JSON.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"ibkr preview payload must be an object: {IBKR_PREVIEW_JSON}")
    return payload


def _select_symbol_order(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("symbol must not be empty")

    orders = payload.get("orders", [])
    if not isinstance(orders, list):
        raise ValueError("ibkr preview payload has invalid orders field")

    matching = [row for row in orders if isinstance(row, dict) and str(row.get("symbol", "")).strip().upper() == wanted]
    if not matching:
        raise ValueError(f"symbol {wanted} not present in ibkr preview source")

    latest_trade_date = max(str(row.get("trade_date", "")).strip() for row in matching)
    latest_rows = [row for row in matching if str(row.get("trade_date", "")).strip() == latest_trade_date]

    def _rank_value(row: dict[str, Any]) -> int:
        raw = row.get("watchlist_rank")
        try:
            return int(str(raw))
        except (TypeError, ValueError):
            return 10**9

    return sorted(latest_rows, key=_rank_value)[0]


def _asof_ts_from_trade_date(trade_date: str) -> float:
    parsed = datetime.fromisoformat(trade_date).date()
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp()


def load_raw_structure_input(symbol: str, timeframe: str) -> dict[str, Any]:
    del timeframe
    payload = _load_payload()
    _select_symbol_order(payload, symbol)
    return {
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }


def load_raw_meta_input(symbol: str, timeframe: str) -> dict[str, Any]:
    payload = _load_payload()
    order = _select_symbol_order(payload, symbol)

    trade_date = str(order.get("trade_date", "")).strip()
    if not trade_date:
        raise ValueError("ibkr preview order is missing trade_date")

    asof_ts = _asof_ts_from_trade_date(trade_date)

    return {
        "symbol": str(order.get("symbol", symbol)).strip().upper(),
        "timeframe": str(timeframe).strip(),
        "asof_ts": asof_ts,
        "volume": {
            "value": {
                "regime": "NORMAL",
                "thin_fraction": 0.0,
            },
            "asof_ts": asof_ts,
            "stale": False,
        },
        "provenance": [
            "repo:reports/ibkr_watchlist_preview_2026-03-06.json",
            f"repo:reports/ibkr_watchlist_preview_2026-03-06.json#symbol={str(order.get('symbol', symbol)).strip().upper()}",
            f"repo:reports/ibkr_watchlist_preview_2026-03-06.json#trade_date={trade_date}",
            "smc_integration:partial_structure_only",
        ],
    }
