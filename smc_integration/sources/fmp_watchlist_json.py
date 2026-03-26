from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor

FMP_WATCHLIST_JSON = Path(__file__).resolve().parents[2] / "reports" / "fmp_watchlist_snapshot.json"


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="fmp_watchlist_json",
        path_hint="reports/fmp_watchlist_snapshot.json",
        capabilities=SourceCapabilities(
            has_structure=False,
            has_meta=True,
            structure_mode="none",
            meta_mode="partial",
        ),
        notes=[
            "FMP watchlist snapshot source with symbol-level context.",
            "No explicit BOS/OB/FVG/sweep events are published by this source.",
        ],
    )


def _load_payload() -> dict[str, Any]:
    if not FMP_WATCHLIST_JSON.exists():
        raise FileNotFoundError(f"fmp source not found: {FMP_WATCHLIST_JSON}")
    payload = json.loads(FMP_WATCHLIST_JSON.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"fmp payload must be an object: {FMP_WATCHLIST_JSON}")
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
    raise ValueError("fmp payload has no symbol rows")


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _coerce_bias(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if normalized in {"BULLISH", "BEARISH", "NEUTRAL"}:
        return normalized
    return None


def _extract_technical(row: dict[str, Any], *, fallback_asof_ts: float) -> dict[str, Any] | None:
    direct = row.get("technical")
    direct_map = direct if isinstance(direct, dict) else {}

    strength = _coerce_optional_float(direct_map.get("strength"))
    if strength is None:
        strength = _coerce_optional_float(row.get("technical_strength"))

    bias = _coerce_bias(direct_map.get("bias"))
    if bias is None:
        bias = _coerce_bias(row.get("technical_bias"))

    if strength is None or bias is None:
        return None

    asof_ts = _coerce_optional_float(direct_map.get("asof_ts"))
    if asof_ts is None:
        asof_ts = _coerce_optional_float(row.get("technical_asof_ts"))
    if asof_ts is None:
        asof_ts = fallback_asof_ts

    stale = _coerce_optional_bool(direct_map.get("stale"))
    if stale is None:
        stale = _coerce_optional_bool(row.get("technical_stale"))
    if stale is None:
        stale = False

    return {
        "value": {
            "strength": strength,
            "bias": bias,
        },
        "asof_ts": asof_ts,
        "stale": stale,
    }


def _select_symbol_row(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("symbol must not be empty")

    rows = _extract_rows(payload)
    matching = [row for row in rows if str(row.get("symbol", "")).strip().upper() == wanted]
    if not matching:
        raise ValueError(f"symbol {wanted} not present in fmp source")

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
        raise ValueError("fmp row is missing both asof_ts and trade_date")

    regime = str(row.get("volume_regime", "NORMAL")).strip().upper() or "NORMAL"
    if regime not in {"NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"}:
        regime = "NORMAL"

    thin_fraction_raw = row.get("thin_fraction", 0.0)
    try:
        thin_fraction = float(thin_fraction_raw)
    except (TypeError, ValueError):
        thin_fraction = 0.0

    resolved_symbol = str(row.get("symbol", symbol)).strip().upper()
    payload = {
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
            "repo:reports/fmp_watchlist_snapshot.json",
            f"repo:reports/fmp_watchlist_snapshot.json#symbol={resolved_symbol}",
            "smc_integration:partial_structure_only",
        ],
    }

    technical = _extract_technical(row, fallback_asof_ts=asof_ts)
    if technical is not None:
        payload["technical"] = technical
        payload["provenance"].append("smc_integration:technical_mapped_from_fmp")

    return payload
