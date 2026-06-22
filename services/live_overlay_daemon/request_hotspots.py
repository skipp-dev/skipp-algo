"""In-process request hotspot tracking (symbol/timeframe)."""
from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()
_symbol_counts: Counter[str] = Counter()
_tf_counts: Counter[str] = Counter()


def record_request(symbol: str, tf: str) -> None:
    """Record one successful/validated smc_live request."""
    sym = symbol.upper().strip()
    timeframe = tf.strip()
    if not sym or not timeframe:
        return
    with _lock:
        _symbol_counts[sym] += 1
        _tf_counts[timeframe] += 1


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
