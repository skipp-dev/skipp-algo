"""Tick-level ``trades`` pull for the Hayashi-Yoshida cross-asset lead-lag build.

Scope: ``docs/governance/tick_hayashi_yoshida_scope.md`` step 1 (tick data
layer). The existing :func:`scripts.pull_databento_edge_input.normalize_trades_frame`
floors every trade timestamp to epoch **seconds** (``// pd.Timedelta(seconds=1)``)
because the ADR-0016 signed-volume path aggregates into bars where second
resolution is plenty. The Hayashi-Yoshida estimator is the opposite case: its
whole value is sub-second async timing, so flooring to seconds would erase the
exact signal it exists to measure.

This module therefore keeps a **nanosecond** integer clock and the raw print
price only — the minimal ``(ts_ns, price)`` series HY consumes — written to one
Parquet file per symbol. Two halves mirror the sibling module: a pure,
unit-testable :func:`normalize_tick_trades_frame` and an impure, credential-bound
:func:`fetch_tick_trades_frame` that is never tested against the live API.

It fabricates nothing: every row traces to a Databento ``trades`` print. An
empty response raises loudly rather than writing a vacuous file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Databento ``trades`` schema on the equity venue (e.g. XNAS.ITCH). One record
# per print carrying price/size/side; the ns event clock is ``ts_event``.
_TRADES_SCHEMA = "trades"
_TIMESTAMP_CANDIDATES = ("ts_event", "ts_recv", "ts", "timestamp", "index")
_PRICE_COL = "price"


def normalize_tick_trades_frame(raw: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    """Coerce a raw Databento ``trades`` frame into the HY tick schema.

    Returns a frame with columns ``symbol, ts_ns, price`` where ``ts_ns`` is the
    integer **nanosecond** epoch of each print (NOT floored to seconds — that is
    the entire point versus the ADR-0016 path). A ``DatetimeIndex`` (the default
    ``store.to_df()`` shape) or any known ``ts_*`` column is accepted; an
    unrecognised frame raises rather than guessing. Rows are sorted by
    ``ts_ns`` so the series is monotone for the estimator.
    """
    if raw.empty:
        raise ValueError("Databento trades frame is empty; nothing to normalize")

    frame = raw.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        ts = pd.to_datetime(frame.index, utc=True)
    else:
        ts_col = next((c for c in _TIMESTAMP_CANDIDATES if c in frame.columns), "")
        if not ts_col:
            raise ValueError(
                "no timestamp column found in Databento trades frame; expected a "
                f"DatetimeIndex or one of {_TIMESTAMP_CANDIDATES}"
            )
        ts = pd.to_datetime(frame[ts_col], utc=True)

    if _PRICE_COL not in frame.columns:
        raise ValueError(f"Databento trades frame missing required column: {_PRICE_COL!r}")

    # ``asi8`` is the int64 ns-since-epoch view of a UTC DatetimeIndex; this is
    # the nanosecond precision the HY estimator depends on.
    ts_ns = pd.DatetimeIndex(ts).asi8
    out = pd.DataFrame(
        {
            "ts_ns": pd.array(ts_ns, dtype="int64"),
            "price": pd.to_numeric(frame[_PRICE_COL], errors="coerce").to_numpy(),
        }
    )
    out["symbol"] = str(symbol).strip().upper()
    out = out.dropna(subset=["price"])
    # Drop the int64 sentinel for NaT timestamps (asi8 maps NaT -> -2**63).
    out = out[out["ts_ns"] > 0]
    if out.empty:
        raise ValueError("Databento trades frame has no usable rows after coercion")
    return (
        out[["symbol", "ts_ns", "price"]]
        .sort_values("ts_ns")
        .reset_index(drop=True)
    )


def fetch_tick_trades_frame(
    symbol: str,
    *,
    dataset: str,
    start: str,
    end: str,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch a raw ``trades`` frame and normalize to the HY tick schema.

    Credential-bound (reads ``DATABENTO_API_KEY`` when ``api_key`` is omitted)
    and never unit tested against the live API; the pure
    :func:`normalize_tick_trades_frame` carries the tested contract.
    """
    from databento_client import (
        _databento_get_range_with_retry,
        _make_databento_client,
    )

    client = _make_databento_client(api_key)
    store = _databento_get_range_with_retry(
        client,
        context="pull_tick_trades",
        dataset=dataset,
        symbols=[str(symbol).strip().upper()],
        schema=_TRADES_SCHEMA,
        start=start,
        end=end,
    )
    frame = store.to_df()
    return normalize_tick_trades_frame(frame, symbol=symbol)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull tick-level trades (ns precision) for the HY lead-lag build."
    )
    parser.add_argument("--symbol", required=True, help="Instrument symbol, e.g. SPY.")
    parser.add_argument("--dataset", required=True, help="Databento dataset, e.g. XNAS.ITCH.")
    parser.add_argument("--start", required=True, help="Inclusive start (ISO date/datetime).")
    parser.add_argument("--end", required=True, help="Exclusive end (ISO date/datetime).")
    parser.add_argument("--output", required=True, help="Output Parquet path.")
    args = parser.parse_args(argv)

    frame = fetch_tick_trades_frame(
        args.symbol,
        dataset=args.dataset,
        start=args.start,
        end=args.end,
    )
    out_path = Path(args.output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_path, index=False)
    # BAR-CLOSE-EXEMPT: CLI coverage summary only; `frame` is sorted ascending by
    # ts_ns and these reads just report the pulled span, not a bar-close derivation.
    span_ns = int(frame["ts_ns"].iloc[-1] - frame["ts_ns"].iloc[0])
    print(
        f"{args.symbol}: {len(frame):,} ticks -> {out_path} "
        f"(span {span_ns / 1e9 / 86400:.1f} days)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
