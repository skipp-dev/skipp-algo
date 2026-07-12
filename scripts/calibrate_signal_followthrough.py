#!/usr/bin/env python3
"""Calibrate breakout-signal follow-through from logged events + FMP 1-min bars.

Joins each signal event (``open_prep/signal_events.py`` output) to the symbol's
FMP 1-minute bars *after* the event and measures what actually happened next —
turning the A0/A1/A2 heuristic into empirical numbers:

    P(favorable move >= target within horizon | level, volume-ratio bucket)

plus the mean net return and the median favorable / adverse excursion. Two
methodology caveats: ``median_mae_pct`` is SIGNED entry-relative (bullish:
``(low-entry)/entry`` — usually negative), not the conventional positive MAE
magnitude; and events logged within ``--horizon-min`` of the end of the day's
bar series keep full weight despite their truncated window, so measured P is
biased slightly downward for late-session events.

Pure functions (``normalize_bars`` / ``compute_outcome`` / ``aggregate``) hold all
the maths and are unit-tested without network; only ``_fetch_bars`` and ``main``
touch FMP.

Usage::

    python scripts/calibrate_signal_followthrough.py \
        --events-dir artifacts/open_prep/signal_events \
        --horizon-min 60 --target-pct 0.5 --out calibration.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

# FMP intraday timestamps are naive US-Eastern (exchange local) strings.
_EXCHANGE_TZ = ZoneInfo("America/New_York")
_BULLISH = {"LONG", "B_UP", "UP"}


def _bar_epoch(raw_date: str) -> float | None:
    """Parse an FMP intraday ``date`` ("2026-07-08 09:35:00", exchange-local) to
    a UTC epoch. Returns None on unparseable input."""
    try:
        naive = datetime.strptime(raw_date.strip(), "%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None
    return naive.replace(tzinfo=_EXCHANGE_TZ).timestamp()


def normalize_bars(raw_bars: list[dict[str, Any]]) -> list[dict[str, float]]:
    """Return ``[{epoch, high, low, close}]`` sorted ascending by epoch.

    Isolates all timezone / shape handling so ``compute_outcome`` stays pure and
    testable on plain numbers.
    """
    out: list[dict[str, float]] = []
    for bar in raw_bars or []:
        epoch = _bar_epoch(str(bar.get("date", "")))
        if epoch is None:
            continue
        try:
            out.append({
                "epoch": epoch,
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda b: b["epoch"])
    return out


def vol_bucket(volume_ratio: float) -> str:
    """Bucket the entry volume ratio into fixed bands; 3.0/1.0 are the A0/A1 floors, 2.0/1.5 add resolution between."""
    if volume_ratio >= 3.0:
        return ">=3.0"
    if volume_ratio >= 2.0:
        return "2.0-3.0"
    if volume_ratio >= 1.5:
        return "1.5-2.0"
    if volume_ratio >= 1.0:
        return "1.0-1.5"
    return "<1.0"


def compute_outcome(
    event: dict[str, Any],
    bars: list[dict[str, float]],
    *,
    horizon_min: int,
    target_pct: float,
) -> dict[str, Any] | None:
    """Measure the post-event excursion. Pure. ``None`` if unusable.

    Direction-aware: for a bullish signal the *favorable* excursion is the high,
    the *adverse* is the low; inverted for a bearish one. Entry is the event
    price (the level the signal fired at).
    """
    entry = float(event.get("price") or 0.0)
    start = event.get("logged_epoch")
    if entry <= 0 or start is None:
        return None
    window = [b for b in bars if start < b["epoch"] <= start + horizon_min * 60]
    if not window:
        return None
    bullish = str(event.get("direction", "")).upper() in _BULLISH
    hi = max(b["high"] for b in window)
    lo = min(b["low"] for b in window)
    last = window[-1]["close"]
    if bullish:
        mfe = (hi - entry) / entry * 100.0
        mae = (lo - entry) / entry * 100.0
        net = (last - entry) / entry * 100.0
    else:
        mfe = (entry - lo) / entry * 100.0
        mae = (entry - hi) / entry * 100.0
        net = (entry - last) / entry * 100.0
    return {
        "symbol": event.get("symbol"),
        "level": str(event.get("level", "")),
        "vol_ratio": float(event.get("volume_ratio") or 0.0),
        "vol_bucket": vol_bucket(float(event.get("volume_ratio") or 0.0)),
        "n_bars": len(window),
        "mfe_pct": round(mfe, 4),
        "mae_pct": round(mae, 4),
        "net_pct": round(net, 4),
        "hit_target": bool(mfe >= target_pct),
    }


def aggregate(outcomes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Empirical follow-through table keyed by ``"<level>|<vol_bucket>"``."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for o in outcomes:
        groups.setdefault(f"{o['level']}|{o['vol_bucket']}", []).append(o)
    table: dict[str, dict[str, Any]] = {}
    for key, rows in sorted(groups.items()):
        n = len(rows)
        table[key] = {
            "n": n,
            "hit_target_rate": round(sum(r["hit_target"] for r in rows) / n, 4),
            "mean_net_pct": round(sum(r["net_pct"] for r in rows) / n, 4),
            "median_mfe_pct": round(median(r["mfe_pct"] for r in rows), 4),
            "median_mae_pct": round(median(r["mae_pct"] for r in rows), 4),
        }
    return table


def load_events(events_dir: Path, dates: list[str] | None) -> list[dict[str, Any]]:
    """Read signal-event JSONL rows, optionally restricted to ``dates``."""
    events: list[dict[str, Any]] = []
    for path in sorted(events_dir.glob("signal_events_*.jsonl")):
        day = path.stem.replace("signal_events_", "")
        if dates and day not in dates:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def _event_day(event: dict[str, Any]) -> date | None:
    epoch = event.get("logged_epoch")
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), UTC).astimezone(_EXCHANGE_TZ).date()


def _fetch_bars(client: Any, symbol: str, day: date) -> list[dict[str, float]]:
    return normalize_bars(client.get_intraday_chart(symbol, interval="1min", day=day))


def run(events: list[dict[str, Any]], client: Any, *, horizon_min: int, target_pct: float) -> dict[str, Any]:
    """Compute outcomes for every event (1-min bars cached per symbol-day)."""
    cache: dict[tuple[str, date], list[dict[str, float]]] = {}
    outcomes: list[dict[str, Any]] = []
    skipped = 0
    for event in events:
        symbol = str(event.get("symbol", "")).upper()
        day = _event_day(event)
        if not symbol or day is None:
            skipped += 1
            continue
        ck = (symbol, day)
        if ck not in cache:
            cache[ck] = _fetch_bars(client, symbol, day)
        outcome = compute_outcome(event, cache[ck], horizon_min=horizon_min, target_pct=target_pct)
        if outcome is None:
            skipped += 1
            continue
        outcomes.append(outcome)
    return {
        "params": {"horizon_min": horizon_min, "target_pct": target_pct},
        "n_events": len(events),
        "n_scored": len(outcomes),
        "n_skipped": skipped,
        "table": aggregate(outcomes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-dir", type=Path, default=Path("artifacts/open_prep/signal_events"))
    parser.add_argument("--dates", type=str, default="", help="comma list of YYYY-MM-DD to restrict to")
    parser.add_argument("--horizon-min", type=int, default=60)
    parser.add_argument("--target-pct", type=float, default=0.5)
    parser.add_argument("--out", type=Path, default=None, help="write calibration JSON here")
    args = parser.parse_args(argv)

    if not args.events_dir.is_dir():
        print(f"events dir not found: {args.events_dir}", file=sys.stderr)
        return 1
    dates = [d.strip() for d in args.dates.split(",") if d.strip()] or None
    events = load_events(args.events_dir, dates)
    if not events:
        print("no signal events found (is RT_SIGNAL_EVENT_LOG_DIR logging yet?)", file=sys.stderr)
        return 1

    from open_prep.macro import FMPClient
    result = run(events, FMPClient.from_env(), horizon_min=args.horizon_min, target_pct=args.target_pct)

    print(f"scored {result['n_scored']}/{result['n_events']} events "
          f"(skipped {result['n_skipped']}); horizon={args.horizon_min}m target={args.target_pct}%")
    print(f"{'level|vol_bucket':22} {'n':>5} {'hit%':>7} {'mean_net%':>10} {'med_MFE%':>9} {'med_MAE%':>9}")
    for key, row in result["table"].items():
        print(f"{key:22} {row['n']:>5} {row['hit_target_rate'] * 100:>6.1f}% "
              f"{row['mean_net_pct']:>10.3f} {row['median_mfe_pct']:>9.3f} {row['median_mae_pct']:>9.3f}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")  # ATOMIC-WRITE-EXEMPT: calibration research CLI writing to an operator-supplied --out path; not a production dataset with concurrent readers
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
