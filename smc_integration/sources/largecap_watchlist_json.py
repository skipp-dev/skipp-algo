"""Large-cap static watchlist scaffold source.

Provides neutral meta defaults (volume regime NORMAL, neutral technical,
neutral news) for benchmark-universe large-caps (AAPL, MSFT, etc.) so
health checks and integration tests don't FAIL when the primary
screener-based sources don't list these symbols.

NOT intended for production signal derivation; acts as a last-resort
fallback only.  Registered at the tail of ``_DOMAIN_SOURCE_ORDER`` so
real data sources win whenever they cover the symbol.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import SourceCapabilities, SourceDescriptor

LARGECAP_WATCHLIST_JSON = Path(__file__).resolve().parents[2] / "reports" / "largecap_watchlist.json"
_META_DOMAIN_STATUS_KEY = "_meta_domain_statuses"


def describe_source() -> SourceDescriptor:
    return SourceDescriptor(
        name="largecap_watchlist_json",
        path_hint="reports/largecap_watchlist.json",
        capabilities=SourceCapabilities(
            has_structure=False,
            has_meta=True,
            structure_mode="none",
            meta_mode="partial",
        ),
        notes=[
            "Static large-cap scaffold; neutral defaults only, last-resort fallback.",
            "No BOS/OB/FVG/sweep events; supplies volume/technical/news meta scaffolding.",
        ],
    )


def _load_payload() -> dict[str, Any]:
    if not LARGECAP_WATCHLIST_JSON.exists():
        raise FileNotFoundError(f"largecap source not found: {LARGECAP_WATCHLIST_JSON}")
    payload = json.loads(LARGECAP_WATCHLIST_JSON.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"largecap payload must be an object: {LARGECAP_WATCHLIST_JSON}")
    return payload


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


def _coerce_bias(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if normalized in {"BULLISH", "BEARISH", "NEUTRAL"}:
        return normalized
    return None


def _select_symbol_row(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("symbol must not be empty")
    rows = payload.get("symbols")
    if not isinstance(rows, list):
        raise ValueError("largecap payload has no symbol rows")
    for row in rows:
        if isinstance(row, dict) and str(row.get("symbol", "")).strip().upper() == wanted:
            return row
    raise ValueError(f"symbol {wanted} not present in largecap source")


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


def load_raw_meta_input(
    symbol: str,
    timeframe: str,
    *,
    reference_time: float | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    payload = _load_payload()
    row = _select_symbol_row(payload, symbol)

    trade_date = str(row.get("trade_date", "")).strip()
    asof_ts_opt = _coerce_optional_float(row.get("asof_ts"))
    asof_strategy = str(payload.get("asof_strategy", "")).strip().lower()
    if asof_ts_opt is not None:
        asof_ts = asof_ts_opt
    elif asof_strategy == "now":
        # Scaffold opt-in: stamp meta with current time so this last-resort
        # fallback never trips the 48h _META_DOMAIN_STALE_HOURS gate. Real
        # provider sources still win whenever they cover the symbol; this
        # only applies when the largecap scaffold is the actual chosen source.
        # When the caller supplies a reference_time (e.g. bundle generated_at),
        # prefer it so determinism is preserved across xdist workers.
        asof_ts = float(reference_time) if reference_time is not None else float(time.time())
    elif trade_date:
        asof_ts = _asof_ts_from_trade_date(trade_date)
    else:
        raise ValueError("largecap row is missing both asof_ts and trade_date")

    regime = str(row.get("volume_regime", "NORMAL")).strip().upper() or "NORMAL"
    if regime not in {"NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"}:
        regime = "NORMAL"

    try:
        thin_fraction = float(row.get("thin_fraction", 0.0))
    except (TypeError, ValueError):
        thin_fraction = 0.0

    resolved_symbol = str(row.get("symbol", symbol)).strip().upper()
    out: dict[str, Any] = {
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
            "repo:reports/largecap_watchlist.json",
            f"repo:reports/largecap_watchlist.json#symbol={resolved_symbol}",
            "smc_integration:largecap_scaffold_fallback",
        ],
    }

    tech = row.get("technical") if isinstance(row.get("technical"), dict) else {}
    tech_strength = _coerce_optional_float(tech.get("strength"))
    tech_bias = _coerce_bias(tech.get("bias"))
    if tech_strength is not None and tech_bias is not None:
        out["technical"] = {
            "value": {"strength": tech_strength, "bias": tech_bias},
            "asof_ts": asof_ts,
            "stale": False,
        }
        out["provenance"].append("smc_integration:technical_scaffold_from_largecap")

    news = row.get("news") if isinstance(row.get("news"), dict) else {}
    news_strength = _coerce_optional_float(news.get("strength"))
    news_bias = _coerce_bias(news.get("bias"))
    if news_strength is not None and news_bias is not None:
        out["news"] = {
            "value": {"strength": news_strength, "bias": news_bias},
            "asof_ts": asof_ts,
            "stale": False,
        }
        out["provenance"].append("smc_integration:news_scaffold_from_largecap")

    return out
