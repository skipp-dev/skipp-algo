"""Analyze the Benzinga WS↔REST shadow-latency JSONL and run the edge-sim.

Consumes the records written by ``scripts/bz_ws_shadow_recorder.py`` and
answers two questions:

1. **Latency gap** — distribution of ``ws_rest_delta_s`` (how much earlier WS
   delivered a headline than the REST poll path). This alone decides whether
   there is *any* latency to exploit.

2. **Edge-sim** — for *catalyst* headlines (``catalyst_score`` above a
   threshold) where WS led REST, the price move on the headline's ticker over
   the ``[t_ws, t_rest]`` window. That move is the slice a WS-driven upgrade
   would have front-run and the REST path missed — the €-proxy of the edge.

Price data comes from Databento intraday (``ohlcv-1s``, the market-data
primary — no FMP volume). The pure aggregation core takes an injectable
price-fetch callable so it is unit-testable without a Databento client.

The ``t_x`` column is carried through untouched: once an X event matcher
populates it, the same latency/edge summaries extend to ``t_x`` with no
schema change.

Usage
-----
    PYTHONPATH=. python scripts/analyze_bz_ws_latency.py \\
        artifacts/bz_ws_shadow/latency_20260727.jsonl --min-catalyst 0.33
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("analyze_bz_ws_latency")

# A price-fetch resolves (symbol, t_start_epoch, t_end_epoch) -> signed move
# fraction over the window, or None when no intraday data covers it.
PriceFetch = Callable[[str, float, float], float | None]


def load_records(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of dicts (skips blank lines)."""
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Nearest-rank percentile on a pre-sorted list (q in [0, 1])."""
    if not sorted_vals:
        return float("nan")
    if q <= 0:
        return sorted_vals[0]
    if q >= 1:
        return sorted_vals[-1]
    idx = min(len(sorted_vals) - 1, round(q * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def _dist(values: list[float]) -> dict[str, Any]:
    """Robust distribution summary (percentiles, not a parametric fit)."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "min": vals[0],
        "p25": _percentile(vals, 0.25),
        "median": _percentile(vals, 0.50),
        "p75": _percentile(vals, 0.75),
        "p90": _percentile(vals, 0.90),
        "max": vals[-1],
    }


def summarize_latency(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the WS↔REST latency gap (+ TradingView) across all records.

    TradingView is a REST-poll source like Benzinga REST, so ``rest_tv_delta_s``
    (poll-vs-poll) is the fair comparison; ``ws_tv_delta_s`` contrasts TV against
    the WS push path. In both, a positive value means the named Benzinga channel
    arrived earlier than TradingView.
    """
    both = [r for r in records if r.get("ws_rest_delta_s") is not None]
    deltas = [float(r["ws_rest_delta_s"]) for r in both]
    ws_earlier = sum(1 for d in deltas if d > 0)
    tv_matched = sum(1 for r in records if r.get("t_tv") is not None)
    return {
        "records_total": len(records),
        "records_ws_and_rest": len(both),
        "ws_earlier_count": ws_earlier,
        "ws_earlier_share": (ws_earlier / len(both)) if both else 0.0,
        "ws_rest_delta_s": _dist(deltas),
        "pub_ws_delta_s": _dist(
            [float(r["pub_ws_delta_s"]) for r in records
             if r.get("pub_ws_delta_s") is not None]
        ),
        "records_with_tv": tv_matched,
        "tv_matched_share": (tv_matched / len(records)) if records else 0.0,
        "ws_tv_delta_s": _dist(
            [float(r["ws_tv_delta_s"]) for r in records
             if r.get("ws_tv_delta_s") is not None]
        ),
        "rest_tv_delta_s": _dist(
            [float(r["rest_tv_delta_s"]) for r in records
             if r.get("rest_tv_delta_s") is not None]
        ),
    }


def select_catalyst_windows(
    records: list[dict[str, Any]],
    *,
    min_catalyst: float,
    require_ws_advantage: bool = True,
) -> list[dict[str, Any]]:
    """Return catalyst records eligible for the price-window edge-sim."""
    out = []
    for r in records:
        if float(r.get("catalyst_score", 0.0)) < min_catalyst:
            continue
        if r.get("t_ws") is None or r.get("t_rest") is None:
            continue
        if not r.get("tickers"):
            continue
        if require_ws_advantage and float(r.get("ws_rest_delta_s") or 0.0) <= 0:
            continue
        out.append(r)
    return out


def attach_price_moves(
    windows: list[dict[str, Any]], price_fetch: PriceFetch
) -> list[dict[str, Any]]:
    """Attach ``window_move_pct`` to each catalyst window via *price_fetch*.

    Uses the record's first ticker and the ``[t_ws, t_rest]`` window. Records
    with no intraday coverage get ``window_move_pct = None``.
    """
    enriched = []
    for r in windows:
        symbol = r["tickers"][0]
        move = price_fetch(symbol, float(r["t_ws"]), float(r["t_rest"]))
        enriched.append({**r, "edge_symbol": symbol, "window_move_pct": move})
    return enriched


def summarize_edge(windows_with_moves: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the edge-sim: how big are the front-run-able moves?"""
    moves = [
        abs(float(r["window_move_pct"]))
        for r in windows_with_moves
        if r.get("window_move_pct") is not None
    ]
    return {
        "catalyst_windows": len(windows_with_moves),
        "windows_with_price": len(moves),
        "abs_move_pct": _dist(moves),
    }


# ── Databento intraday price fetch (I/O shim) ───────────────────────


def _make_databento_price_fetch(pad_seconds: float = 2.0) -> PriceFetch:
    """Build a ``PriceFetch`` backed by Databento ``ohlcv-1s`` bars.

    The window is padded by ``pad_seconds`` on each side so a sub-second
    ``[t_ws, t_rest]`` still brackets at least one bar. The move is the last
    close minus the first open in the window, as a signed fraction.
    """
    import os
    from datetime import UTC, datetime

    key = os.getenv("DATABENTO_API_KEY", "")
    if not key:
        raise RuntimeError("DATABENTO_API_KEY missing — cannot run the price edge-sim")

    from databento_client import _make_databento_client
    from databento_dataset_policy import DatasetMode, DatasetRole, resolve_dataset

    client = _make_databento_client(key)
    dataset = resolve_dataset(
        DatasetRole.EQUITY_INTRADAY_PARITY,
        requested_dataset="EQUS.MINI",
        schema="ohlcv-1s",
        mode=DatasetMode.HISTORICAL,
    )

    def _fetch(symbol: str, t0: float, t1: float) -> float | None:
        start = datetime.fromtimestamp(t0 - pad_seconds, tz=UTC)
        end = datetime.fromtimestamp(t1 + pad_seconds, tz=UTC)
        try:
            data = client.timeseries.get_range(
                dataset=dataset,
                schema="ohlcv-1s",
                symbols=[symbol],
                start=start,
                end=end,
            )
            df = data.to_df()
        except Exception:  # pragma: no cover - network/entitlement resilience
            logger.debug("databento fetch failed for %s", symbol, exc_info=True)
            return None
        if df is None or len(df) == 0:
            return None
        first_open = float(df.iloc[0]["open"])
        # BAR-CLOSE-EXEMPT: offline analyzer over a [t_ws, t_rest] window that
        # is always historical by run time, so every ohlcv-1s bar here is
        # closed — no live/unclosed-bar hazard the guard protects against.
        last_close = float(df.iloc[-1]["close"])
        if first_open <= 0:
            return None
        return (last_close - first_open) / first_open

    return _fetch


def run_analysis(
    path: Path, *, min_catalyst: float, price_fetch: PriceFetch | None
) -> dict[str, Any]:
    """Full analysis: latency summary + (optional) price edge-sim."""
    records = load_records(path)
    report: dict[str, Any] = {"source": str(path), "latency": summarize_latency(records)}
    windows = select_catalyst_windows(records, min_catalyst=min_catalyst)
    report["catalyst_windows_selected"] = len(windows)
    if price_fetch is not None:
        enriched = attach_price_moves(windows, price_fetch)
        report["edge_sim"] = summarize_edge(enriched)
    else:
        report["edge_sim"] = {"skipped": "no price fetch (pass --with-prices)"}
    return report


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Analyze Benzinga WS↔REST shadow latency.")
    p.add_argument("jsonl", type=Path, help="recorder output JSONL")
    p.add_argument("--min-catalyst", type=float, default=0.33,
                   help="catalyst_score threshold for the edge-sim")
    p.add_argument("--with-prices", action="store_true",
                   help="run the Databento intraday price edge-sim (needs DATABENTO_API_KEY)")
    args = p.parse_args(argv)

    fetch = _make_databento_price_fetch() if args.with_prices else None
    report = run_analysis(args.jsonl, min_catalyst=args.min_catalyst, price_fetch=fetch)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
