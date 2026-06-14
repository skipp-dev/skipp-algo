"""US equity universe resolution for the Databento pipeline.

Provides two universe sources:

* **Nasdaq Trader** symbol directory — official listed securities, no API key
  required.
* **FMP company screener** — richer metadata (market cap, sector, industry),
  requires an FMP API key.

Also includes the **Databento symbol-support probe** which checks whether
each symbol actually resolves in a given Databento dataset, and caches the
results to avoid repeated API calls.

Backward compatibility:  all names exported from this module are still
importable from ``databento_volatility_screener`` via re-export shims.
"""

from __future__ import annotations

import json
import logging
import time as time_module
import warnings
from datetime import UTC, date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from databento_client import (
    _databento_get_range_with_retry,
    _exclusive_ohlcv_1s_end,
    _make_databento_client,
    _normalize_tls_certificate_env,
)
from databento_utils import (
    US_EASTERN_TZ,
    _coerce_timestamp_frame,
    _extract_unresolved_symbols_from_warning_messages,
    _iter_symbol_batches,
    _normalize_symbols,
    normalize_symbol_for_databento,
)
from open_prep_boundary import make_fmp_client

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

SYMBOL_SUPPORT_CHECK_BATCH_SIZE = 250
SYMBOL_SUPPORT_LOOKBACK_DAYS = 14
SYMBOL_SUPPORT_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

UNIVERSE_COLUMNS = ["symbol", "company_name", "exchange", "sector", "industry", "market_cap"]

NASDAQ_TRADER_DIRECTORY_SPECS = (
    (
        "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt",
        "Symbol",
        "Security Name",
        "Listing Exchange",
    ),
    (
        "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
        "ACT Symbol",
        "Security Name",
        "Exchange",
    ),
)
NASDAQ_TRADER_EXCHANGE_CODE_MAP = {
    "NASDAQ": "Q",
    "NYSE": "N",
    "AMEX": "A",
    "NYSEARCA": "P",
    "NYSE ARCA": "P",
    "BATS": "Z",
    "CBOE": "Z",
}
NASDAQ_TRADER_EXCHANGE_NAME_MAP = {
    "Q": "NASDAQ",
    "N": "NYSE",
    "A": "AMEX",
    "P": "NYSE ARCA",
    "Z": "BATS",
}


# ── Symbol-support cache ───────────────────────────────────────────────────

def _symbol_support_cache_path(cache_dir: str | Path | None, dataset: str) -> Path:
    from databento_utils import build_cache_path
    return build_cache_path(cache_dir, "symbol_support", dataset=dataset, parts=["support_map"], suffix=".json")


def _read_symbol_support_cache(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            return {}
        age = (datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)).total_seconds()
        if age > SYMBOL_SUPPORT_CACHE_TTL_SECONDS:
            logger.info("Symbol support cache expired (%.1f h old, TTL %.1f h): %s", age / 3600, SYMBOL_SUPPORT_CACHE_TTL_SECONDS / 3600, path.name)
            return {}
        return {str(key): bool(value) for key, value in loaded.items()}
    except Exception:
        logger.warning("Failed to read symbol support cache %s", path, exc_info=True)
        return {}


def _write_symbol_support_cache(path: Path, support_map: dict[str, bool]) -> None:
    from databento_utils import _replace_atomic
    def _write_temp(temp_path: Path) -> None:
        temp_path.write_text(json.dumps(support_map, indent=2), encoding="utf-8")
    _replace_atomic(path, _write_temp)


def _symbols_requiring_support_check(symbols: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    return _normalize_symbols(symbols)


# ── Symbol-support probe ───────────────────────────────────────────────────

def _probe_symbol_support(
    databento_api_key: str,
    *,
    dataset: str,
    symbols: list[str],
) -> dict[str, bool]:
    if not symbols:
        return {}
    client = _make_databento_client(databento_api_key)
    current_utc_day = datetime.now(UTC).date()
    conditions = client.metadata.get_dataset_condition(
        dataset=dataset,
        start_date=(current_utc_day - timedelta(days=SYMBOL_SUPPORT_LOOKBACK_DAYS)).isoformat(),
        end_date=current_utc_day.isoformat(),
    )
    available_days = [
        date.fromisoformat(str(item.get("date")))
        for item in conditions
        if isinstance(item, dict) and item.get("condition") == "available" and item.get("date")
    ]
    available_days = [day for day in available_days if day < current_utc_day]
    if not available_days:
        return {symbol: True for symbol in symbols}
    probe_day = available_days[-1]
    probe_start = datetime.combine(probe_day, time(9, 30), tzinfo=US_EASTERN_TZ).astimezone(UTC).isoformat()
    probe_end = _exclusive_ohlcv_1s_end(
        datetime.combine(probe_day, time(9, 31), tzinfo=US_EASTERN_TZ).astimezone(UTC)
    ).isoformat()
    support_map: dict[str, bool] = {}

    for batch in _iter_symbol_batches(symbols, batch_size=SYMBOL_SUPPORT_CHECK_BATCH_SIZE):
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                store = _databento_get_range_with_retry(
                    client,
                    context="_probe_symbol_support",
                    dataset=dataset,
                    symbols=batch,
                    schema="ohlcv-1s",
                    start=probe_start,
                    end=probe_end,
                )
                batch_df = store.to_df(count=100_000)
                if isinstance(batch_df, pd.DataFrame):
                    batch_frame = _coerce_timestamp_frame(batch_df)
                else:
                    chunks = list(batch_df)
                    batch_frame = _coerce_timestamp_frame(pd.concat(chunks, ignore_index=False)) if chunks else pd.DataFrame()
        except Exception:
            logger.warning("Symbol support probe failed for batch of %d symbols, assuming supported.", len(batch), exc_info=True)
            for symbol in batch:
                support_map.setdefault(symbol, True)
            continue
        resolved = set()
        if not batch_frame.empty and "symbol" in batch_frame.columns:
            resolved = {
                normalize_symbol_for_databento(symbol)
                for symbol in batch_frame["symbol"].astype(str).tolist()
                if normalize_symbol_for_databento(symbol)
            }
        unresolved = _extract_unresolved_symbols_from_warning_messages([str(item.message) for item in caught_warnings])
        for symbol in batch:
            if symbol in resolved:
                support_map[symbol] = True
            elif symbol in unresolved:
                support_map[symbol] = False
    return support_map


# ── Universe filtering ──────────────────────────────────────────────────────

def filter_supported_universe_for_databento(
    databento_api_key: str,
    *,
    dataset: str,
    universe: pd.DataFrame,
    cache_dir: str | Path | None = None,
    use_file_cache: bool = False,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    if universe.empty or "symbol" not in universe.columns:
        return universe.copy(), []
    candidate_symbols = _symbols_requiring_support_check(universe["symbol"].dropna().astype(str).tolist())
    if not candidate_symbols:
        return universe.copy(), []

    cache_path = _symbol_support_cache_path(cache_dir, dataset)
    support_map = _read_symbol_support_cache(cache_path) if use_file_cache and not force_refresh else {}
    missing = [symbol for symbol in candidate_symbols if symbol not in support_map]
    if missing:
        support_map.update(_probe_symbol_support(databento_api_key, dataset=dataset, symbols=missing))
        if use_file_cache:
            _write_symbol_support_cache(cache_path, support_map)

    unsupported = sorted(symbol for symbol in candidate_symbols if support_map.get(symbol) is False)
    if not unsupported:
        return universe.copy(), []
    filtered = universe[~universe["symbol"].astype(str).str.upper().isin(unsupported)].copy().reset_index(drop=True)
    return filtered, unsupported


# ── Universe data sources ──────────────────────────────────────────────────

def _empty_universe_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=UNIVERSE_COLUMNS)


def _fetch_us_equity_universe_via_screener(
    client: Any,
    *,
    min_market_cap: float | None = None,
    exchanges: str = "NASDAQ,NYSE,AMEX",
) -> pd.DataFrame:
    """Fetch universe via FMP company screener."""
    rows: list[dict[str, Any]] = []
    page = 0
    page_size = 1000
    while True:
        try:
            batch = client.get_company_screener(
                country="US",
                market_cap_more_than=min_market_cap,
                exchange=exchanges,
                is_etf=False,
                is_fund=False,
                limit=page_size,
                page=page,
            )
        except Exception:
            logger.warning("FMP company screener request failed on page %d.", page, exc_info=True)
            break
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
        if page > 50:
            break
    if not rows:
        return _empty_universe_frame()
    frame = pd.DataFrame(rows)
    if frame.empty:
        return _empty_universe_frame()
    out = pd.DataFrame(
        {
            "symbol": frame.get("symbol", "").astype(str).map(normalize_symbol_for_databento),
            "company_name": frame.get("companyName", frame.get("name", "")),
            "exchange": frame.get("exchangeShortName", frame.get("exchange", "")),
            "sector": frame.get("sector", ""),
            "industry": frame.get("industry", ""),
            "market_cap": pd.to_numeric(frame.get("marketCap"), errors="coerce"),
        }
    )
    out = out[out["symbol"].astype(str).str.len() > 0].copy()
    out = out[out["symbol"].ne("")].drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    return out


def _normalize_requested_exchange_codes(exchanges: str) -> set[str]:
    requested: set[str] = set()
    for item in str(exchanges or "").split(","):
        token = item.strip().upper()
        if not token:
            continue
        requested.add(NASDAQ_TRADER_EXCHANGE_CODE_MAP.get(token, token))
    return requested or {"Q", "N", "A"}


def _download_nasdaq_trader_text(url: str) -> str:
    import ssl
    _ssl_ctx = ssl.create_default_context(cafile=_normalize_tls_certificate_env())
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30, context=_ssl_ctx) as response:
                payload = response.read()
            return bytes(payload).decode("utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover - deterministic in tests via monkeypatch
            last_error = exc
            if attempt < 2:
                time_module.sleep(0.5 * (2 ** attempt))
    if last_error is None:
        raise RuntimeError("retry loop exited without success or recorded error")
    raise last_error


def _parse_nasdaq_trader_directory(
    text: str,
    *,
    symbol_column: str,
    security_name_column: str,
    exchange_column: str,
    allowed_exchange_codes: set[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in pd.read_csv(BytesIO(text.encode("utf-8")), sep="|", dtype=str).fillna("").to_dict(orient="records"):
        first_value = next(iter(row.values()), "")
        if isinstance(first_value, str) and first_value.startswith("File Creation Time:"):
            continue
        symbol = normalize_symbol_for_databento(str(row.get(symbol_column, "")).strip())
        exchange_code = str(row.get(exchange_column, "")).strip().upper()
        if not symbol or exchange_code not in allowed_exchange_codes:
            continue
        if str(row.get("ETF", "")).strip().upper() == "Y":
            continue
        if str(row.get("Test Issue", "")).strip().upper() == "Y":
            continue
        rows.append(
            {
                "symbol": symbol,
                "company_name": str(row.get(security_name_column, "")).strip(),
                "exchange": NASDAQ_TRADER_EXCHANGE_NAME_MAP.get(exchange_code, exchange_code),
                "sector": "",
                "industry": "",
                "market_cap": np.nan,
            }
        )
    if not rows:
        return _empty_universe_frame()
    return pd.DataFrame(rows, columns=UNIVERSE_COLUMNS)


def _fetch_us_equity_universe_via_nasdaq_trader(*, exchanges: str = "NASDAQ,NYSE,AMEX") -> pd.DataFrame:
    allowed_exchange_codes = _normalize_requested_exchange_codes(exchanges)
    frames: list[pd.DataFrame] = []
    for url, symbol_column, security_name_column, exchange_column in NASDAQ_TRADER_DIRECTORY_SPECS:
        try:
            text = _download_nasdaq_trader_text(url)
        except Exception:
            logger.warning("Failed to download Nasdaq Trader directory from %s", url, exc_info=True)
            continue
        frame = _parse_nasdaq_trader_directory(
            text,
            symbol_column=symbol_column,
            security_name_column=security_name_column,
            exchange_column=exchange_column,
            allowed_exchange_codes=allowed_exchange_codes,
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return _empty_universe_frame()
    universe = pd.concat(frames, ignore_index=True)
    universe = universe.drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    return universe


# ── Public universe API ────────────────────────────────────────────────────

def fetch_us_equity_universe(
    fmp_api_key: str = "",
    *,
    min_market_cap: float | None = None,
    exchanges: str = "NASDAQ,NYSE,AMEX",
    active_only: bool = True,
    trade_date: date | None = None,
    snapshot_root: str | Path | None = None,
) -> pd.DataFrame:
    frame, _metadata = fetch_us_equity_universe_with_metadata(
        fmp_api_key,
        min_market_cap=min_market_cap,
        exchanges=exchanges,
        active_only=active_only,
        trade_date=trade_date,
        snapshot_root=snapshot_root,
    )
    return frame


def fetch_us_equity_universe_with_metadata(
    fmp_api_key: str = "",
    *,
    min_market_cap: float | None = None,
    exchanges: str = "NASDAQ,NYSE,AMEX",
    active_only: bool = True,
    trade_date: date | None = None,
    snapshot_root: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    # Backtest replay path: when caller opts out of active-only and provides a
    # trade_date, prefer a previously persisted per-day universe snapshot to
    # avoid survivorship bias (#2351 / re-audit F2).
    if not active_only and trade_date is not None:
        snapshot = load_universe_snapshot(trade_date, root=snapshot_root)
        if snapshot is not None:
            symbols = [str(s) for s in snapshot.get("symbols", [])]
            frame = pd.DataFrame({col: ["" if col != "market_cap" else np.nan] * len(symbols) for col in UNIVERSE_COLUMNS})
            frame["symbol"] = symbols
            return (
                frame.reset_index(drop=True),
                {
                    "source": "universe_snapshot",
                    "fallback_source": None,
                    "scope_definition": (
                        f"Persisted universe snapshot for trade_date={trade_date.isoformat()} "
                        f"loaded from {snapshot.get('source_schema', 'unknown')} captured at "
                        f"{snapshot.get('captured_at', 'unknown')}."
                    ),
                    "min_market_cap_requested": float(min_market_cap) if min_market_cap is not None else None,
                    "min_market_cap_effective": None,
                    "min_market_cap_applied": False,
                    "selection_reason": "historical_snapshot",
                    "active_only": False,
                    "trade_date": trade_date.isoformat(),
                    "survivorship_bias_risk": False,
                    "snapshot_captured_at": snapshot.get("captured_at"),
                    "snapshot_source_schema": snapshot.get("source_schema"),
                },
            )
        logger.warning(
            "No persisted universe snapshot for trade_date=%s; falling back to current vendor data. "
            "Backtest results will carry survivorship-bias risk (#2351).",
            trade_date.isoformat(),
        )

    survivorship_bias_risk = (not active_only) and trade_date is not None
    frame, metadata = _fetch_us_equity_universe_live(
        fmp_api_key,
        min_market_cap=min_market_cap,
        exchanges=exchanges,
    )
    metadata["active_only"] = bool(active_only)
    metadata["trade_date"] = trade_date.isoformat() if trade_date is not None else None
    metadata["survivorship_bias_risk"] = survivorship_bias_risk

    # Live-screening write path: persist today's resolved universe as a snapshot
    # so future backtests can replay it (idempotent; existing file is kept).
    if active_only and not frame.empty and "symbol" in frame.columns:
        try:
            snapshot_date = trade_date or datetime.now(UTC).date()
            symbols_to_persist = [str(s) for s in frame["symbol"].dropna().astype(str).tolist() if str(s).strip()]
            if symbols_to_persist:
                save_universe_snapshot(
                    symbols_to_persist,
                    trade_date=snapshot_date,
                    source_schema=str(metadata.get("source", "unknown")),
                    root=snapshot_root,
                    overwrite=False,
                )
        except Exception:  # pragma: no cover - persistence is best-effort
            logger.warning("Universe-snapshot persistence failed for %s", snapshot_date, exc_info=True)

    return frame, metadata


def _fetch_us_equity_universe_live(
    fmp_api_key: str = "",
    *,
    min_market_cap: float | None = None,
    exchanges: str = "NASDAQ,NYSE,AMEX",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    requested_min_market_cap = float(min_market_cap) if min_market_cap is not None else None
    if min_market_cap is not None and fmp_api_key:
        client = make_fmp_client(fmp_api_key)
        return (
            _fetch_us_equity_universe_via_screener(
                client,
                min_market_cap=min_market_cap,
                exchanges=exchanges,
            ),
            {
                "source": "fmp_company_screener",
                "fallback_source": "nasdaq_trader_symbol_directory",
                "scope_definition": "US equity universe returned by the FMP company screener for the requested exchanges, filtered by the requested market-cap floor before Databento symbol support is applied.",
                "min_market_cap_requested": requested_min_market_cap,
                "min_market_cap_effective": requested_min_market_cap,
                "min_market_cap_applied": True,
                "selection_reason": "market_cap_filter_requested",
            },
        )
    if min_market_cap is not None and not fmp_api_key:
        logger.warning(
            "min_market_cap=%.0f requested but no FMP API key provided; "
            "returning unfiltered Nasdaq Trader universe instead.",
            min_market_cap,
        )

    official = _fetch_us_equity_universe_via_nasdaq_trader(exchanges=exchanges)
    if not official.empty:
        return (
            official,
            {
                "source": "nasdaq_trader_symbol_directory",
                "fallback_source": "fmp_company_screener" if fmp_api_key else None,
                "scope_definition": "Listed non-ETF, non-test issues from Nasdaq Trader symbol directories for the requested US exchanges; Databento support is applied afterward.",
                "min_market_cap_requested": requested_min_market_cap,
                "min_market_cap_effective": None,
                "min_market_cap_applied": False,
                "selection_reason": "official_directory",
            },
        )

    if fmp_api_key:
        client = make_fmp_client(fmp_api_key)
        return (
            _fetch_us_equity_universe_via_screener(
                client,
                min_market_cap=min_market_cap,
                exchanges=exchanges,
            ),
            {
                "source": "fmp_company_screener",
                "fallback_source": "nasdaq_trader_symbol_directory",
                "scope_definition": "US equity universe returned by the FMP company screener after the Nasdaq Trader directory fetch failed; Databento support is applied afterward.",
                "min_market_cap_requested": requested_min_market_cap,
                "min_market_cap_effective": requested_min_market_cap,
                "min_market_cap_applied": requested_min_market_cap is not None,
                "selection_reason": "official_directory_failed",
            },
        )

    logger.warning("Nasdaq Trader directory fetch failed and no FMP API key provided; returning empty universe.")
    return (
        _empty_universe_frame(),
        {
            "source": "empty",
            "fallback_source": None,
            "scope_definition": "No universe rows available because the Nasdaq Trader directory fetch failed and no FMP API key was provided for fallback.",
            "min_market_cap_requested": requested_min_market_cap,
            "min_market_cap_effective": None,
            "min_market_cap_applied": False,
            "selection_reason": "no_available_source",
        },
    )


# ── Per-day universe snapshots (#2351 / re-audit F2) ──────────────────────

UNIVERSE_SNAPSHOT_ROOT = Path("artifacts/universe")
UNIVERSE_SNAPSHOT_SCHEMA_VERSION = 1


def _resolve_snapshot_root(root: str | Path | None) -> Path:
    return Path(root) if root is not None else UNIVERSE_SNAPSHOT_ROOT


def _universe_snapshot_path(trade_date: date, root: str | Path | None = None) -> Path:
    return _resolve_snapshot_root(root) / f"{trade_date.isoformat()}.json"


def save_universe_snapshot(
    symbols: list[str] | tuple[str, ...] | set[str],
    *,
    trade_date: date,
    source_schema: str,
    root: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Persist a per-day universe snapshot under ``artifacts/universe/{date}.json``.

    Idempotent: when the target file already exists and ``overwrite`` is False,
    the existing path is returned unchanged so the live screening read path can
    invoke this on every run without re-writing.
    """
    path = _universe_snapshot_path(trade_date, root)
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = sorted({str(s).strip() for s in symbols if str(s).strip()})
    payload = {
        "schema_version": UNIVERSE_SNAPSHOT_SCHEMA_VERSION,
        "trade_date": trade_date.isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "source_schema": str(source_schema),
        "symbols": normalized,
        "size": len(normalized),
    }
    from databento_utils import _replace_atomic

    def _write_temp(temp_path: Path) -> None:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _replace_atomic(path, _write_temp)
    return path


def load_universe_snapshot(
    trade_date: date,
    *,
    root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return the persisted snapshot for ``trade_date`` or ``None`` when absent."""
    path = _universe_snapshot_path(trade_date, root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Universe snapshot at %s is unreadable; ignoring.", path, exc_info=True)
        return None
    if not isinstance(payload, dict) or "symbols" not in payload:
        return None
    payload["symbols"] = [str(s) for s in payload.get("symbols", [])]
    return payload


def list_universe_snapshots(root: str | Path | None = None) -> list[date]:
    """List trade-dates for which a snapshot file exists, ascending."""
    snapshot_root = _resolve_snapshot_root(root)
    if not snapshot_root.exists():
        return []
    dates: list[date] = []
    for entry in snapshot_root.iterdir():
        if entry.suffix != ".json":
            continue
        try:
            dates.append(date.fromisoformat(entry.stem))
        except ValueError:
            continue
    return sorted(dates)


# ── Backtest snapshot consumer (#2352 / re-audit F2) ──────────────────────

class MissingUniverseSnapshotError(RuntimeError):
    """Raised when a backtest requires a snapshot for ``trade_date`` and none exists."""

    def __init__(self, trade_date: date, snapshot_root: Path) -> None:
        super().__init__(
            f"No persisted universe snapshot for trade_date={trade_date.isoformat()} "
            f"under {snapshot_root}; refusing to run in strict mode (survivorship-bias "
            f"protection, #2352). Persist a snapshot first or rerun without --strict-universe."
        )
        self.trade_date = trade_date
        self.snapshot_root = snapshot_root


def load_universe_for_backtest(
    trade_date: date,
    *,
    strict: bool = False,
    snapshot_root: str | Path | None = None,
    fmp_api_key: str = "",
    min_market_cap: float | None = None,
    exchanges: str = "NASDAQ,NYSE,AMEX",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Resolve the universe a backtest should use for ``trade_date``.

    Resolution contract:

    * **Snapshot present** → strictly used (no vendor call), regardless of
      ``strict``. Metadata carries ``source="universe_snapshot"`` and
      ``survivorship_bias_risk=False``.
    * **Snapshot absent + strict=True** → raises :class:`MissingUniverseSnapshotError`.
      CI mode must use this to refuse silently survivorship-biased runs.
    * **Snapshot absent + strict=False** → logs a WARNING and falls back to
      :func:`fetch_us_equity_universe_with_metadata` with ``active_only=False``;
      the returned metadata carries ``survivorship_bias_risk=True`` so downstream
      consumers can flag the result in their reports.
    """
    snapshot = load_universe_snapshot(trade_date, root=snapshot_root)
    if snapshot is None and strict:
        raise MissingUniverseSnapshotError(
            trade_date,
            _resolve_snapshot_root(snapshot_root),
        )
    if snapshot is None:
        logger.warning(
            "Backtest for trade_date=%s requested without a persisted universe snapshot; "
            "falling back to active_only=False vendor data. Result carries survivorship-bias risk (#2352). "
            "Use --strict-universe to refuse in CI mode.",
            trade_date.isoformat(),
        )
    return fetch_us_equity_universe_with_metadata(
        fmp_api_key,
        min_market_cap=min_market_cap,
        exchanges=exchanges,
        active_only=False,
        trade_date=trade_date,
        snapshot_root=snapshot_root,
    )


