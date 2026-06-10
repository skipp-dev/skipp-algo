"""Databento market-data helpers for the Real-Time News Intelligence Dashboard.

Replaces FMP quote/pricing enrichment with Databento ``ohlcv-1d`` daily bars
and provides lightweight helpers used by ``streamlit_terminal.py`` and
``open_prep/streamlit_monitor.py``.

Requires ``DATABENTO_API_KEY`` in environment / ``.env``.
Uses the same caching infrastructure as ``databento_volatility_screener.py``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

import pandas as pd

from databento_client import _databento_get_range_with_retry
from databento_reference import maybe_refresh_symbol_reference_cache
from databento_utils import normalize_symbol_for_databento
from databento_volatility_screener import (
    PREFERRED_DATABENTO_DATASETS as _PREFERRED_DATASETS,
)
from databento_volatility_screener import (
    _clamp_request_end,
    _get_schema_available_end,
    _make_databento_client,
)

logger = logging.getLogger(__name__)

_ET = _ZoneInfo("America/New_York")

# ── Module-level cache for quote snapshots ──────────────────────
#
# Audit 2026-05-10 (PR-E): the quote cache is now scoped per-API-key
# fingerprint. Pre-PR-E ``_quote_cache`` was a single module-global
# ``dict[symbol, quote]`` and ``_quote_cache_ts`` a single timestamp,
# so quotes fetched under one Databento account were silently served
# to callers using a different API key (cross-account leakage when
# the process is shared between users / environments).
#
# The map is now ``dict[fingerprint, dict[symbol, quote]]`` and the
# timestamp ``dict[fingerprint, float]``; ``_client_fingerprint`` is
# the same SHA-256 helper used by ``_dataset_cache`` (PR-C).
_quote_cache: dict[str, dict[str, dict[str, Any]]] = {}
_quote_cache_ts: dict[str, float] = {}
_QUOTE_CACHE_TTL = 120.0  # 2 minutes
_cache_lock = threading.Lock()

# Per-request symbol cap. Databento accepts large symbol lists, but practical
# rate-limit and payload-size concerns favor chunking. Callers that pass more
# than this many symbols are split into back-to-back requests rather than
# silently truncated (the previous behavior).
_MAX_SYMBOLS_PER_REQUEST = 200

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
    return normalize_symbol_for_databento(symbol)


def _reverse_symbol(db_symbol: str) -> str:
    """Map Databento symbol back to standard dash-notation."""
    reverse = {v: k for k, v in _SYMBOL_ALIASES.items() if "-" in k}
    return reverse.get(db_symbol, db_symbol)


def is_available() -> bool:
    """Return True if DATABENTO_API_KEY is configured."""
    return bool(os.environ.get("DATABENTO_API_KEY", ""))


def _fetch_chunk(
    client: Any,
    *,
    dataset: str,
    symbols: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    """Fetch one chunk of OHLCV-1d bars. Lets exceptions bubble so the
    caller can isolate per-chunk failures instead of nuking the whole batch.
    """
    # F-V4-E1 (2026-05-01): route through the canonical retry helper in
    # databento_client so transient TLS / RemoteDisconnected / 5xx failures
    # don't poison a chunk that would have succeeded on a second attempt.
    store = _databento_get_range_with_retry(
        client,
        context=f"terminal_databento._fetch_chunk[{dataset}]",
        dataset=dataset,
        symbols=symbols,
        schema="ohlcv-1d",
        start=start,
        end=end,
    )
    return store.to_df()


def fetch_databento_daily_bars_with_status(
    symbols: list[str],
    *,
    lookback_days: int = 5,
    dataset: str | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Fetch daily bars and return ``(results, failed_symbols)``.

    Per-chunk exceptions are isolated: a failure on chunk N does not drop
    chunks 0..N-1 or N+1..end. Symbols belonging to a failed chunk are
    returned in ``failed_symbols`` (in their original, pre-normalized form)
    so callers can decide whether to retry or surface a partial-data
    warning.
    """
    api_key = _get_api_key()
    if not api_key or not symbols:
        return {}, []

    # Respect cache (fully-cached short-circuit). Audit 2026-05-10
    # (PR-E): cache lookups are scoped by API-key fingerprint so we
    # never serve a quote fetched under a different Databento account.
    fp = _client_fingerprint(api_key)
    with _cache_lock:
        now = time.time()
        ts = _quote_cache_ts.get(fp, 0.0)
        if now - ts < _QUOTE_CACHE_TTL:
            fp_quotes = _quote_cache.get(fp, {})
            cached = {
                s.upper(): fp_quotes[s.upper()]
                for s in symbols
                if s.upper() in fp_quotes
            }
            if len(cached) == len(symbols):
                return cached, []

    failed: list[str] = []
    try:
        client = _make_databento_client(api_key)
        ds = dataset or _pick_dataset(client, api_key)
        end_date = datetime.now(_ET).date()
        start_date = end_date - timedelta(days=lookback_days + 3)  # padding for weekends

        maybe_refresh_symbol_reference_cache(symbols)

        # Build (orig_symbol, normalized_symbol) pairs so we can report
        # *original* symbols back to the caller when a chunk fails. Symbols
        # that fail normalization are also reported back via ``failed`` so
        # every requested symbol is accounted for in either ``results`` or
        # ``failed``.
        pairs: list[tuple[str, str]] = []
        for s in symbols:
            normalized = _normalize_symbol(s)
            if normalized:
                pairs.append((s, normalized))
            else:
                failed.append(s)

        if len(pairs) > _MAX_SYMBOLS_PER_REQUEST:
            logger.info(
                "Databento daily-bars request: chunking %d symbols into batches of %d",
                len(pairs), _MAX_SYMBOLS_PER_REQUEST,
            )

        available_end_1d = _get_schema_available_end(client, ds, "ohlcv-1d")
        requested_end = pd.Timestamp(str(end_date + timedelta(days=1)), tz=UTC)
        clamped_end = _clamp_request_end(requested_end, available_end_1d)

        frames: list[pd.DataFrame] = []
        for batch_start in range(0, len(pairs), _MAX_SYMBOLS_PER_REQUEST):
            batch_pairs = pairs[batch_start:batch_start + _MAX_SYMBOLS_PER_REQUEST]
            batch_orig = [orig for orig, _ in batch_pairs]
            batch_norm = [norm for _, norm in batch_pairs]
            try:
                batch_df = _fetch_chunk(
                    client,
                    dataset=ds,
                    symbols=batch_norm,
                    start=start_date.isoformat(),
                    end=clamped_end.isoformat(),
                )
            except Exception as exc:  # isolate per-chunk failures
                logger.warning(
                    "Databento chunk %d-%d failed (%d symbols): %s",
                    batch_start, batch_start + len(batch_norm), len(batch_norm), exc,
                    exc_info=True,
                )
                failed.extend(batch_orig)
                continue
            if batch_df is not None and not batch_df.empty:
                frames.append(batch_df)

        if not frames:
            return {}, failed
        df = pd.concat(frames) if len(frames) > 1 else frames[0]

        if df.empty:
            return {}, failed

        # Ensure symbol column is string
        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].astype(str)
        else:
            return {}, failed

        required_ohlcv = {"open", "high", "low", "close", "volume"}
        if not required_ohlcv.issubset(df.columns):
            logger.warning("Databento frame missing OHLCV columns: %s", required_ohlcv - set(df.columns))
            return {}, failed

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

        # Update cache. Scoped per fingerprint per PR-E.
        with _cache_lock:
            fp_quotes = _quote_cache.setdefault(fp, {})
            fp_quotes.update(result)
            _quote_cache_ts[fp] = time.time()

        return result, failed

    except Exception as exc:
        logger.warning("Databento daily bars failed: %s", exc, exc_info=True)
        # Whole-pipeline failure: report all originally-requested symbols
        # as failed so the caller doesn't think the empty dict is a no-op.
        not_yet_failed = [s for s in symbols if s not in failed]
        failed.extend(not_yet_failed)
        return {}, failed


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

    Per-chunk failures are now logged as WARNINGs (with the failed symbol
    list) rather than silently dropping the entire batch. Use
    :func:`fetch_databento_daily_bars_with_status` directly for programmatic
    access to the failed-symbols list.
    """
    results, failed = fetch_databento_daily_bars_with_status(
        symbols, lookback_days=lookback_days, dataset=dataset,
    )
    if failed:
        total = len(failed) + len(results)
        logger.warning(
            "databento daily bars: %d/%d symbols failed: %s",
            len(failed), total, failed[:10],
        )
    return results


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


_dataset_cache: dict[str, str] = {}
_dataset_cache_lock = threading.Lock()


def _client_fingerprint(api_key: str) -> str:
    """Return a stable, non-reversible fingerprint for *api_key*.

    Used to scope :data:`_dataset_cache` per Databento account so a
    cached dataset for one API key is never returned for another. The
    full key is never logged or persisted -- only the first 16 hex
    characters of its SHA-256 digest end up in process memory.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _reset_dataset_cache() -> None:
    """Test-only helper: clear the per-client dataset cache."""
    with _dataset_cache_lock:
        _dataset_cache.clear()


def _pick_dataset(client: Any, api_key: str) -> str:
    """Choose the best available dataset for *client* (scoped by *api_key*).

    Audit 2026-05-10 (PR-C): the cache used to be a single module-global
    string, so the first client's dataset was returned for every
    subsequent call regardless of which API key (or which Databento
    account / entitlement set) was in use. The cache is now a dict keyed
    by an opaque per-key fingerprint.
    """
    fp = _client_fingerprint(api_key)
    cached = _dataset_cache.get(fp)
    if cached is not None:
        return cached
    with _dataset_cache_lock:
        cached = _dataset_cache.get(fp)
        if cached is not None:
            return cached
        try:
            available = client.metadata.list_datasets()
            available_set = {str(d) for d in available}
            for ds in _PREFERRED_DATASETS:
                if ds in available_set:
                    _dataset_cache[fp] = ds
                    logger.info("Databento dataset selected: %s", ds)
                    return ds
            # Fallback
            picked = str(available[0]) if available else "DBEQ.BASIC"
            _dataset_cache[fp] = picked
            return picked
        except Exception:
            _dataset_cache[fp] = "DBEQ.BASIC"
            return "DBEQ.BASIC"


def get_dataset_info(api_key: str | None = None) -> dict[str, Any]:
    """Return metadata about the selected Databento dataset.

    Useful for diagnostics / sidebar display.
    """
    key = api_key or _get_api_key()
    if not key:
        return {"error": "No API key"}
    try:
        client = _make_databento_client(key)
        ds = _pick_dataset(client, key)
        ds_range = client.metadata.get_dataset_range(dataset=ds)
        return {
            "dataset": ds,
            "start": str(ds_range.get("start", "")),
            "end": str(ds_range.get("end", "")),
            "schemas": list(ds_range.get("schema", {}).keys()) if isinstance(ds_range.get("schema"), dict) else [],
        }
    except Exception as exc:
        logger.warning("Databento dataset info lookup failed: %s", exc, exc_info=True)
        return {"error": "dataset_lookup_failed"}
