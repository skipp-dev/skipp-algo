"""
Thread-safe bar accumulator and overlay field cache.

Design notes:
  - A single module-level RWLock-style design would be simpler, but Python's
    threading.Lock is sufficient here because the read path (HTTP requests)
    is fast (dict lookup) and the write path (bar append) holds the lock for
    microseconds.
  - Per user memory (concurrency-shared-mutables.md): module-level mutable
    dicts that are touched from background threads MUST be guarded by a Lock.
  - Snapshot reads must return a defensive copy under the lock.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# BarCache: symbol → deque of bar dicts (OHLCV), capped at rolling_bars
_bar_lock = threading.Lock()
_bars: dict[str, deque[dict[str, Any]]] = {}
_bar_last_update: dict[str, float] = {}  # symbol → monotonic timestamp of last push
_rolling_bars_cap: int = 60  # set by feed.py on init
_max_symbols: int = 2000  # configurable via init_bar_cache()

# OverlayCache: symbol → overlay payload dict (pre-computed)
_overlay_lock = threading.Lock()
_overlay: dict[str, dict[str, Any]] = {}
_overlay_computed_at: float = 0.0

# VIX level (updated separately since it's a single value)
_vix_lock = threading.Lock()
_vix_level: float | None = None


# ---------------------------------------------------------------------------
# Bar cache API
# ---------------------------------------------------------------------------

def init_bar_cache(rolling_bars: int, *, max_symbols: int = 2000) -> None:
    global _rolling_bars_cap, _max_symbols
    if max_symbols < 1:
        raise ValueError(f"max_symbols must be >= 1, got {max_symbols}")
    _rolling_bars_cap = rolling_bars
    _max_symbols = max_symbols


def push_bar(symbol: str, bar: dict[str, Any]) -> None:
    """Append a 1-min OHLCV bar for symbol, evicting oldest if at cap."""
    with _bar_lock:
        if symbol not in _bars:
            # Evict least-recently-updated symbols until under capacity
            # Safety: limit iterations to prevent infinite loop on misconfiguration
            for _ in range(_max_symbols + 1):
                if len(_bars) < _max_symbols:
                    break
                _evict_stale_symbols_locked()
            _bars[symbol] = deque(maxlen=_rolling_bars_cap)
        _bars[symbol].append(bar)
        _bar_last_update[symbol] = time.monotonic()


def get_bars_snapshot(symbol: str) -> list[dict[str, Any]]:
    """Return a defensive copy of the bar deque for one symbol."""
    with _bar_lock:
        if symbol not in _bars:
            return []
        return list(_bars[symbol])


def get_all_symbols_snapshot() -> dict[str, list[dict[str, Any]]]:
    """Return a defensive copy of all bars. Called by compute cycle."""
    with _bar_lock:
        return {sym: list(dq) for sym, dq in _bars.items()}


def bar_symbol_count() -> int:
    with _bar_lock:
        return len(_bars)


def total_bar_count() -> int:
    with _bar_lock:
        return sum(len(dq) for dq in _bars.values())


def _evict_stale_symbols_locked() -> None:
    """Evict the 10% least-recently-updated symbols. Caller MUST hold _bar_lock."""
    if not _bar_last_update:
        return
    n_evict = max(1, len(_bars) // 10)
    victims = sorted(_bar_last_update, key=lambda s: _bar_last_update[s])[:n_evict]
    for sym in victims:
        _bars.pop(sym, None)
        _bar_last_update.pop(sym, None)
    logger.info("Evicted %d stale symbols from bar cache (cap=%d)", len(victims), _max_symbols)


# ---------------------------------------------------------------------------
# Overlay cache API
# ---------------------------------------------------------------------------

def set_overlay(payloads: dict[str, dict[str, Any]]) -> None:
    """Replace entire overlay cache atomically."""
    global _overlay_computed_at
    with _overlay_lock:
        _overlay.clear()
        _overlay.update(payloads)
        _overlay_computed_at = time.monotonic()


def get_overlay(symbol: str) -> dict[str, Any] | None:
    """Return a defensive copy of the overlay payload for one symbol."""
    with _overlay_lock:
        payload = _overlay.get(symbol.upper())
        return dict(payload) if payload is not None else None


def patch_overlay(symbol: str, updates: dict[str, Any]) -> None:
    """Merge updates into an existing overlay entry (used for fast flow refresh).

    Only patches symbols that already have a full overlay payload; ignores
    symbols not yet computed to avoid serving incomplete payloads.
    """
    with _overlay_lock:
        upper = symbol.upper()
        if upper in _overlay:
            _overlay[upper].update(updates)


def overlay_age_secs() -> float:
    """Seconds since last full overlay computation."""
    with _overlay_lock:
        if _overlay_computed_at == 0.0:
            return float("inf")
        return time.monotonic() - _overlay_computed_at


def overlay_symbol_count() -> int:
    with _overlay_lock:
        return len(_overlay)


# ---------------------------------------------------------------------------
# VIX
# ---------------------------------------------------------------------------

def set_vix(level: float) -> None:
    with _vix_lock:
        global _vix_level
        _vix_level = level


def get_vix() -> float | None:
    with _vix_lock:
        return _vix_level
