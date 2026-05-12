"""Databento OPRA.PILLAR ingestion wrapper for Unusual Options Activity.

Public surface mirrors ``ingest_unusual_whales.fetch_uw_options_flow`` so
``streamlit_monitor._cached_bz_options_op`` can swap providers behind a
feature flag (``ENABLE_OPRA_UOA``) with zero downstream renderer changes.

The detector lives in ``newsstack_fmp.opra_uoa`` and is I/O-free; this module
is the I/O shell that:

1.  Resolves the ticker list and parent-symbology symbols (``AAPL.OPT``).
2.  Pulls a short trailing window of OPRA ``trades`` records via
    :pyclass:`databento_provider.DabentoProvider`.
3.  Pulls the matching ``definition`` slice for the same window to resolve
    ``instrument_id`` -> underlying / strike / expiry / call-put.
4.  Hands both to ``detect_unusual_options_activity`` and returns the
    Benzinga-compatible record list.

Errors are swallowed and a ``[]`` list is returned (mirroring the UW
wrapper's contract) so caller code never has to special-case a degraded
Databento path.

NOTE: This wrapper deliberately accepts an ``api_key`` positional argument
even though the first parameter is unused by the OPRA path. The signature
must stay identical to ``fetch_uw_options_flow`` so the monitor's call
site can stay a single line behind a feature flag. Pass the Databento key
via the ``DATABENTO_API_KEY`` env var (consumed by ``DabentoProvider``).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from newsstack_fmp.opra_uoa import (
    OpraDefinitionRecord,
    detect_unusual_options_activity,
)

logger = logging.getLogger(__name__)

# Default trailing trades window. OPRA volume is ~1B trades/day so we keep
# the look-back tight to avoid 100MB+ pulls per refresh. 15 minutes mirrors
# the UW flow-alerts feed's typical alert lifetime.
_DEFAULT_TRADES_WINDOW_MIN = int(os.getenv("OPRA_UOA_TRADES_WINDOW_MIN", "15"))

# Databento dataset + schemas.
_OPRA_DATASET = "OPRA.PILLAR"
_TRADES_SCHEMA = "trades"
_DEFINITION_SCHEMA = "definition"


def _split_tickers(tickers: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize the caller's ticker payload into a deduped upper-case list.

    The UW wrapper accepts a comma-separated string; we accept that plus
    list/tuple for caller convenience and unit-test ergonomics.
    """
    if tickers is None:
        return []
    if isinstance(tickers, (list, tuple)):
        raw = list(tickers)
    else:
        raw = str(tickers).split(",")
    out: list[str] = []
    seen: set[str] = set()
    for r in raw:
        t = str(r).strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _parent_symbol(ticker: str) -> str:
    """Build the OPRA parent-symbology symbol for a given underlying.

    Databento exposes per-underlying option universes via the
    ``parent`` stype (``stype_in="parent"`` is implicit when the symbol
    ends with ``.OPT``). See:
    https://databento.com/docs/standards-and-conventions/symbology
    """
    return f"{ticker.strip().upper()}.OPT"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_ts(ts: datetime) -> str:
    """Render a UTC datetime as Databento ``YYYY-MM-DDTHH:MM:SS`` ISO."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _store_to_rows(store: Any) -> list[dict[str, Any]]:
    """Materialize a Databento ``DBNStore`` (or compatible) into row dicts.

    The provider returns a store whose ``.to_df()`` yields a pandas
    DataFrame. We coerce to list-of-dict because the detector only needs
    Mapping access and we don't want to force pandas into the detector's
    test fixtures.

    Returns ``[]`` on any error so caller error handling stays uniform.
    """
    if store is None:
        return []
    try:
        df = store.to_df()
    except Exception:
        logger.debug("OPRA store.to_df() failed", exc_info=True)
        return []
    if df is None or len(df) == 0:
        return []
    try:
        # ``to_dict(orient="records")`` preserves dtypes well enough for the
        # detector (it only needs price/size/side/instrument_id/ts_event).
        return df.reset_index().to_dict(orient="records")
    except Exception:
        logger.debug("OPRA DataFrame->records coercion failed", exc_info=True)
        return []


def _make_provider(api_key: str | None) -> Any | None:
    """Instantiate the Databento provider lazily.

    Returns ``None`` if instantiation fails for any reason (missing
    package, missing key, etc.); the wrapper then short-circuits to
    ``[]`` matching the UW wrapper's error contract.
    """
    try:
        from databento_provider import DabentoProvider
    except Exception:
        logger.debug("databento_provider import failed", exc_info=True)
        return None
    # Prefer the explicit kwarg key, but fall back to the env-var path the
    # provider itself honours so callers can wire either way.
    key = (api_key or os.getenv("DATABENTO_API_KEY", "") or "").strip()
    if not key:
        logger.debug("OPRA UOA: no Databento API key available")
        return None
    try:
        return DabentoProvider(api_key=key)
    except Exception:
        logger.warning("DabentoProvider instantiation failed", exc_info=True)
        return None


def fetch_opra_options_flow(
    api_key: str,
    tickers: str | list[str] | tuple[str, ...],
    *,
    limit: int = 100,  # kept for signature parity; OPRA cap is via window+premium
    min_premium: float | None = None,
    window_minutes: int | None = None,
    databento_api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Return Benzinga-compatible UOA records sourced from OPRA.PILLAR.

    Parameters
    ----------
    api_key
        Ignored (kept for call-site parity with ``fetch_uw_options_flow``).
        The Databento key is read from ``DATABENTO_API_KEY`` or the
        ``databento_api_key`` kwarg below.
    tickers
        Comma-separated string or iterable of underlying tickers.
    limit
        Soft cap on the number of records returned. Applied AFTER detector
        output so sweep-cluster context isn't truncated.
    min_premium
        Optional dollar gate forwarded to the detector. ``None`` = $25k
        default (see :pyfunc:`newsstack_fmp.opra_uoa.detect_unusual_options_activity`).
    window_minutes
        Look-back window in minutes. Defaults to ``OPRA_UOA_TRADES_WINDOW_MIN``
        env var or 15 minutes.
    databento_api_key
        Explicit override for the Databento key. Falls back to env.

    Returns
    -------
    list[dict[str, Any]]
        Empty list on any failure; never raises.
    """
    # The unused ``api_key`` parameter is intentional \u2014 see module docstring.
    del api_key
    norm_tickers = _split_tickers(tickers)
    if not norm_tickers:
        return []

    provider = _make_provider(databento_api_key)
    if provider is None:
        return []

    window_min = int(window_minutes or _DEFAULT_TRADES_WINDOW_MIN)
    window_min = max(window_min, 1)
    end_dt = _utc_now()
    start_dt = end_dt - timedelta(minutes=window_min)
    start_iso = _format_ts(start_dt)
    end_iso = _format_ts(end_dt)

    symbols = [_parent_symbol(t) for t in norm_tickers]

    # ---- pull trades ----
    try:
        trades_store = provider.get_range(
            context="opra_uoa.trades",
            dataset=_OPRA_DATASET,
            symbols=symbols,
            schema=_TRADES_SCHEMA,
            start=start_iso,
            end=end_iso,
        )
    except Exception:
        logger.warning(
            "OPRA UOA: trades get_range failed (tickers=%s window=%dm)",
            norm_tickers, window_min, exc_info=True,
        )
        return []
    trade_rows = _store_to_rows(trades_store)
    if not trade_rows:
        return []

    # ---- pull definitions (parallel slice) ----
    # ``definition`` is published once per session per instrument, so even a
    # 15-minute window typically yields a complete map for active strikes.
    # If gaps surface in production we'll widen this to a session-aligned
    # 24h pull and cache the resulting map.
    try:
        defs_store = provider.get_range(
            context="opra_uoa.definition",
            dataset=_OPRA_DATASET,
            symbols=symbols,
            schema=_DEFINITION_SCHEMA,
            start=start_iso,
            end=end_iso,
        )
    except Exception:
        logger.warning(
            "OPRA UOA: definition get_range failed (tickers=%s window=%dm)",
            norm_tickers, window_min, exc_info=True,
        )
        return []
    def_rows = _store_to_rows(defs_store)
    if not def_rows:
        # Without definitions we cannot map instrument_id -> underlying.
        # Bail rather than emit malformed records.
        logger.info(
            "OPRA UOA: no definition rows for tickers=%s window=%dm; skipping",
            norm_tickers, window_min,
        )
        return []

    definitions = [OpraDefinitionRecord.from_row(r) for r in def_rows]

    try:
        records = detect_unusual_options_activity(
            trade_rows,
            definitions,
            min_premium=min_premium,
            tickers=norm_tickers,
        )
    except Exception:
        logger.warning("OPRA UOA detector raised", exc_info=True)
        return []

    if limit and limit > 0 and len(records) > limit:
        records = records[:limit]
    return records


__all__ = ["fetch_opra_options_flow"]
