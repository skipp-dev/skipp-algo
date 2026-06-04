"""EV-13 — Databento data-pull wrapper for the first real edge-pipeline run.

The EV-04..EV-12 stack built the whole evidence machine; this wrapper is the
credential-bound on-ramp that turns *real* Databento OHLCV into the exact
JSON :mod:`scripts.run_edge_pipeline` consumes::

    Databento ohlcv-* get_range
        -> normalize_ohlcv_frame            (pure, tested)
        -> build_explicit_structure_from_bars   (canonical SMC detection)
        -> _prepare_symbol_resampled_bars       (same resampled frame the
                                                  structure events anchor on)
        -> {bars, structure, as_of, ...}     (run_edge_pipeline input)

Two halves, deliberately separated so the credential-free transform is unit
tested and only the network call is environment-bound:

* :func:`structure_and_bars_to_pipeline_input` — PURE. Given a base-granularity
  OHLCV ``DataFrame`` it detects structure and emits the pipeline payload. The
  emitted ``bars`` are the *resampled* timeframe bars (NOT the raw input), so
  the anchor indices and forward windows match exactly what the structure
  detector — and therefore the live scorer — observed. Feeding the raw base
  bars here would silently misalign every event's lookahead window.
* :func:`fetch_ohlcv_frame` — IMPURE. Reads ``DATABENTO_API_KEY`` from the
  environment and calls ``timeseries.get_range``. Never unit tested against the
  live API; it is a thin, redaction-safe shim over the existing retrying client.

It fabricates nothing: every bar and every detected event traces to the
Databento response. When a symbol yields no resampled bars or no structure
events, the wrapper refuses loudly rather than emitting an empty payload that
would mislead the gate into a vacuous "not evaluated".

Roadmap pointer: Edge-Validation Roadmap, Phase 2 / story EV-13
(first-real-run on-ramp). See docs/edge_first_real_run_runbook.md.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from governance.family_returns import DEFAULT_COST_BPS
from scripts.explicit_structure_from_bars import (
    _TIMEFRAME_TO_PANDAS_FREQ,
    _canonical_timeframe,
    _prepare_symbol_resampled_bars,
    build_explicit_structure_from_bars,
)
from scripts.smc_atomic_write import atomic_write_json
from scripts.smc_price_action_engine import coerce_timestamps_to_epoch_seconds

# Databento OHLCV schemas, smallest base granularity to largest. The fetch
# granularity must be at or below the structure timeframe so resampling up is
# well defined.
_OHLCV_SCHEMAS = ("ohlcv-1s", "ohlcv-1m", "ohlcv-1h", "ohlcv-1d")

# Structure container keys, mirrored from family_event_adapter so the payload
# shape is validated here rather than failing deep in the pipeline.
_STRUCTURE_KEYS = ("bos", "orderblocks", "fvg", "liquidity_sweeps")

# Candidate timestamp columns a Databento ``.to_df()`` frame may carry, in
# preference order (mirror of databento_volatility_screener._coerce_timestamp_frame).
_TIMESTAMP_CANDIDATES = ("ts_event", "ts_recv", "ts", "timestamp", "index")

_REQUIRED_OHLCV_COLUMNS = ("open", "high", "low", "close")

# ADR-0016 aggressor-signed order-flow data path. The ``trades`` schema carries
# a real per-trade ``side`` (A=sell aggressor, B=buy aggressor, N=no side) so the
# signed volume is sourced from the venue's book state, not a tick-rule guess.
_TRADES_SCHEMA = "trades"
_REQUIRED_TRADES_COLUMNS = ("price", "size", "side")

# ADR-0020 options-flow data path. OPRA option trades are pulled from the
# consolidated options feed via PARENT symbology (``{SYMBOL}.OPT``), so every
# returned print is already an option on the requested underlying -- no
# ``definition`` join is needed to recover the underlying.
#
# SCHEMA = ``tcbbo`` (trade + consolidated BBO), NOT plain ``trades``:
# empirically the OPRA ``trades`` ``side`` field is uniformly ``N`` (the
# consolidated options tape does not stamp a reliable aggressor flag), so a
# ``trades``-only pull yields ``uoa_signed_notional == 0`` on every bar -- a
# zero-variance, A/B-useless feature. ``OPRA.PILLAR`` does not offer the
# venue-level ``tbbo`` schema; its trade-with-quote schema is ``tcbbo`` (trades
# stamped with the *consolidated* NBBO). It emits one record per trade carrying
# the NBBO at the print (``bid_px_00`` / ``ask_px_00``), so the aggressor is
# reconstructed with the quote rule in :func:`normalize_opra_trades_frame`:
#   price >= ask -> ask-lift -> aggressive BUYER  -> ``A``
#   price <= bid -> bid-hit  -> aggressive SELLER -> ``B``
#   inside spread / locked / missing quote        -> ``N`` (honest unsigned)
# The OPRA aggressor convention is INVERSE of equities (A=bullish buyer +,
# B=bearish seller -); that sign flip lives in
# :func:`aggregate_signed_uoa_notional`, not here.
_OPRA_DATASET = "OPRA.PILLAR"
_OPRA_TRADES_SCHEMA = "tcbbo"
_OPRA_PARENT_STYPE = "parent"
_REQUIRED_OPRA_TRADES_COLUMNS = ("price", "size", "side")
# NBBO columns carried by the ``tcbbo`` schema (level-0 consolidated best
# bid/ask at the print). When present, they drive the quote-rule aggressor
# reconstruction; when absent (a plain ``trades`` frame, e.g. in unit tests),
# the raw ``side`` enum is passed through unchanged for back-compat.
_OPRA_BID_PX_COL = "bid_px_00"
_OPRA_ASK_PX_COL = "ask_px_00"


def normalize_ohlcv_frame(raw: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    """Coerce a raw Databento OHLCV frame into the structure-detector schema.

    Returns a frame with columns ``symbol, timestamp, open, high, low, close,
    volume`` where ``timestamp`` is epoch **seconds** (the unit
    ``build_explicit_structure_from_bars`` expects). A ``DatetimeIndex`` or any
    of the known ``ts_*`` columns is accepted; an unrecognised frame raises
    rather than guessing.
    """
    if raw.empty:
        raise ValueError("Databento frame is empty; nothing to normalize")

    frame = raw.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.reset_index()
        frame = frame.rename(columns={frame.columns[0]: "ts"})
        ts_col = "ts"
    else:
        ts_col = next((c for c in _TIMESTAMP_CANDIDATES if c in frame.columns), "")
        if not ts_col:
            raise ValueError(
                "no timestamp column found in Databento frame; expected a "
                f"DatetimeIndex or one of {_TIMESTAMP_CANDIDATES}"
            )

    missing = [c for c in _REQUIRED_OHLCV_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"Databento frame missing required OHLCV columns: {missing}")

    timestamps = pd.to_datetime(frame[ts_col], utc=True)
    # tz-aware -> epoch seconds via Timedelta subtraction (version-safe; avoids
    # the deprecated Series.view and the tz-aware astype("int64") error).
    epoch_seconds = (timestamps - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    out = pd.DataFrame(
        {
            # Epoch seconds; _coerce_bars re-reads this with unit="s".
            "timestamp": epoch_seconds,
            "open": pd.to_numeric(frame["open"], errors="coerce"),
            "high": pd.to_numeric(frame["high"], errors="coerce"),
            "low": pd.to_numeric(frame["low"], errors="coerce"),
            "close": pd.to_numeric(frame["close"], errors="coerce"),
        }
    )
    if "symbol" in frame.columns:
        out["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    else:
        out["symbol"] = str(symbol).strip().upper()
    out["volume"] = (
        pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
        if "volume" in frame.columns
        else 0.0
    )
    out = out.dropna(subset=list(_REQUIRED_OHLCV_COLUMNS))
    if out.empty:
        raise ValueError("Databento frame has no usable OHLCV rows after coercion")
    return out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def normalize_trades_frame(raw: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    """Coerce a raw Databento ``trades`` frame into the signed-volume schema.

    Returns a frame with columns ``symbol, timestamp, price, size, side`` where
    ``timestamp`` is epoch **seconds** (matching :func:`normalize_ohlcv_frame`
    so trade buckets and OHLCV bars share one clock). ``side`` is upper-cased to
    the Databento enum ``{"A", "B", "N"}``; a ``DatetimeIndex`` or any known
    ``ts_*`` column is accepted, an unrecognised frame raises rather than
    guessing.
    """
    if raw.empty:
        raise ValueError("Databento trades frame is empty; nothing to normalize")

    frame = raw.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.reset_index()
        frame = frame.rename(columns={frame.columns[0]: "ts"})
        ts_col = "ts"
    else:
        ts_col = next((c for c in _TIMESTAMP_CANDIDATES if c in frame.columns), "")
        if not ts_col:
            raise ValueError(
                "no timestamp column found in Databento trades frame; expected a "
                f"DatetimeIndex or one of {_TIMESTAMP_CANDIDATES}"
            )

    missing = [c for c in _REQUIRED_TRADES_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"Databento trades frame missing required columns: {missing}")

    timestamps = pd.to_datetime(frame[ts_col], utc=True)
    epoch_seconds = (timestamps - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    out = pd.DataFrame(
        {
            "timestamp": epoch_seconds,
            "price": pd.to_numeric(frame["price"], errors="coerce"),
            "size": pd.to_numeric(frame["size"], errors="coerce").astype("float64"),
            "side": frame["side"].astype(str).str.strip().str.upper(),
        }
    )
    if "symbol" in frame.columns:
        out["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    else:
        out["symbol"] = str(symbol).strip().upper()
    out = out.dropna(subset=["timestamp", "size"])
    if out.empty:
        raise ValueError("Databento trades frame has no usable rows after coercion")
    return out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def _quote_rule_opra_aggressor(
    price: pd.Series, bid: pd.Series, ask: pd.Series
) -> pd.Series:
    """Reconstruct the OPRA aggressor enum from the NBBO at each print.

    The consolidated OPRA tape does not stamp a reliable aggressor ``side`` (it
    is uniformly ``N``), so the side is inferred from the trade price relative to
    the best bid/ask carried by the ``tcbbo`` schema (the classic quote rule):

    * ``price >= ask`` -> the print lifted the offer -> aggressive **buyer** ->
      ``"A"`` (bullish under the INVERSE OPRA convention applied downstream).
    * ``price <= bid`` -> the print hit the bid -> aggressive **seller** ->
      ``"B"`` (bearish).
    * anything else -- strictly inside the spread, a locked/crossed quote
      (``ask <= bid``), or a missing bid/ask/price -- stays ``"N"`` (honest
      unsigned; contributes 0 to the signed sum but is still counted).

    Returns an object Series of ``{"A", "B", "N"}`` aligned to ``price.index``.
    """
    side = pd.Series("N", index=price.index, dtype="object")
    valid = price.notna() & bid.notna() & ask.notna() & (ask > bid)
    side = side.mask(valid & (price >= ask), "A")
    side = side.mask(valid & (price <= bid), "B")
    return side


def normalize_opra_trades_frame(raw: pd.DataFrame, *, underlying: str) -> pd.DataFrame:
    """Coerce a raw OPRA ``tcbbo`` frame into the signed-UOA-notional schema.

    Returns a frame with columns ``underlying, timestamp, price, size, side``
    where ``timestamp`` is epoch **seconds** (matching :func:`normalize_ohlcv_
    frame` so option-print buckets and OHLCV bars share one clock), ``price`` is
    the per-contract premium (dollars), ``size`` the contract count, and ``side``
    the upper-cased Databento enum ``{"A", "B", "N"}``.

    Because OPRA trades are pulled via parent symbology (``{underlying}.OPT``),
    every print already belongs to the requested underlying; the ``underlying``
    column is stamped on for provenance rather than recovered per row. A
    ``DatetimeIndex`` or any known ``ts_*`` column is accepted; an unrecognised
    frame raises rather than guessing.

    When the source frame carries the ``tcbbo`` NBBO columns
    (``bid_px_00`` / ``ask_px_00``), ``side`` is RECONSTRUCTED from the quote
    rule (:func:`_quote_rule_opra_aggressor`) because the raw OPRA ``side`` field
    is uniformly ``N``. When those columns are absent (a plain ``trades`` frame,
    e.g. in unit tests), the raw ``side`` enum is passed through unchanged.
    """
    if raw.empty:
        raise ValueError("OPRA trades frame is empty; nothing to normalize")

    frame = raw.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.reset_index()
        frame = frame.rename(columns={frame.columns[0]: "ts"})
        ts_col = "ts"
    else:
        ts_col = next((c for c in _TIMESTAMP_CANDIDATES if c in frame.columns), "")
        if not ts_col:
            raise ValueError(
                "no timestamp column found in OPRA trades frame; expected a "
                f"DatetimeIndex or one of {_TIMESTAMP_CANDIDATES}"
            )

    missing = [c for c in _REQUIRED_OPRA_TRADES_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"OPRA trades frame missing required columns: {missing}")

    timestamps = pd.to_datetime(frame[ts_col], utc=True)
    epoch_seconds = (timestamps - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    price = pd.to_numeric(frame["price"], errors="coerce")
    # Reconstruct the aggressor from the NBBO when the tcbbo quote columns are
    # present (the raw OPRA ``side`` is uniformly N); otherwise pass it through.
    if _OPRA_BID_PX_COL in frame.columns and _OPRA_ASK_PX_COL in frame.columns:
        side = _quote_rule_opra_aggressor(
            price,
            pd.to_numeric(frame[_OPRA_BID_PX_COL], errors="coerce"),
            pd.to_numeric(frame[_OPRA_ASK_PX_COL], errors="coerce"),
        )
    else:
        side = frame["side"].astype(str).str.strip().str.upper()
    out = pd.DataFrame(
        {
            "timestamp": epoch_seconds,
            "price": price,
            "size": pd.to_numeric(frame["size"], errors="coerce").astype("float64"),
            "side": side,
        }
    )
    out["underlying"] = str(underlying).strip().upper()
    out = out.dropna(subset=["timestamp", "size", "price"])
    if out.empty:
        raise ValueError("OPRA trades frame has no usable rows after coercion")
    return out.sort_values(["underlying", "timestamp"]).reset_index(drop=True)


def aggregate_signed_volume(trades: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Bucket signed trade volume onto the same grid the OHLCV bars use.

    Reuses the resampler's exact ``bucket_end`` rule
    (``scripts.explicit_structure_from_bars.resample_bars_to_timeframe``):
    ``floored = ts.floor(freq)``; ``bucket_end = floored`` when the trade lands
    exactly on the boundary, else ``floored + freq``. This left-open /
    right-closed labelling is identical to the OHLCV resample, so the emitted
    ``timestamp`` joins one-to-one onto the resampled bar timestamps.

    Per bucket: ``signed_volume`` = ``sum(size)`` over buy aggressors (``side``
    ``B``) minus sell aggressors (``side`` ``A``); ``N`` (auction / non-displayed
    / no-side trades) contribute **0** to the signed sum but are still counted in
    ``trade_count``. ``abs_volume`` = ``sum(size)`` over **all** trades in the
    bucket (the total traded size, an unsigned magnitude) -- the order-flow
    imbalance denominator (ADR-0019). Returns columns
    ``timestamp, signed_volume, trade_count, abs_volume`` (epoch seconds). An
    empty input yields an empty frame.
    """
    columns = ["timestamp", "signed_volume", "trade_count", "abs_volume"]
    if trades.empty:
        return pd.DataFrame(columns=columns)

    canonical_tf = _canonical_timeframe(timeframe)
    freq = _TIMEFRAME_TO_PANDAS_FREQ[canonical_tf]
    offset = pd.tseries.frequencies.to_offset(freq)

    ts = pd.to_datetime(trades["timestamp"], unit="s", utc=True)
    floored = ts.dt.floor(freq)
    bucket_end = floored.where(ts.eq(floored), floored + offset)

    size = pd.to_numeric(trades["size"], errors="coerce").astype("float64").fillna(0.0)
    side = trades["side"].astype(str).str.strip().str.upper()
    # Buy aggressor (+), sell aggressor (-); anything else (N/blank) is unsigned.
    # NB: the float64 cast above is load-bearing -- Databento delivers ``size``
    # as uint32, and ``0 - size`` on an unsigned dtype underflows to ``2**32 -
    # size`` (a sell trade would add ~4.3e9 instead of subtracting its size).
    signed = size.where(side.eq("B"), 0.0) - size.where(side.eq("A"), 0.0)

    work = pd.DataFrame(
        {"bucket_end": bucket_end, "signed": signed, "abs": size, "count": 1}
    ).dropna(subset=["bucket_end"])
    if work.empty:
        return pd.DataFrame(columns=columns)

    grouped = (
        work.groupby("bucket_end", sort=True)
        .agg(
            signed_volume=("signed", "sum"),
            trade_count=("count", "sum"),
            abs_volume=("abs", "sum"),
        )
        .reset_index()
    )
    grouped["timestamp"] = coerce_timestamps_to_epoch_seconds(grouped["bucket_end"])
    return grouped[columns].reset_index(drop=True)


def _merge_signed_volume_into_bars(
    bars: list[dict[str, float]], trades: pd.DataFrame, timeframe: str
) -> None:
    """Embed ``signed_volume`` + ``trade_count`` + ``abs_volume`` into each bar
    dict in place.

    Additive keys only -- the OHLCV keyset is untouched, so the bar-frame column
    validators (subset checks) keep passing and the shadow extractor signature
    ``(bars, anchor_idx)`` needs no new argument. Bars whose bucket saw no trades
    are left as honest OHLCV-only dicts (the extractor returns honest-None there).
    """
    agg = aggregate_signed_volume(trades, timeframe)
    if agg.empty:
        return
    lookup = {
        int(row.timestamp): (
            float(row.signed_volume),
            int(row.trade_count),
            float(row.abs_volume),
        )
        for row in agg.itertuples(index=False)
    }
    for bar in bars:
        signed = lookup.get(int(bar["timestamp"]))
        if signed is not None:
            (
                bar["signed_volume"],
                bar["trade_count"],
                bar["abs_volume"],
            ) = signed


# OCC standard equity-option contract multiplier (100 shares per contract).
# Mirrors ``newsstack_fmp.opra_uoa._OCC_CONTRACT_MULTIPLIER`` so the recorded
# ADR-0020 shadow feature and the live UOA alerts price premium identically; it
# is duplicated (not imported) to keep this scripts module decoupled from the
# news stack. The OCC multiplier is a fixed market convention, not a tunable.
_OCC_CONTRACT_MULTIPLIER = 100


def aggregate_signed_uoa_notional(
    opra_trades: pd.DataFrame, timeframe: str
) -> pd.DataFrame:
    """Bucket signed OPRA options-premium notional onto the OHLCV bar grid.

    Reuses the resampler's exact ``bucket_end`` rule (identical to
    :func:`aggregate_signed_volume`), so the emitted ``timestamp`` joins
    one-to-one onto the resampled bar timestamps of the *underlying*.

    ``opra_trades`` is an OPRA ``trades`` frame already mapped to the underlying
    (one row per option print) with columns ``timestamp`` (epoch seconds),
    ``size`` (contracts), ``price`` (per-contract premium, dollars) and ``side``
    (``A`` / ``B`` / ``N``). Per print the notional premium is
    ``price * size * 100`` (the OCC multiplier).

    The OPRA aggressor convention is the **inverse** of the equity tape: ``A``
    (trade hit the ask) is the aggressive **buyer** -> ``+`` (bullish); ``B``
    (hit the bid) is the aggressive **seller** -> ``-`` (bearish); ``N``
    (cross / unknown) contributes ``0`` to the signed sum but is still counted in
    ``uoa_trade_count`` and ``uoa_abs_notional``. This matches
    ``newsstack_fmp.opra_uoa._side_to_aggressor`` exactly.

    Per bucket: ``uoa_signed_notional`` = signed premium sum;
    ``uoa_abs_notional`` = total premium sum over **all** prints (the imbalance
    denominator, ADR-0020). Returns columns ``timestamp, uoa_signed_notional,
    uoa_trade_count, uoa_abs_notional`` (epoch seconds). An empty input yields an
    empty frame.
    """
    columns = [
        "timestamp",
        "uoa_signed_notional",
        "uoa_trade_count",
        "uoa_abs_notional",
    ]
    if opra_trades.empty:
        return pd.DataFrame(columns=columns)

    canonical_tf = _canonical_timeframe(timeframe)
    freq = _TIMEFRAME_TO_PANDAS_FREQ[canonical_tf]
    offset = pd.tseries.frequencies.to_offset(freq)

    ts = pd.to_datetime(opra_trades["timestamp"], unit="s", utc=True)
    floored = ts.dt.floor(freq)
    bucket_end = floored.where(ts.eq(floored), floored + offset)

    # float64 cast is load-bearing: Databento delivers ``size`` as uint32, and a
    # signed subtraction on an unsigned dtype underflows (see aggregate_signed_
    # volume). ``price`` is fixed-point but coerced for the multiply.
    size = pd.to_numeric(opra_trades["size"], errors="coerce").astype("float64").fillna(0.0)
    price = pd.to_numeric(opra_trades["price"], errors="coerce").astype("float64").fillna(0.0)
    notional = size * price * float(_OCC_CONTRACT_MULTIPLIER)
    side = opra_trades["side"].astype(str).str.strip().str.upper()
    # INVERSE of equity: ask-side (A) is the aggressive buyer (+), bid-side (B)
    # the aggressive seller (-); anything else (N/blank) is unsigned.
    signed = notional.where(side.eq("A"), 0.0) - notional.where(side.eq("B"), 0.0)

    work = pd.DataFrame(
        {
            "bucket_end": bucket_end,
            "signed": signed,
            "abs": notional,
            "count": 1,
        }
    ).dropna(subset=["bucket_end"])
    if work.empty:
        return pd.DataFrame(columns=columns)

    grouped = (
        work.groupby("bucket_end", sort=True)
        .agg(
            uoa_signed_notional=("signed", "sum"),
            uoa_trade_count=("count", "sum"),
            uoa_abs_notional=("abs", "sum"),
        )
        .reset_index()
    )
    grouped["timestamp"] = coerce_timestamps_to_epoch_seconds(grouped["bucket_end"])
    return grouped[columns].reset_index(drop=True)


def _merge_signed_uoa_notional_into_bars(
    bars: list[dict[str, float]], opra_trades: pd.DataFrame, timeframe: str
) -> None:
    """Embed ``uoa_signed_notional`` + ``uoa_trade_count`` + ``uoa_abs_notional``
    into each matching bar dict in place.

    Additive keys only -- the OHLCV keyset is untouched, so the bar-frame column
    validators keep passing and the shadow extractor signature
    ``(bars, anchor_idx)`` needs no new argument. Bars whose bucket saw no option
    prints are left without the keys; the ``signed_uoa_notional_at`` extractor
    treats those as an honest no-flow gap (contributes 0), so a window with zero
    total premium returns honest-None.
    """
    agg = aggregate_signed_uoa_notional(opra_trades, timeframe)
    if agg.empty:
        return
    lookup = {
        int(row.timestamp): (
            float(row.uoa_signed_notional),
            int(row.uoa_trade_count),
            float(row.uoa_abs_notional),
        )
        for row in agg.itertuples(index=False)
    }
    for bar in bars:
        uoa = lookup.get(int(bar["timestamp"]))
        if uoa is not None:
            (
                bar["uoa_signed_notional"],
                bar["uoa_trade_count"],
                bar["uoa_abs_notional"],
            ) = uoa


def _resampled_bars_payload(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict[str, float]]:
    """The resampled timeframe bars the structure events anchor on.

    Reuses the structure module's own resampler so the emitted ``bars`` list is
    byte-for-byte the frame the detector indexed — guaranteeing the pipeline's
    anchor/lookahead arithmetic matches the live scorer.

    Emits the full OHLCV bar (``open`` and ``volume`` included, not just HLC).
    The resampler already aggregates volume (sum) and open (first); dropping
    them here previously starved the ADR-0019 order-flow candidates
    (``governance.family_score_features_v2.relative_volume_at`` and the Amihud
    illiquidity proxy) of their only input, forcing an honest-None on every
    bar. Carrying volume point-in-time unblocks their pre-registered A/B.
    """
    resampled, _canonical_tf = _prepare_symbol_resampled_bars(df, symbol, timeframe)
    if resampled.empty:
        return []
    return [
        {
            "timestamp": float(row.timestamp),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        for row in resampled.itertuples(index=False)
    ]


def structure_and_bars_to_pipeline_input(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str = "15m",
    as_of: float | str | None = None,
    periods_per_year: int = 252,
    cost_bps: float = DEFAULT_COST_BPS,
    structure_profile: str = "hybrid_default",
    dataset: str | None = None,
    schema: str | None = None,
    start: str | None = None,
    end: str | None = None,
    trades: pd.DataFrame | None = None,
    opra_trades: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build a :mod:`scripts.run_edge_pipeline` input payload from real bars.

    ``df`` is a base-granularity OHLCV frame (output of
    :func:`normalize_ohlcv_frame`). ``as_of`` arms the EV-04 point-in-time
    guard; when ``None`` it defaults to the last resampled bar's timestamp so
    the guard is always armed against the data's own horizon.

    When ``trades`` (output of :func:`normalize_trades_frame`) is supplied, the
    ADR-0016 aggressor-signed aggregates ``signed_volume`` + ``trade_count`` are
    bucketed onto the same grid and embedded into each matching bar dict as
    additive keys (OHLCV keyset unchanged). Bars whose bucket saw no trades stay
    OHLCV-only.

    When ``opra_trades`` (an OPRA ``trades`` frame mapped to the underlying) is
    supplied, the ADR-0020 ``uoa_signed_notional`` + ``uoa_abs_notional`` options
    -flow aggregates are bucketed onto the same grid and embedded the same way,
    feeding the recorded-only ``signed_uoa_notional_at`` shadow feature. Bars
    whose bucket saw no option prints stay without the UOA keys.

    Raises ``ValueError`` when the symbol produces no resampled bars or no
    structure events (an honest empty result, never a fabricated payload).
    """
    structure = build_explicit_structure_from_bars(
        df, symbol=symbol, timeframe=timeframe, structure_profile=structure_profile
    )
    bars = _resampled_bars_payload(df, symbol, timeframe)
    if not bars:
        raise ValueError(
            f"symbol {symbol!r} produced no resampled {timeframe} bars; "
            "cannot build a pipeline input"
        )
    if not any(structure.get(key) for key in _STRUCTURE_KEYS):
        raise ValueError(
            f"symbol {symbol!r} produced no detected SMC structure "
            f"({_STRUCTURE_KEYS}); nothing to evaluate"
        )

    if trades is not None and not trades.empty:
        _merge_signed_volume_into_bars(bars, trades, timeframe)

    if opra_trades is not None and not opra_trades.empty:
        _merge_signed_uoa_notional_into_bars(bars, opra_trades, timeframe)

    resolved_as_of = as_of if as_of is not None else bars[-1]["timestamp"]

    payload: dict[str, Any] = {
        "bars": bars,
        "structure": {key: structure.get(key, []) for key in _STRUCTURE_KEYS},
        "periods_per_year": int(periods_per_year),
        "cost_bps": float(cost_bps),
        "as_of": resolved_as_of,
        "provenance": {
            "symbol": str(symbol).strip().upper(),
            "timeframe": timeframe,
            "structure_profile": structure_profile,
            "source": "databento",
            "bar_count": len(bars),
            # Full fetch context so the downstream governance archive is
            # self-describing and a multi-symbol dashboard scan can filter
            # heterogeneous runs apart (omitted keys stay ``None`` for
            # non-CLI callers that don't know the fetch window).
            "dataset": dataset,
            "schema": schema,
            "window": {"start": start, "end": end},
            "with_trades": bool(trades is not None and not trades.empty),
            "with_opra": bool(opra_trades is not None and not opra_trades.empty),
        },
    }
    return payload


def fetch_ohlcv_frame(
    symbol: str,
    *,
    dataset: str,
    schema: str,
    start: str,
    end: str,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch a raw OHLCV frame from Databento (credential-bound, not unit tested).

    Reads ``DATABENTO_API_KEY`` from the environment when ``api_key`` is omitted.
    A thin shim over the repo's retrying client; the returned frame is handed to
    :func:`normalize_ohlcv_frame`.
    """
    if schema not in _OHLCV_SCHEMAS:
        raise ValueError(f"schema must be one of {_OHLCV_SCHEMAS}, got {schema!r}")

    # Imported lazily so the pure transform path carries no databento dependency.
    from databento_client import (
        _databento_get_range_with_retry,
        _make_databento_client,
    )

    client = _make_databento_client(api_key)
    store = _databento_get_range_with_retry(
        client,
        context="pull_databento_edge_input",
        dataset=dataset,
        symbols=[str(symbol).strip().upper()],
        schema=schema,
        start=start,
        end=end,
    )
    frame = store.to_df()
    return normalize_ohlcv_frame(frame, symbol=symbol)


def fetch_trades_frame(
    symbol: str,
    *,
    dataset: str,
    start: str,
    end: str,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch a raw ``trades`` frame from Databento (credential-bound, not unit tested).

    Mirrors :func:`fetch_ohlcv_frame`: reads ``DATABENTO_API_KEY`` from the
    environment when ``api_key`` is omitted and shims the repo's retrying client,
    then hands the response to :func:`normalize_trades_frame`. Trades are pulled
    from the same ``dataset`` as the OHLCV bars (e.g. ``XNAS.ITCH``).
    """
    from databento_client import (
        _databento_get_range_with_retry,
        _make_databento_client,
    )

    client = _make_databento_client(api_key)
    store = _databento_get_range_with_retry(
        client,
        context="pull_databento_edge_input_trades",
        dataset=dataset,
        symbols=[str(symbol).strip().upper()],
        schema=_TRADES_SCHEMA,
        start=start,
        end=end,
    )
    frame = store.to_df()
    return normalize_trades_frame(frame, symbol=symbol)


def fetch_opra_trades_frame(
    symbol: str,
    *,
    start: str,
    end: str,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch a raw OPRA ``tcbbo`` frame for one underlying (credential-bound).

    Mirrors :func:`fetch_trades_frame` but targets the consolidated options feed
    ``OPRA.PILLAR`` and resolves the whole option chain through **parent
    symbology**: ``symbols=[f"{symbol}.OPT"], stype_in="parent"`` returns every
    OPRA print on the underlying, so the response needs no ``definition`` join to
    recover the underlying. The ``tcbbo`` schema (trade + consolidated BBO)
    attaches the NBBO at each print so the aggressor can be reconstructed with
    the quote rule (the raw OPRA ``side`` is uniformly ``N``). The frame is
    handed to :func:`normalize_opra_trades_frame`.

    Not unit tested against the live API (no OPRA entitlement in CI); the pure
    normaliser and the aggregation it feeds carry the tested contract.
    """
    from databento_client import (
        _databento_get_range_with_retry,
        _make_databento_client,
    )

    client = _make_databento_client(api_key)
    underlying = str(symbol).strip().upper()
    store = _databento_get_range_with_retry(
        client,
        context="pull_databento_edge_input_opra",
        dataset=_OPRA_DATASET,
        symbols=[f"{underlying}.OPT"],
        stype_in=_OPRA_PARENT_STYPE,
        schema=_OPRA_TRADES_SCHEMA,
        start=start,
        end=end,
    )
    frame = store.to_df()
    return normalize_opra_trades_frame(frame, underlying=underlying)


def _coerce_as_of_arg(value: str | None) -> float | str | None:
    """CLI ``--as-of``: passthrough ISO string / epoch, or None to auto-default."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        # Validate it parses as ISO now so the CLI fails fast, but pass the
        # string through (run_edge_pipeline._coerce_as_of treats naive as UTC).
        datetime.fromisoformat(text).replace(tzinfo=UTC)
        return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "EV-13: pull real Databento OHLCV and emit a run_edge_pipeline "
            "input JSON (bars + detected SMC structure)."
        )
    )
    parser.add_argument("--symbol", required=True, help="Instrument symbol, e.g. AAPL.")
    parser.add_argument("--dataset", required=True, help="Databento dataset, e.g. XNAS.ITCH.")
    parser.add_argument(
        "--schema",
        default="ohlcv-1m",
        choices=_OHLCV_SCHEMAS,
        help="Databento fetch granularity (must be <= --timeframe).",
    )
    parser.add_argument("--timeframe", default="15m", help="Structure timeframe (5m/15m/1H/4H/1D).")
    parser.add_argument("--start", required=True, help="Inclusive start (ISO date/datetime).")
    parser.add_argument("--end", required=True, help="Exclusive end (ISO date/datetime).")
    parser.add_argument(
        "--as-of",
        default=None,
        help="Point-in-time boundary (ISO or epoch). Default: last bar timestamp.",
    )
    parser.add_argument("--structure-profile", default="hybrid_default")
    parser.add_argument("--periods-per-year", type=int, default=252)
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    parser.add_argument(
        "--with-trades",
        action="store_true",
        help=(
            "Also pull the ADR-0016 aggressor-signed ``trades`` schema from the "
            "same dataset and embed per-bar signed_volume + trade_count. Default "
            "off keeps the OHLCV-only payload byte-for-byte unchanged."
        ),
    )
    parser.add_argument(
        "--with-opra",
        action="store_true",
        help=(
            "Also pull the ADR-0020 OPRA option ``trades`` (OPRA.PILLAR, parent "
            "symbology {SYMBOL}.OPT) and embed per-bar uoa_signed_notional + "
            "uoa_abs_notional. Default off keeps the payload unchanged. Requires "
            "an OPRA-entitled key."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the run_edge_pipeline input JSON.",
    )
    args = parser.parse_args(argv)

    try:
        frame = fetch_ohlcv_frame(
            args.symbol,
            dataset=args.dataset,
            schema=args.schema,
            start=args.start,
            end=args.end,
        )
        trades = (
            fetch_trades_frame(
                args.symbol,
                dataset=args.dataset,
                start=args.start,
                end=args.end,
            )
            if args.with_trades
            else None
        )
        opra_trades = (
            fetch_opra_trades_frame(
                args.symbol,
                start=args.start,
                end=args.end,
            )
            if args.with_opra
            else None
        )
        payload = structure_and_bars_to_pipeline_input(
            frame,
            symbol=args.symbol,
            timeframe=args.timeframe,
            as_of=_coerce_as_of_arg(args.as_of),
            periods_per_year=args.periods_per_year,
            cost_bps=args.cost_bps,
            structure_profile=args.structure_profile,
            dataset=args.dataset,
            schema=args.schema,
            start=args.start,
            end=args.end,
            trades=trades,
            opra_trades=opra_trades,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(payload, args.output, indent=2, sort_keys=False)
    counts = {k: len(payload["structure"][k]) for k in _STRUCTURE_KEYS}
    print(
        f"wrote {len(payload['bars'])} bar(s) + structure {counts} "
        f"for {args.symbol} ({args.timeframe}) to {args.output}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
