"""In-process request hotspot tracking (symbol/timeframe)."""
from __future__ import annotations

import itertools
import threading
from collections import Counter

_lock = threading.Lock()
_symbol_counts: Counter[str] = Counter()
_tf_counts: Counter[str] = Counter()
# Monotonic access ticks per key so eviction can break count ties by recency
# (LRU): among equally-frequent keys the least-recently-seen are dropped first,
# so a freshly-recorded legitimate symbol is never evicted ahead of an ancient
# one-off probe that happens to share the same count.
_seq = itertools.count()
_symbol_seen: dict[str, int] = {}
_tf_seen: dict[str, int] = {}

# Bound the number of distinct keys tracked so an authenticated client probing
# many distinct symbols (``symbol`` is only capped at 10 chars, charset is
# unrestricted) cannot grow these counters without limit and OOM the daemon.
# When the cap is exceeded we drop the least-frequent keys down to a low
# watermark: hot symbols (high counts) survive, one-off probes/typos are
# evicted. The watermark batches eviction so it runs at most once per
# ``_MAX_TRACKED_KEYS - _EVICT_TO`` new distinct keys.
_MAX_TRACKED_KEYS = 4096
_EVICT_TO = 3072


def _bounded_increment(counter: Counter[str], seen: dict[str, int], key: str) -> None:
    """Increment ``counter[key]`` and evict cold keys past the cap.

    Eviction ranks keys by ``(count, last_seen)`` ascending and drops the
    lowest down to the low watermark, so hot keys (high count) survive and, at
    equal counts, the least-recently-seen probe is evicted before a recent
    legitimate request. The just-incremented ``key`` carries the newest tick
    and is therefore always retained.
    """
    counter[key] += 1
    seen[key] = next(_seq)
    if len(counter) > _MAX_TRACKED_KEYS:
        ranked = sorted(counter, key=lambda k: (counter[k], seen[k]))
        for stale_key in ranked[: len(counter) - _EVICT_TO]:
            del counter[stale_key]
            del seen[stale_key]


def record_request(symbol: str, tf: str) -> None:
    """Record one successful/validated smc_live request."""
    sym = symbol.upper().strip()
    timeframe = tf.strip()
    if not sym or not timeframe:
        return
    with _lock:
        _bounded_increment(_symbol_counts, _symbol_seen, sym)
        _bounded_increment(_tf_counts, _tf_seen, timeframe)


def snapshot(top_n: int = 5) -> dict[str, object]:
    """Return a defensive snapshot of top symbol/timeframe request counts."""
    with _lock:
        n = max(0, top_n)
        return {
            "symbol_count": len(_symbol_counts),
            "tf_count": len(_tf_counts),
            "top_symbols": list(_symbol_counts.most_common(n)),
            "top_tfs": list(_tf_counts.most_common(n)),
        }


def reset() -> None:
    """Reset all counters (tests/debug only)."""
    with _lock:
        _symbol_counts.clear()
        _tf_counts.clear()
        _symbol_seen.clear()
        _tf_seen.clear()
