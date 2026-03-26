from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor

WATCHLIST_CSV = Path(__file__).resolve().parents[2] / "reports" / "databento_watchlist_top5_pre1530.csv"


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="databento_watchlist_csv",
        path_hint="reports/databento_watchlist_top5_pre1530.csv",
        capabilities=SourceCapabilities(
            has_structure=True,
            has_meta=True,
            structure_mode="partial",
            meta_mode="partial",
        ),
        notes=[
            "Real repo watchlist source with symbol and trade-date context.",
            "Does not publish explicit BOS/OB/FVG/sweep events; structure mapping remains explicit empty lists.",
        ],
    )


def _load_rows() -> list[dict[str, str]]:
    if not WATCHLIST_CSV.exists():
        raise FileNotFoundError(f"watchlist source not found: {WATCHLIST_CSV}")

    with WATCHLIST_CSV.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]

    if not rows:
        raise ValueError(f"watchlist source is empty: {WATCHLIST_CSV}")
    return rows


def _select_symbol_row(rows: list[dict[str, str]], symbol: str) -> dict[str, str]:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("symbol must not be empty")

    matching = [row for row in rows if str(row.get("symbol", "")).strip().upper() == wanted]
    if not matching:
        raise ValueError(f"symbol {wanted} not present in watchlist source")

    latest_trade_date = max(str(row.get("trade_date", "")).strip() for row in matching)
    latest_rows = [row for row in matching if str(row.get("trade_date", "")).strip() == latest_trade_date]

    def _rank_value(row: dict[str, str]) -> int:
        raw = str(row.get("watchlist_rank", "")).strip()
        try:
            return int(raw)
        except ValueError:
            return 10**9

    return sorted(latest_rows, key=_rank_value)[0]


def _asof_ts_from_trade_date(trade_date: str) -> float:
    parsed = datetime.fromisoformat(trade_date).date()
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp()


def load_raw_structure_input(symbol: str, timeframe: str) -> dict[str, Any]:
    del timeframe
    rows = _load_rows()
    _select_symbol_row(rows, symbol)
    return {
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }


def load_raw_meta_input(symbol: str, timeframe: str) -> dict[str, Any]:
    rows = _load_rows()
    row = _select_symbol_row(rows, symbol)

    trade_date = str(row.get("trade_date", "")).strip()
    if not trade_date:
        raise ValueError("watchlist row is missing trade_date")

    asof_ts = _asof_ts_from_trade_date(trade_date)

    return {
        "symbol": str(row.get("symbol", symbol)).strip().upper(),
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
            "repo:reports/databento_watchlist_top5_pre1530.csv",
            f"repo:reports/databento_watchlist_top5_pre1530.csv#symbol={str(row.get('symbol', symbol)).strip().upper()}",
            f"repo:reports/databento_watchlist_top5_pre1530.csv#trade_date={trade_date}",
            "smc_integration:partial_structure_only",
        ],
    }
