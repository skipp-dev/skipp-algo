"""In-process request hotspot tracking (symbol/timeframe)."""
from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()
_symbol_counts: Counter[str] = Counter()
_tf_counts: Counter[str] = Counter()

# Bound the number of distinct keys tracked so an authenticated client probing
# many distinct symbols (``symbol`` is only capped at 10 chars, charset is
# unrestricted) cannot grow these counters without limit and OOM the daemon.
# When the cap is exceeded we drop the least-frequent keys down to a low
# watermark: hot symbols (high counts) survive, one-off probes/typos are
# evicted. The watermark batches eviction so it runs at most once per
# ``_MAX_TRACKED_KEYS - _EVICT_TO`` new distinct keys.
_MAX_TRACKED_KEYS = 4096
_EVICT_TO = 3072


def _bounded_increment(counter: Counter[str], key: str) -> None:
    """Increment ``counter[key]`` and evict least-frequent keys past the cap."""
    counter[key] += 1
    if len(counter) > _MAX_TRACKED_KEYS:
        for stale_key, _ in counter.most_common()[_EVICT_TO:]:
            del counter[stale_key]


def record_request(symbol: str, tf: str) -> None:
    """Record one successful/validated smc_live request."""
    sym = symbol.upper().strip()
    timeframe = tf.strip()
    if not sym or not timeframe:
        return
    with _lock:
        _bounded_increment(_symbol_counts, sym)
        _bounded_increment(_tf_counts, timeframe)


def snapshot(top_n: int = 5) -> dict[str, object]:
    """Return a defensive snapshot of top symbol/timeframe request counts."""
    with _lock:
        return {
            "symbol_count": len(_symbol_counts),
            "tf_count": len(_tf_counts),
            "top_symbols": list(_symbol_counts.most_common(max(1, top_n))),
            "top_tfs": list(_tf_counts.most_common(max(1, top_n))),
        }


def reset() -> None:
    """Reset all counters (tests/debug only)."""
    with _lock:
        _symbol_counts.clear()
        _tf_counts.clear()
