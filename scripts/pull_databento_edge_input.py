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
    _prepare_symbol_resampled_bars,
    build_explicit_structure_from_bars,
)
from scripts.smc_atomic_write import atomic_write_json

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


def _resampled_bars_payload(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict[str, float]]:
    """The resampled timeframe bars the structure events anchor on.

    Reuses the structure module's own resampler so the emitted ``bars`` list is
    byte-for-byte the frame the detector indexed — guaranteeing the pipeline's
    anchor/lookahead arithmetic matches the live scorer.
    """
    resampled, _canonical_tf = _prepare_symbol_resampled_bars(df, symbol, timeframe)
    if resampled.empty:
        return []
    return [
        {
            "timestamp": float(row.timestamp),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
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
) -> dict[str, Any]:
    """Build a :mod:`scripts.run_edge_pipeline` input payload from real bars.

    ``df`` is a base-granularity OHLCV frame (output of
    :func:`normalize_ohlcv_frame`). ``as_of`` arms the EV-04 point-in-time
    guard; when ``None`` it defaults to the last resampled bar's timestamp so
    the guard is always armed against the data's own horizon.

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
        payload = structure_and_bars_to_pipeline_input(
            frame,
            symbol=args.symbol,
            timeframe=args.timeframe,
            as_of=_coerce_as_of_arg(args.as_of),
            periods_per_year=args.periods_per_year,
            cost_bps=args.cost_bps,
            structure_profile=args.structure_profile,
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
