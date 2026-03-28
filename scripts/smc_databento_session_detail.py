"""Databento full-universe session-minute-detail collection.

Extracted from ``smc_microstructure_base_runtime`` to reduce scope creep.
All public symbols are re-exported from the runtime module for backward
compatibility.

Owns the session-time constants (``PREMARKET_START_ET``, etc.) and the
coverage / fingerprint helpers that were previously private to the
runtime module.
"""
from __future__ import annotations

import hashlib
import json
import logging
import warnings
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from databento_provider import DabentoProvider, MarketDataProvider
from databento_utils import (
    US_EASTERN_TZ,
    build_cache_path,
    clamp_request_end,
    extract_unresolved_symbols_from_warning_messages,
    iter_symbol_batches,
    read_cached_frame,
    resolve_display_timezone,
    store_to_frame,
    trade_day_cache_max_age_seconds,
    validate_frame_columns,
    warn_with_redacted_exception,
    write_cached_frame,
)

logger = logging.getLogger(__name__)


# ── Session-time constants (ET) ─────────────────────────────────────

PREMARKET_START_ET = time(4, 0)
REGULAR_OPEN_ET = time(9, 30)
OPEN_30M_END_ET = time(10, 0)
MIDDAY_START_ET = time(11, 0)
MIDDAY_END_ET = time(14, 0)
LATE_START_ET = time(14, 30)
CLOSE_60M_START_ET = time(15, 0)
REGULAR_CLOSE_ET = time(16, 0)
AFTERHOURS_END_ET = time(20, 0)

PREMARKET_MINUTES = 330
REGULAR_MINUTES = 390
MIDDAY_MINUTES = 180
AFTERHOURS_MINUTES = 240


# ── Coverage / fingerprint helpers ──────────────────────────────────


def _universe_fingerprint(symbols: set[str]) -> str:
    normalized = ",".join(sorted(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _coverage_stats(frame: pd.DataFrame, expected_symbols: set[str]) -> dict[str, Any]:
    normalized_expected = {str(symbol).strip().upper() for symbol in expected_symbols if str(symbol).strip()}
    if frame.empty or "symbol" not in frame.columns:
        actual_symbols: set[str] = set()
    else:
        actual_symbols = set(frame["symbol"].dropna().astype(str).str.upper())
    missing_symbols = sorted(normalized_expected - actual_symbols)
    coverage_ratio = 1.0 if not normalized_expected else float(len(actual_symbols & normalized_expected) / len(normalized_expected))
    return {
        "expected_count": len(normalized_expected),
        "actual_count": len(actual_symbols & normalized_expected),
        "coverage_ratio": coverage_ratio,
        "missing_symbols": missing_symbols,
    }


def _assert_complete_symbol_coverage(frame: pd.DataFrame, expected_symbols: set[str], *, context: str) -> None:
    coverage = _coverage_stats(frame, expected_symbols)
    if coverage["missing_symbols"]:
        sample = ", ".join(coverage["missing_symbols"][:10])
        raise RuntimeError(
            f"{context}: incomplete symbol coverage ({coverage['actual_count']}/{coverage['expected_count']}). "
            f"Missing symbols include: {sample}"
        )


# ── Thin wrappers for testability (monkeypatch targets) ─────────────


def _make_databento_client(api_key: str) -> MarketDataProvider:
    return DabentoProvider(api_key)


def _get_schema_available_end(client: MarketDataProvider, dataset: str, schema: str) -> pd.Timestamp:
    return client.get_schema_available_end(dataset, schema)


def _databento_get_range_with_retry(provider: MarketDataProvider, **kwargs: Any) -> Any:
    return provider.get_range(**kwargs)


def _store_to_frame(store: Any, count: int, context: str) -> pd.DataFrame:
    return store_to_frame(store, count=count, context=context)


def _read_cached_frame(path: Path, max_age_seconds: float) -> pd.DataFrame | None:
    return read_cached_frame(path, max_age_seconds=max_age_seconds)


def _write_cached_frame(path: Path, frame: pd.DataFrame) -> None:
    write_cached_frame(path, frame)


# ── Main collection function ───────────────────────────────────────


def collect_full_universe_session_minute_detail(
    databento_api_key: str,
    *,
    provider: MarketDataProvider | None = None,
    dataset: str,
    trading_days: list[date],
    universe_symbols: set[str],
    expected_symbols_by_trade_day: dict[date, set[str]] | None = None,
    display_timezone: str,
    cache_dir: str | Path | None = None,
    use_file_cache: bool = True,
    force_refresh: bool = False,
) -> pd.DataFrame:
    output_columns = [
        "trade_date",
        "symbol",
        "timestamp",
        "session",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
    ]
    if not trading_days or not universe_symbols:
        return pd.DataFrame(columns=output_columns)

    if provider is None:
        provider = _make_databento_client(databento_api_key)
    available_end = _get_schema_available_end(provider, dataset, "ohlcv-1m")
    display_tz = resolve_display_timezone(display_timezone)
    all_rows: list[pd.DataFrame] = []
    runtime_unsupported_symbols_seen_global: set[str] = set()
    latest_trade_day = max(trading_days)

    for trade_day in trading_days:
        day_runtime_unsupported_symbols: set[str] = set()
        day_expected_symbols = {
            str(symbol).strip().upper()
            for symbol in (expected_symbols_by_trade_day or {}).get(trade_day, universe_symbols)
            if str(symbol).strip()
        }
        day_expected_symbols &= {str(symbol).strip().upper() for symbol in universe_symbols if str(symbol).strip()}
        if not day_expected_symbols:
            continue

        local_start = datetime.combine(trade_day, PREMARKET_START_ET, tzinfo=US_EASTERN_TZ).astimezone(display_tz)
        local_end = datetime.combine(trade_day, AFTERHOURS_END_ET, tzinfo=US_EASTERN_TZ).astimezone(display_tz)
        fetch_start_utc = pd.Timestamp(local_start.astimezone(UTC))
        fetch_end_utc = clamp_request_end(pd.Timestamp(local_end.astimezone(UTC)), available_end)
        if fetch_end_utc <= fetch_start_utc:
            continue

        cache_path = build_cache_path(
            cache_dir,
            "full_universe_session_minute_detail",
            dataset=dataset,
            parts=[
                trade_day.isoformat(),
                display_timezone,
                PREMARKET_START_ET.strftime("%H%M%S"),
                AFTERHOURS_END_ET.strftime("%H%M%S"),
                _universe_fingerprint(day_expected_symbols),
            ],
        )
        cache_meta_path = cache_path.with_suffix(f"{cache_path.suffix}.meta.json")
        day_frame: pd.DataFrame | None = None
        if use_file_cache and not force_refresh:
            day_frame = _read_cached_frame(
                cache_path,
                max_age_seconds=trade_day_cache_max_age_seconds(trade_day, latest_trade_day),
            )
            if day_frame is not None:
                try:
                    expected_symbols_for_cache = set(day_expected_symbols)
                    if cache_meta_path.exists():
                        try:
                            cache_meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
                            cached_unresolved = {
                                str(symbol).strip().upper()
                                for symbol in cache_meta.get("runtime_unsupported_symbols", [])
                                if str(symbol).strip()
                            }
                            expected_symbols_for_cache -= cached_unresolved
                        except Exception as exc:
                            logger.warning(
                                "Ignoring unreadable session-minute cache metadata for %s: %s",
                                trade_day,
                                exc,
                            )
                    _assert_complete_symbol_coverage(
                        day_frame,
                        expected_symbols_for_cache,
                        context=f"Cached session minute detail for {trade_day}",
                    )
                except RuntimeError as exc:
                    logger.warning("Ignoring incomplete session-minute cache for %s: %s", trade_day, exc)
                    day_frame = None

        if day_frame is None:
            day_parts: list[pd.DataFrame] = []
            active_symbols = set(day_expected_symbols)
            for symbols_batch in iter_symbol_batches(active_symbols):
                unresolved_symbols: set[str] = set()
                try:
                    with warnings.catch_warnings(record=True) as caught_warnings:
                        warnings.simplefilter("always")
                        store = _databento_get_range_with_retry(
                            provider,
                            context="collect_full_universe_session_minute_detail",
                            dataset=dataset,
                            symbols=symbols_batch,
                            schema="ohlcv-1m",
                            start=fetch_start_utc.isoformat(),
                            end=fetch_end_utc.isoformat(),
                        )
                    frame = _store_to_frame(store, count=250_000, context="collect_full_universe_session_minute_detail")
                    unresolved_symbols.update(extract_unresolved_symbols_from_warning_messages(
                        [str(item.message) for item in caught_warnings]
                    ))
                except Exception as exc:
                    unresolved_from_exception = extract_unresolved_symbols_from_warning_messages([str(exc)])
                    unresolved_in_batch = {
                        symbol for symbol in unresolved_from_exception if symbol in set(symbols_batch)
                    }
                    if not unresolved_in_batch:
                        warn_with_redacted_exception(
                            f"Session minute detail fetch failed for batch on {trade_day}, skipping",
                            exc,
                            include_traceback=True,
                        )
                        continue

                    unresolved_symbols.update(unresolved_in_batch)
                    retry_symbols = [symbol for symbol in symbols_batch if symbol not in unresolved_in_batch]
                    logger.warning(
                        "Session minute detail fetch for %s excluded %d runtime-unresolved symbols from a failing batch and retried the remaining %d symbols.",
                        trade_day,
                        len(unresolved_in_batch),
                        len(retry_symbols),
                    )
                    if not retry_symbols:
                        frame = pd.DataFrame(columns=output_columns)
                    else:
                        try:
                            with warnings.catch_warnings(record=True) as retry_caught_warnings:
                                warnings.simplefilter("always")
                                retry_store = _databento_get_range_with_retry(
                                    provider,
                                    context="collect_full_universe_session_minute_detail",
                                    dataset=dataset,
                                    symbols=retry_symbols,
                                    schema="ohlcv-1m",
                                    start=fetch_start_utc.isoformat(),
                                    end=fetch_end_utc.isoformat(),
                                )
                            frame = _store_to_frame(
                                retry_store,
                                count=250_000,
                                context="collect_full_universe_session_minute_detail",
                            )
                            unresolved_symbols.update(
                                extract_unresolved_symbols_from_warning_messages(
                                    [str(item.message) for item in retry_caught_warnings]
                                )
                            )
                        except Exception as retry_exc:
                            warn_with_redacted_exception(
                                f"Session minute detail retry failed for filtered batch on {trade_day}, skipping",
                                retry_exc,
                                include_traceback=True,
                            )
                            continue

                day_runtime_unsupported_symbols.update(unresolved_symbols)
                runtime_unsupported_symbols_seen_global.update(unresolved_symbols)
                if not frame.empty:
                    validate_frame_columns(
                        frame,
                        required={"symbol", "open", "high", "low", "close", "volume"},
                        context="collect_full_universe_session_minute_detail",
                    )
                if frame.empty or "symbol" not in frame.columns:
                    continue

                frame = frame.copy()
                frame["symbol"] = frame["symbol"].astype(str).str.upper()
                frame = frame[frame["symbol"].isin(day_expected_symbols)].copy()
                if frame.empty:
                    continue

                frame["timestamp"] = pd.to_datetime(frame["ts"], errors="coerce", utc=True).dt.tz_convert(display_tz)
                et_time = frame["timestamp"].dt.tz_convert(US_EASTERN_TZ).dt.time
                frame["session"] = np.select(
                    [
                        et_time < REGULAR_OPEN_ET,
                        et_time < REGULAR_CLOSE_ET,
                        et_time <= AFTERHOURS_END_ET,
                    ],
                    ["premarket", "regular", "afterhours"],
                    default="overnight",
                )
                trade_count_column = next(
                    (candidate for candidate in ("trade_count", "count", "n_trades", "num_trades") if candidate in frame.columns),
                    None,
                )
                if trade_count_column is not None:
                    frame["trade_count"] = pd.to_numeric(frame[trade_count_column], errors="coerce")
                else:
                    frame["trade_count"] = np.nan
                frame.insert(0, "trade_date", trade_day)
                day_parts.append(frame[output_columns].reset_index(drop=True))

            day_frame = pd.concat(day_parts, ignore_index=True) if day_parts else pd.DataFrame(columns=output_columns)
            expected_symbols = set(day_expected_symbols) - day_runtime_unsupported_symbols
            if day_runtime_unsupported_symbols:
                logger.warning(
                    "Session minute detail for %s excluded %d runtime-unsupported symbols from completeness checks for this trade day.",
                    trade_day,
                    len(day_runtime_unsupported_symbols),
                )
            if runtime_unsupported_symbols_seen_global:
                logger.info(
                    "Cumulative runtime-unsupported symbols observed across processed trade days: %d",
                    len(runtime_unsupported_symbols_seen_global),
                )
            _assert_complete_symbol_coverage(
                day_frame,
                expected_symbols,
                context=f"Session minute detail for {trade_day}",
            )
            if use_file_cache:
                if not day_frame.empty:
                    _write_cached_frame(cache_path, day_frame)
                cache_meta_payload = {
                    "trade_day": trade_day.isoformat(),
                    "runtime_unsupported_symbols": sorted(day_runtime_unsupported_symbols),
                }
                cache_meta_path.write_text(json.dumps(cache_meta_payload, indent=2), encoding="utf-8")

        if day_frame is not None and not day_frame.empty:
            all_rows.append(day_frame)

    return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(columns=output_columns)
