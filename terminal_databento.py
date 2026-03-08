"""Databento market-data helpers for the Real-Time News Intelligence Dashboard.

Replaces FMP quote/pricing enrichment with Databento ``ohlcv-1d`` daily bars
and provides lightweight helpers used by ``streamlit_terminal.py`` and
``open_prep/streamlit_monitor.py``.

Requires ``DATABENTO_API_KEY`` in environment / ``.env``.
Uses the same caching infrastructure as ``databento_volatility_screener.py``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

_ET = _ZoneInfo("America/New_York")

import pandas as pd

logger = logging.getLogger(__name__)

# ── Module-level cache for quote snapshots ──────────────────────
_quote_cache: dict[str, dict[str, Any]] = {}
_quote_cache_ts: float = 0.0
_QUOTE_CACHE_TTL = 120.0  # 2 minutes
_cache_lock = threading.Lock()

# ── Dataset preference (same as databento_volatility_screener) ──
_PREFERRED_DATASETS = (
    "XNAS.ITCH",
    "XNYS.PILLAR",
    "DBEQ.BASIC",
    "XNAS.BASIC",
)

_SYMBOL_ALIASES = {
    "BRK-A": "BRK.A",
    "BRK-B": "BRK.B",
    "BRK/A": "BRK.A",
    "BRK/B": "BRK.B",
    "BF-B": "BF.B",
    "MKC-V": "MKC.V",
    "MOG-A": "MOG.A",
}


def _get_api_key() -> str:
    key = os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        logger.warning("DATABENTO_API_KEY not set")
    return key


def _normalize_symbol(symbol: str) -> str:
    """Map dash/slash ticker variants to Databento dot-notation."""
    s = symbol.upper().strip()
    return _SYMBOL_ALIASES.get(s, s)


def _reverse_symbol(db_symbol: str) -> str:
    """Map Databento symbol back to standard dash-notation."""
    reverse = {v: k for k, v in _SYMBOL_ALIASES.items() if "-" in k}
    return reverse.get(db_symbol, db_symbol)


def is_available() -> bool:
    """Return True if DATABENTO_API_KEY is configured."""
    return bool(os.environ.get("DATABENTO_API_KEY", ""))


def fetch_databento_daily_bars(
    symbols: list[str],
    *,
    lookback_days: int = 5,
    dataset: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch recent daily OHLCV bars for *symbols* via Databento.

    Returns a dict mapping uppercase ticker → quote dict with keys:
    symbol, price (last close), open, high, low, close, volume,
    change, changesPercentage.
    """
    api_key = _get_api_key()
    if not api_key or not symbols:
        return {}

    # Respect cache
    global _quote_cache, _quote_cache_ts
    with _cache_lock:
        now = time.time()
        if now - _quote_cache_ts < _QUOTE_CACHE_TTL:
            cached = {s.upper(): _quote_cache[s.upper()] for s in symbols if s.upper() in _quote_cache}
            if len(cached) == len(symbols):
                return cached

    try:
        import databento as db

        client = db.Historical(api_key)
        ds = dataset or _pick_dataset(client)
        end_date = datetime.now(_ET).date()
        start_date = end_date - timedelta(days=lookback_days + 3)  # padding for weekends

        db_symbols = [_normalize_symbol(s) for s in symbols]
        # Limit batch size to avoid API limits
        db_symbols = db_symbols[:200]

        store = client.timeseries.get_range(
            dataset=ds,
            symbols=db_symbols,
            schema="ohlcv-1d",
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
        )
        df = store.to_df()

        if df.empty:
            return {}

        # Ensure symbol column is string
        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].astype(str)
        else:
            return {}

        required_ohlcv = {"open", "high", "low", "close", "volume"}
        if not required_ohlcv.issubset(df.columns):
            logger.warning("Databento frame missing OHLCV columns: %s", required_ohlcv - set(df.columns))
            return {}

        result: dict[str, dict[str, Any]] = {}
        for sym in df["symbol"].unique():
            sym_df = df[df["symbol"] == sym].sort_index()
            if sym_df.empty:
                continue

            latest = sym_df.iloc[-1]
            prev_close = sym_df.iloc[-2]["close"] if len(sym_df) >= 2 else latest["open"]

            close_val = float(latest["close"])
            change = close_val - float(prev_close) if prev_close else 0.0
            change_pct = (change / float(prev_close) * 100) if prev_close and prev_close != 0 else 0.0

            # Scale Databento fixed-point prices (they are in 1e-9 USD)
            # Actually databento ohlcv-1d returns prices as floats in USD
            orig_sym = _reverse_symbol(str(sym))

            result[orig_sym.upper()] = {
                "symbol": orig_sym.upper(),
                "price": close_val,
                "open": float(latest["open"]),
                "high": float(latest["high"]),
                "low": float(latest["low"]),
                "close": close_val,
                "volume": int(latest["volume"]),
                "change": round(change, 4),
                "changesPercentage": round(change_pct, 4),
                "changePercentage": round(change_pct, 4),
            }

        # Update cache
        with _cache_lock:
            _quote_cache.update(result)
            _quote_cache_ts = time.time()

        return result

    except Exception as exc:
        logger.warning("Databento daily bars failed: %s", exc, exc_info=True)
        return {}


def fetch_databento_quotes(
    symbols: list[str],
    *,
    dataset: str | None = None,
) -> list[dict[str, Any]]:
    """Drop-in replacement for ``fetch_fmp_quotes``.

    Returns a list of quote dicts (same shape as the old FMP response)
    so callers don't need structural changes.
    """
    bar_map = fetch_databento_daily_bars(symbols, dataset=dataset)
    return list(bar_map.values())


def fetch_databento_quote_map(
    symbols: list[str],
    *,
    dataset: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Convenience: returns {SYMBOL: quote_dict} for batch enrichment."""
    return fetch_databento_daily_bars(symbols, dataset=dataset)


_dataset_cache: str | None = None
_dataset_cache_lock = threading.Lock()


def _pick_dataset(client: Any) -> str:
    """Choose the best available dataset for the account."""
    global _dataset_cache
    if _dataset_cache is not None:
        return _dataset_cache
    with _dataset_cache_lock:
        if _dataset_cache is not None:
            return _dataset_cache
        try:
            available = client.metadata.list_datasets()
            available_set = {str(d) for d in available}
            for ds in _PREFERRED_DATASETS:
                if ds in available_set:
                    _dataset_cache = ds
                    logger.info("Databento dataset selected: %s", ds)
                    return ds
            # Fallback
            _dataset_cache = str(available[0]) if available else "DBEQ.BASIC"
            return _dataset_cache
        except Exception:
            _dataset_cache = "DBEQ.BASIC"
            return _dataset_cache


def get_dataset_info(api_key: str | None = None) -> dict[str, Any]:
    """Return metadata about the selected Databento dataset.

    Useful for diagnostics / sidebar display.
    """
    key = api_key or _get_api_key()
    if not key:
        return {"error": "No API key"}
    try:
        import databento as db
        client = db.Historical(key)
        ds = _pick_dataset(client)
        ds_range = client.metadata.get_dataset_range(dataset=ds)
        return {
            "dataset": ds,
            "start": str(ds_range.get("start", "")),
            "end": str(ds_range.get("end", "")),
            "schemas": list(ds_range.get("schema", {}).keys()) if isinstance(ds_range.get("schema"), dict) else [],
        }
    except Exception as exc:
        return {"error": str(exc)}
