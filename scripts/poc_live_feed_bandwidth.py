"""
PoC: db.Live() EQUS.MINI ohlcv-1m — Bandwidth & RAM Measurement
=================================================================
Replays 5 minutes of market data for 5 tickers (via intraday-replay),
accumulates bars in the RAM dict that a real daemon would keep, and
prints extrapolated stats for the full 6,889-ticker universe.

Usage:
    .venv/bin/python3 scripts/poc_live_feed_bandwidth.py

The script replays last Friday's data so it works outside market hours.
Runs for 5 min of replay-time (not wall-clock; replay goes much faster).
"""

from __future__ import annotations

import datetime
import os
import sys
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path

import psutil

# ---------------------------------------------------------------------------
# Load API key from .env
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parent.parent
_env_path = _repo_root / ".env"
if not _env_path.exists():
    sys.exit("ERROR: .env not found in repo root")

_api_key: str = ""
for _line in _env_path.read_text(encoding="utf-8").splitlines():
    if _line.startswith("DATABENTO_API_KEY"):
        _api_key = _line.split("=", 1)[1].strip()
        break
if not _api_key:
    sys.exit("ERROR: DATABENTO_API_KEY not found in .env")

import databento as db  # noqa: E402 — after sys.path check


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOLS = ["AAPL", "NVDA", "META", "MSFT", "TSLA"]
DATASET = "EQUS.MINI"
SCHEMA = "ohlcv-1m"
UNIVERSE_SIZE = 6_889

# Replay today's session from open (13:30 UTC = NYSE open).
# We stream live and stop after MAX_RECORDS records (or 60s wall-clock, whichever comes first).
# ohlcv-1m bars only emit at bar-close, so during live market we expect 1 bar/min/ticker.
REPLAY_START = datetime.datetime(2026, 6, 14, 0, 0, tzinfo=datetime.timezone.utc)  # earliest available
MAX_RECORDS = 100   # stop after this many data records (excluding system records)
WALL_TIMEOUT_S = 8   # stop after this many wall-clock seconds regardless (short for pre-market runs)

# Approximate DBN ohlcv-1m record size in bytes (fixed: 64-byte header + 40-byte body)
DBN_OHLCV_RECORD_BYTES = 104


# ---------------------------------------------------------------------------
# RAM dict that the real daemon would maintain
# {symbol: [{"open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "ts": ...}]}
# ---------------------------------------------------------------------------
bar_cache: dict[str, list[dict]] = defaultdict(list)

counters = {
    "records": 0,
    "bytes_approx": 0,
}


def _on_record(record: object) -> None:
    """Callback invoked for every record received from the live feed."""
    counters["records"] += 1
    counters["bytes_approx"] += DBN_OHLCV_RECORD_BYTES

    # Simulate what the daemon stores
    sym = getattr(record, "hd", None)
    if sym is None:
        return
    raw_sym = getattr(record, "instrument_id", 0)  # will be resolved via symmap

    # Store the OHLCV bar
    bar_cache[raw_sym].append(
        {
            "open": getattr(record, "open", 0) / 1e9,
            "high": getattr(record, "high", 0) / 1e9,
            "low": getattr(record, "low", 0) / 1e9,
            "close": getattr(record, "close", 0) / 1e9,
            "volume": getattr(record, "volume", 0),
            "ts_event": getattr(record.hd, "ts_event", 0),
        }
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    proc = psutil.Process(os.getpid())
    ram_before_mb = proc.memory_info().rss / 1024 / 1024

    tracemalloc.start()
    t_start = time.monotonic()

    print(f"[PoC] Connecting to {DATASET} {SCHEMA} | symbols: {SYMBOLS}")
    print(f"[PoC] Replaying from {REPLAY_START.isoformat()} | stopping at {MAX_RECORDS} records or {WALL_TIMEOUT_S}s")
    print()

    client = db.Live(key=_api_key)

    # Subscribe with intraday replay from the earliest available point
    client.subscribe(
        dataset=DATASET,
        schema=SCHEMA,
        symbols=SYMBOLS,
        start=REPLAY_START,
    )

    deadline = time.monotonic() + WALL_TIMEOUT_S
    data_records = 0
    try:
        for record in client:
            # Skip system records (SessionEnd, SymbolMapping, etc.) — only count data
            rec_name = type(record).__name__
            if rec_name not in ("OhlcvMsg", "Ohlcv1M", "OhlcvMsg"):
                # still call callback but mark as system record
                if "Ohlcv" in rec_name or "Bar" in rec_name:
                    _on_record(record)
                    data_records += 1
                # else: system record, skip
            else:
                _on_record(record)
                data_records += 1

            if data_records >= MAX_RECORDS:
                print(f"[PoC] Reached {MAX_RECORDS} data records — stopping.")
                break
            if time.monotonic() > deadline:
                print(f"[PoC] Wall-clock timeout ({WALL_TIMEOUT_S}s) — stopping.")
                break
    except db.BentoError as exc:
        print(f"[PoC] BentoError: {exc}")
    except KeyboardInterrupt:
        print("[PoC] Interrupted by user.")
    finally:
        client.stop()

    t_elapsed = time.monotonic() - t_start

    # RAM measurement
    ram_after_mb = proc.memory_info().rss / 1024 / 1024
    ram_delta_mb = ram_after_mb - ram_before_mb
    _, peak_tracemalloc_kb = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # ---------------------------------------------------------------------------
    # Stats
    # ---------------------------------------------------------------------------
    n_rec = counters["records"]
    n_bytes = counters["bytes_approx"]
    n_symbols_with_data = len(bar_cache)
    total_bars_stored = sum(len(v) for v in bar_cache.values())

    print("=" * 60)
    print("RESULTS — 5-ticker replay")
    print("=" * 60)
    print(f"  Wall-clock duration      : {t_elapsed:.1f}s")
    print(f"  Records received         : {n_rec}")
    print(f"  Symbols with bars        : {n_symbols_with_data}")
    print(f"  Total bars stored in RAM : {total_bars_stored}")
    print(f"  Approx bytes (DBN wire)  : {n_bytes:,} bytes  ({n_bytes/1024:.1f} KB)")
    print(f"  RAM delta (RSS)          : {ram_delta_mb:+.1f} MB")
    print(f"  Peak tracemalloc         : {peak_tracemalloc_kb/1024:.1f} MB")
    print()

    # ---------------------------------------------------------------------------
    # Extrapolation to full universe
    # ---------------------------------------------------------------------------
    scale = UNIVERSE_SIZE / max(len(SYMBOLS), 1)
    print("=" * 60)
    print(f"EXTRAPOLATION → {UNIVERSE_SIZE} tickers")
    print("=" * 60)

    if n_rec > 0:
        bytes_per_ticker_per_window = n_bytes / len(SYMBOLS)
        bytes_full = bytes_per_ticker_per_window * UNIVERSE_SIZE
        bars_per_ticker = total_bars_stored / max(n_symbols_with_data, 1)
        bars_full = bars_per_ticker * UNIVERSE_SIZE

        bar_ram_kb = bars_full * 200 / 1024
        bar_ram_60min_mb = (bars_full * (60 / max(bars_per_ticker, 1)) * 200) / 1024 / 1024

        refreshes_per_day = 13 * 2  # 6.5h × 2 (30-min interval)
        daily_gb = bytes_full * refreshes_per_day / 1024 / 1024 / 1024

        print(f"  Observed wire bytes (5 tickers) : {n_bytes:,} bytes")
        print(f"  Wire bytes full universe        : {bytes_full/1024/1024:.2f} MB per cycle")
        print(f"  Bars per cycle (full universe)  : {bars_full:.0f}")
        print(f"  Estimated RAM (bars in window)  : {bar_ram_kb:.0f} KB")
        print(f"  Estimated RAM (last 60-min)     : {bar_ram_60min_mb:.1f} MB")
        print()
        print(f"  Daily total (30-min refresh)    : {daily_gb:.3f} GB/day")
        print(f"  Monthly (22 trading days)       : {daily_gb*22:.2f} GB/month")
    else:
        print("  No live records received (market closed or pre-open).")
        print(f"  Replay started from: {REPLAY_START}")
        print("  Falling back to analytical calculation based on fixed DBN record size.\n")

        # -----------------------------------------------------------------
        # Analytical calculation
        # DBN ohlcv-1m record: 104 bytes (fixed, 64-byte header + 40-byte body)
        # Streaming model: daemon receives 1 bar per ticker per minute continuously
        # -----------------------------------------------------------------
        bars_per_min = UNIVERSE_SIZE          # 1 bar/min per ticker
        wire_per_min_kb = bars_per_min * DBN_OHLCV_RECORD_BYTES / 1024
        wire_per_session_mb = wire_per_min_kb * 390 / 1024  # 390 min = 6.5h session

        # RAM: daemon keeps last 60 min of bars as Python dicts (~200 bytes each)
        python_dict_bytes = 200
        ram_60min_mb = UNIVERSE_SIZE * 60 * python_dict_bytes / 1024 / 1024
        # + overhead for numpy/pandas if we keep a rolling DataFrame per ticker
        # rough estimate: 6,889 × 60 bars × ~80 bytes (numpy float64×5 cols) = 33 MB
        ram_numpy_mb = UNIVERSE_SIZE * 60 * 5 * 8 / 1024 / 1024  # 5 OHLCV columns × float64

        print(f"  DBN record size (ohlcv-1m)      : {DBN_OHLCV_RECORD_BYTES} bytes (fixed)")
        print(f"  Wire bandwidth                  : {wire_per_min_kb:.0f} KB/min  =  {wire_per_min_kb*60/1024:.1f} MB/hour")
        print(f"  Wire per full session (6.5h)    : {wire_per_session_mb:.1f} MB/day")
        print(f"  Wire per month (22 days)        : {wire_per_session_mb*22/1024:.2f} GB/month")
        print()
        print(f"  RAM — last 60-min bars (dicts)  : {ram_60min_mb:.0f} MB")
        print(f"  RAM — last 60-min bars (numpy)  : {ram_numpy_mb:.0f} MB  (more efficient)")
        print(f"  → Railway 512 MB tier           : {'✓ fits' if ram_numpy_mb + 80 < 512 else '✗ too large'}")
        print(f"  → Railway 1 GB tier ($12/mo)    : {'✓ fits' if ram_numpy_mb + 80 < 1024 else '✗ too large'}")
        print()
        print("  NOTE: Run during NYSE hours (13:30–20:00 UTC Mon–Fri) for live measurement.")

    print()
    print("[PoC] Done.")


if __name__ == "__main__":
    main()
