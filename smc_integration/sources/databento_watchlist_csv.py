from __future__ import annotations

import csv
import logging
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor

WATCHLIST_CSV = Path(__file__).resolve().parents[2] / "reports" / "databento_watchlist_top5_pre1530.csv"
_LOG = logging.getLogger(__name__)


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
            "Volume regime is derived from same-day premarket liquidity columns when available and surfaced as UNKNOWN otherwise.",
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


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _same_trade_date_rows(rows: list[dict[str, str]], trade_date: str) -> list[dict[str, str]]:
    return [row for row in rows if str(row.get("trade_date", "")).strip() == trade_date]


def _positive_peer_values(rows: list[dict[str, str]], field_name: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw_value = _coerce_optional_float(row.get(field_name))
        if raw_value is None or raw_value <= 0:
            continue
        values.append(raw_value)
    return values


def _derive_volume_meta(row: dict[str, str], peer_rows: list[dict[str, str]]) -> dict[str, Any]:
    liquidity_ratios: list[float] = []
    for field_name in ("premarket_volume", "premarket_trade_count"):
        peer_values = _positive_peer_values(peer_rows, field_name)
        row_value = _coerce_optional_float(row.get(field_name))
        if row_value is None or row_value < 0 or not peer_values:
            continue
        peer_median = statistics.median(peer_values)
        if peer_median <= 0:
            continue
        liquidity_ratios.append(max(0.0, row_value) / peer_median)

    if not liquidity_ratios:
        _LOG.info(
            "databento volume regime UNKNOWN for %s on %s: no usable premarket liquidity ratios",
            str(row.get("symbol") or "").strip().upper() or "?",
            str(row.get("trade_date") or "").strip() or "?",
        )
        return {
            "regime": "UNKNOWN",
            "thin_fraction": None,
        }

    liquidity_ratio = min(liquidity_ratios)
    clamped_ratio = min(max(liquidity_ratio, 0.0), 1.0)
    thin_fraction = round(1.0 - clamped_ratio, 4)

    regime = "NORMAL"
    if liquidity_ratio <= 0.2:
        regime = "HOLIDAY_SUSPECT"
    elif liquidity_ratio <= 0.6:
        regime = "LOW_VOLUME"

    return {
        "regime": regime,
        "thin_fraction": thin_fraction,
    }


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
    volume_meta = _derive_volume_meta(row, _same_trade_date_rows(rows, trade_date))

    payload: dict[str, Any] = {
        "symbol": str(row.get("symbol", symbol)).strip().upper(),
        "timeframe": str(timeframe).strip(),
        "asof_ts": asof_ts,
        "volume": {
            "value": volume_meta,
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

    if volume_meta.get("regime") == "UNKNOWN":
        payload["provenance"].append("smc_integration:volume_regime_unknown_no_premarket_liquidity")
    else:
        payload["provenance"].append("smc_integration:volume_regime_derived_from_premarket_liquidity")

    return payload
