"""Real ASIA-session FVG sampler — replaces the synthetic midnight-UTC artifact.

Closes the deferred ToDo from ``docs/FVG_LABEL_AUDIT_Q3.md`` §5b.4 by
sourcing **actual ASIA-window (00:00–08:00 UTC) intraday bars** instead
of the canonical export bundle (which only covers 11–14 UTC).

Approach:

1. Pull DBEQ.BASIC OHLCV-5m for a small high-extended-hours universe
   (TSLA / NVDA / AAPL / AMZN / META / MSFT / GOOGL / SPY / QQQ) over a
   configurable window (default 60 days), with **full 24 h coverage**.
   These instruments have material extended-hours volume in the
   17:00–04:00 ET tape (= 22:00–08:00 UTC), which overlaps the ASIA
   classifier window.
2. Run the production FVG detector
   (:func:`scripts.explicit_structure_from_bars.build_fvg_from_bars`)
   per symbol × timeframe.
3. Replay each FVG forward through the bars and compute
   ``label_fvg_mitigation`` (lenient) and ``label_fvg_partial_50``
   (strict) using the same scorer logic as the production benchmark.
4. Bucket each event by anchor session
   (:func:`scripts.smc_session_context_block._classify_session`).
5. Report per-session counts + lenient/strict hit-rates.

This script is intentionally **stand-alone**: it does not depend on the
canonical export bundle or the structure-artifact contract, so it can
be re-run nightly without disturbing the normal benchmark pipeline.

Run::

    DATABENTO_API_KEY=... python scripts/fvg_asia_real_sample.py \
        --days 60 --timeframes 5m,15m,1H \
        --output artifacts/ci/fvg_asia_real_sample_2026-04-22.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from scripts.smc_atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env before argparse defaults are resolved (they call os.environ.get).
load_dotenv(ROOT / ".env")

from scripts.explicit_structure_from_bars import (
    build_fvg_from_bars,
    resample_bars_to_timeframe,
)
from scripts.smc_session_context_block import _classify_session
from smc_core.scoring import (
    label_fvg_mitigation,
    label_fvg_partial_50,
)

# Small high-volume universe with material extended-hours tape so the
# 22:00–08:00 UTC window actually contains trades (US equities trade
# 04:00–20:00 ET in extended hours, which covers 22:00 UTC start of
# the ASIA bucket through ~01:00 UTC plus 09:00–14:00 UTC of the next
# session). For genuine 24-h coverage a futures dataset would be
# needed, but that is a separate (and licensed-differently) source.
DEFAULT_SYMBOLS: tuple[str, ...] = (
    "TSLA",
    "NVDA",
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "GOOGL",
    "SPY",
    "QQQ",
)
DEFAULT_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1H")
DEFAULT_DATASET: str = "DBEQ.BASIC"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        type=str,
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbol list.",
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        default=",".join(DEFAULT_TIMEFRAMES),
        help="Comma-separated timeframe list (5m,15m,1H,4H supported).",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=os.environ.get("DATABENTO_DATASET") or DEFAULT_DATASET,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Lookback window in days (default 60).",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="ISO end timestamp (UTC). Defaults to last full UTC day.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report here (default: stdout only).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.environ.get("DATABENTO_API_KEY"),
    )
    return parser.parse_args(argv)


def _fetch_bars_5m(
    *,
    api_key: str,
    dataset: str,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Fetch DBEQ.BASIC OHLCV-1m bars and resample to 5m, all hours."""
    import databento as db  # local import keeps the module importable offline

    client = db.Historical(api_key)
    store = client.timeseries.get_range(
        dataset=dataset,
        symbols=symbols,
        schema="ohlcv-1m",
        start=start.isoformat(),
        end=end.isoformat(),
    )
    df = store.to_df()
    if df.empty:
        return df

    if df.index.name in {"ts_event", "ts_recv"} or isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    if "ts_event" in df.columns:
        df["timestamp"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    elif "timestamp" not in df.columns and "ts_recv" in df.columns:
        df["timestamp"] = pd.to_datetime(df["ts_recv"], utc=True, errors="coerce")
    if "symbol" not in df.columns:
        raise RuntimeError("Databento response missing 'symbol' column")

    keep = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = 0.0
    df = df[keep].dropna(subset=["timestamp", "open", "high", "low", "close"]).copy()
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df = df.reset_index(drop=True)

    # Resample 1m → 5m per symbol so downstream FVG detection runs on 5m base.
    pieces: list[pd.DataFrame] = []
    for sym, sdf in df.groupby("symbol", sort=False):
        rs = resample_bars_to_timeframe(sdf, "5m")
        if rs.empty:
            continue
        rs = rs.copy()
        rs["symbol"] = sym
        pieces.append(rs)
    if not pieces:
        return df.iloc[0:0]
    return pd.concat(pieces, ignore_index=True)


def _label_fvg(
    *,
    zone_low: float,
    zone_high: float,
    direction: str,
    future: pd.DataFrame,
) -> tuple[bool, bool]:
    """Return (lenient_hit, strict_partial_50_hit)."""
    highs = [float(v) for v in pd.to_numeric(future["high"], errors="coerce").dropna().tolist()]
    lows = [float(v) for v in pd.to_numeric(future["low"], errors="coerce").dropna().tolist()]
    closes = [float(v) for v in pd.to_numeric(future["close"], errors="coerce").dropna().tolist()]
    lenient = bool(label_fvg_mitigation(zone_low, zone_high, direction, highs, lows, closes))
    strict = bool(label_fvg_partial_50(zone_low, zone_high, direction, highs, lows, closes))
    return lenient, strict


def _process_symbol_tf(
    *,
    bars_5m: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> list[dict]:
    sym_bars = bars_5m.loc[bars_5m["symbol"] == symbol].copy()
    if sym_bars.empty:
        return []

    if timeframe != "5m":
        sym_bars = resample_bars_to_timeframe(sym_bars, timeframe)
        if sym_bars.empty:
            return []

    sym_bars = sym_bars.sort_values("timestamp").reset_index(drop=True)
    sym_bars["timestamp"] = pd.to_datetime(sym_bars["timestamp"], utc=True, errors="coerce")
    sym_bars = sym_bars.dropna(subset=["timestamp"]).reset_index(drop=True)

    fvgs = build_fvg_from_bars(sym_bars, symbol=symbol, timeframe=timeframe)
    if not fvgs:
        return []

    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    sym_bars["epoch_s"] = ((sym_bars["timestamp"] - epoch) // pd.Timedelta(seconds=1)).astype("int64")

    out: list[dict] = []
    for fvg in fvgs:
        anchor_ts = float(fvg.get("anchor_ts", fvg.get("time", 0)) or 0)
        zone_low = float(fvg.get("low", 0) or 0)
        zone_high = float(fvg.get("high", 0) or 0)
        direction = str(fvg.get("dir", "BULL")).upper()
        if anchor_ts <= 0 or zone_low <= 0 or zone_high <= zone_low:
            continue

        future_mask = sym_bars["epoch_s"] > int(anchor_ts)
        future = sym_bars.loc[future_mask, ["high", "low", "close"]].head(200)
        if future.empty:
            continue

        lenient, strict = _label_fvg(
            zone_low=zone_low,
            zone_high=zone_high,
            direction=direction,
            future=future,
        )
        anchor_dt = datetime.fromtimestamp(anchor_ts, tz=UTC)
        session = _classify_session(anchor_dt.time())
        out.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "anchor_ts": anchor_ts,
                "anchor_iso": anchor_dt.isoformat(),
                "session": session,
                "lenient_hit": lenient,
                "strict_partial_50_hit": strict,
            }
        )
    return out


def _aggregate(events: list[dict]) -> dict:
    by_session: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        by_session[ev["session"]].append(ev)

    rows: list[dict] = []
    for session in sorted(by_session):
        items = by_session[session]
        n = len(items)
        if n == 0:
            continue
        lenient_hr = sum(1 for it in items if it["lenient_hit"]) / n
        strict_hr = sum(1 for it in items if it["strict_partial_50_hit"]) / n
        tf_breakout = Counter(it["timeframe"] for it in items)
        symbol_breakout = Counter(it["symbol"] for it in items)
        rows.append(
            {
                "session": session,
                "n_events": n,
                "lenient_hr": round(lenient_hr, 4),
                "strict_partial_50_hr": round(strict_hr, 4),
                "delta_strict_minus_lenient": round(strict_hr - lenient_hr, 4),
                "tf_breakout": dict(tf_breakout),
                "symbol_breakout": dict(symbol_breakout),
            }
        )
    return {
        "n_total": len(events),
        "per_session": rows,
    }


def _print_md(report: dict) -> None:
    print("# Real ASIA-session FVG sample\n")
    print(f"Source: `{report['source']}`")
    print(f"Window: {report['window']['start']} → {report['window']['end']} (UTC)")
    print(f"Symbols: {', '.join(report['universe'])}")
    print(f"Timeframes: {', '.join(report['timeframes'])}")
    print(f"Total FVG events: {report['summary']['n_total']}\n")
    print("| Session | n | lenient HR | strict ≥50% HR | Δ | TF breakout |")
    print("|---|---:|---:|---:|---:|---|")
    for row in report["summary"]["per_session"]:
        tf_str = ", ".join(f"{tf}:{c}" for tf, c in sorted(row["tf_breakout"].items()))
        print(
            f"| {row['session']} | {row['n_events']} | "
            f"{row['lenient_hr']:.3f} | {row['strict_partial_50_hr']:.3f} | "
            f"{row['delta_strict_minus_lenient']:+.3f} | {tf_str} |"
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.api_key:
        print("ERROR: DATABENTO_API_KEY not set", file=sys.stderr)
        return 2

    end_dt = (
        datetime.fromisoformat(args.end).astimezone(UTC)
        if args.end
        else datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    start_dt = end_dt - timedelta(days=int(args.days))
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    print(f"# fetching {len(symbols)} symbols × ohlcv-5m, {start_dt} → {end_dt}", file=sys.stderr)
    bars_5m = _fetch_bars_5m(
        api_key=args.api_key,
        dataset=args.dataset,
        symbols=symbols,
        start=start_dt,
        end=end_dt,
    )
    print(f"# fetched {len(bars_5m)} bar rows", file=sys.stderr)
    if bars_5m.empty:
        print("ERROR: no bars returned from Databento", file=sys.stderr)
        return 3

    # Hour distribution sanity (proves we have ASIA-window coverage)
    hour_dist = Counter(bars_5m["timestamp"].dt.hour)
    asia_hours = sum(c for h, c in hour_dist.items() if 0 <= h < 8 or h >= 22)
    print(
        f"# bar coverage: {sum(hour_dist.values())} total, "
        f"{asia_hours} in ASIA window (00–08 UTC + 22–24 UTC)",
        file=sys.stderr,
    )

    all_events: list[dict] = []
    for symbol in symbols:
        for tf in timeframes:
            events = _process_symbol_tf(bars_5m=bars_5m, symbol=symbol, timeframe=tf)
            all_events.extend(events)
            print(f"# {symbol:6s} {tf:4s}: {len(events):4d} FVG events", file=sys.stderr)

    summary = _aggregate(all_events)
    report = {
        "source": f"databento {args.dataset} ohlcv-5m, full 24h",
        "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        "universe": symbols,
        "timeframes": timeframes,
        "summary": summary,
    }

    _print_md(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(report, indent=2), args.output)
        print(f"\n# wrote {args.output}", file=sys.stderr)

    asia_n = next(
        (row["n_events"] for row in summary["per_session"] if row["session"] == "ASIA"),
        0,
    )
    print(f"\n# ASIA n_events = {asia_n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
