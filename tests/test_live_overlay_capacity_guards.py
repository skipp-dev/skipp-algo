"""Capacity-parameter validation guards (bug-hunt round 5).

Same class as the RingBuffer(max_size=0) crash: buffer-like constructors
accepted a zero/non-positive capacity and failed later (ZeroDivisionError
in the rolling average, silently-empty bar cache) instead of failing fast
at construction. See tests/test_smc_ringbuffer.py for the RingBuffer and
SmcBoxManager guards themselves.
"""

from __future__ import annotations

import pytest

from services.live_overlay_daemon import cache
from services.live_overlay_daemon.smc_advanced_patterns import HVBDetector


def test_hvb_detector_rejects_non_positive_lookback() -> None:
    # lookback=0 trimmed volume_history to empty right before the
    # rolling-average division -> ZeroDivisionError on first detect().
    with pytest.raises(ValueError, match="lookback must be >= 1"):
        HVBDetector(lookback=0)
    with pytest.raises(ValueError, match="lookback must be >= 1"):
        HVBDetector(lookback=-5)


def test_hvb_detector_normal_lookback_still_works() -> None:
    det = HVBDetector(lookback=2, hvb_threshold=1.5)
    det.detect(bar_index=1, volume=100, close=10.0, open=9.0, high=11.0, low=8.0)
    bar = det.detect(bar_index=2, volume=300, close=10.0, open=9.0, high=11.0, low=8.0)
    assert bar.volume_ratio > 1.0


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
