from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor

TRADINGVIEW_WATCHLIST_JSON = Path(__file__).resolve().parents[2] / "reports" / "tradingview_watchlist_snapshot.json"


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="tradingview_watchlist_json",
        path_hint="reports/tradingview_watchlist_snapshot.json",
        capabilities=SourceCapabilities(
            has_structure=False,
            has_meta=True,
            structure_mode="none",
            meta_mode="partial",
        ),
        notes=[
            "TradingView watchlist snapshot source with symbol-level context.",
            "No explicit BOS/OB/FVG/sweep events are published by this source.",
        ],
    )


def _load_payload() -> dict[str, Any]:
    if not TRADINGVIEW_WATCHLIST_JSON.exists():
        raise FileNotFoundError(f"tradingview source not found: {TRADINGVIEW_WATCHLIST_JSON}")
    payload = json.loads(TRADINGVIEW_WATCHLIST_JSON.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"tradingview payload must be an object: {TRADINGVIEW_WATCHLIST_JSON}")
    return payload


def _asof_ts_from_trade_date(trade_date: str) -> float:
    parsed = datetime.fromisoformat(trade_date).date()
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp()


def _extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("symbols", "watchlist", "items", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            out = [row for row in rows if isinstance(row, dict)]
            if out:
                return out
    raise ValueError("tradingview payload has no symbol rows")


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _select_symbol_row(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("symbol must not be empty")

    rows = _extract_rows(payload)
    matching = [row for row in rows if str(row.get("symbol", "")).strip().upper() == wanted]
    if not matching:
        raise ValueError(f"symbol {wanted} not present in tradingview source")

    def _sort_key(row: dict[str, Any]) -> tuple[str, float]:
        trade_date = str(row.get("trade_date", "")).strip()
        asof_ts = _coerce_optional_float(row.get("asof_ts")) or 0.0
        return trade_date, asof_ts

    return sorted(matching, key=_sort_key, reverse=True)[0]


def load_raw_structure_input(symbol: str, timeframe: str) -> dict[str, Any]:
    del timeframe
    payload = _load_payload()
    _select_symbol_row(payload, symbol)
    return {
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }


def load_raw_meta_input(symbol: str, timeframe: str) -> dict[str, Any]:
    payload = _load_payload()
    row = _select_symbol_row(payload, symbol)

    trade_date = str(row.get("trade_date", "")).strip()
    asof_ts_opt = _coerce_optional_float(row.get("asof_ts"))
    if asof_ts_opt is not None:
        asof_ts = asof_ts_opt
    elif trade_date:
        asof_ts = _asof_ts_from_trade_date(trade_date)
    else:
        raise ValueError("tradingview row is missing both asof_ts and trade_date")

    regime = str(row.get("volume_regime", "NORMAL")).strip().upper() or "NORMAL"
    if regime not in {"NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"}:
        regime = "NORMAL"

    thin_fraction_raw = row.get("thin_fraction", 0.0)
    try:
        thin_fraction = float(thin_fraction_raw)
    except (TypeError, ValueError):
        thin_fraction = 0.0

    resolved_symbol = str(row.get("symbol", symbol)).strip().upper()
    return {
        "symbol": resolved_symbol,
        "timeframe": str(timeframe).strip(),
        "asof_ts": asof_ts,
        "volume": {
            "value": {
                "regime": regime,
                "thin_fraction": thin_fraction,
            },
            "asof_ts": asof_ts,
            "stale": False,
        },
        "provenance": [
            "repo:reports/tradingview_watchlist_snapshot.json",
            f"repo:reports/tradingview_watchlist_snapshot.json#symbol={resolved_symbol}",
            "smc_integration:partial_structure_only",
        ],
    }
