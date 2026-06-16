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

import threading
import time
from collections import deque
from typing import Any

# BarCache: symbol → deque of bar dicts (OHLCV), capped at rolling_bars
_bar_lock = threading.Lock()
_bars: dict[str, deque[dict[str, Any]]] = {}
_rolling_bars_cap: int = 60  # set by feed.py on init

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

def init_bar_cache(rolling_bars: int) -> None:
    global _rolling_bars_cap
    _rolling_bars_cap = rolling_bars


def push_bar(symbol: str, bar: dict[str, Any]) -> None:
    """Append a 1-min OHLCV bar for symbol, evicting oldest if at cap."""
    with _bar_lock:
        if symbol not in _bars:
            _bars[symbol] = deque(maxlen=_rolling_bars_cap)
        _bars[symbol].append(bar)


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
    """Merge updates into an existing overlay entry (used for fast flow refresh)."""
    with _overlay_lock:
        upper = symbol.upper()
        if upper in _overlay:
            _overlay[upper].update(updates)
        else:
            _overlay[upper] = dict(updates)


def overlay_age_secs() -> float:
    """Seconds since last full overlay computation."""
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
