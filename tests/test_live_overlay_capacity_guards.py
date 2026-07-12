"""Capacity-parameter validation guards (bug-hunt round 5).

Buffer-like constructors accepted a zero/non-positive capacity and failed
later (silently-empty bar cache) instead of failing fast at construction.
"""

from __future__ import annotations

import pytest

from services.live_overlay_daemon import cache


def test_init_bar_cache_rejects_non_positive_rolling_bars() -> None:
    # rolling_bars=0 built deque(maxlen=0) caches: every bar append was
    # silently discarded and downstream compute saw empty bars.
    with pytest.raises(ValueError, match="rolling_bars must be >= 1"):
        cache.init_bar_cache(0, max_symbols=100)
    with pytest.raises(ValueError, match="rolling_bars must be >= 1"):
        cache.init_bar_cache(-1, max_symbols=100)
    # Symmetry with the existing max_symbols guard.
    with pytest.raises(ValueError, match="max_symbols must be >= 1"):
        cache.init_bar_cache(60, max_symbols=0)
