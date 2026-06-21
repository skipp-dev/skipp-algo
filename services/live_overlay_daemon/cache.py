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

import copy
import logging
import math
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
_last_eviction_at: float = 0.0  # monotonic ts of last eviction pass (L5)
_EVICT_INTERVAL_SECS: float = 60.0  # periodic eviction interval

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
    with _bar_lock:
        _rolling_bars_cap = rolling_bars
        _max_symbols = max_symbols
        # Apply updated rolling cap to existing symbol deques as well, so a
        # runtime reconfiguration is reflected immediately for already-tracked
        # symbols.
        if _bars:
            for sym, dq in list(_bars.items()):
                _bars[sym] = deque(dq, maxlen=_rolling_bars_cap)
            # Downscaling max_symbols must enforce the hard cap immediately.
            overshoot = len(_bars) - _max_symbols
            if overshoot > 0:
                _evict_n_stale_symbols_locked(overshoot)


def push_bar(symbol: str, bar: dict[str, Any]) -> None:
    """Append a 1-min OHLCV bar for symbol, evicting stale entries."""
    global _last_eviction_at
    with _bar_lock:
        now = time.monotonic()
        # Seed the eviction clock on first push so periodic eviction can fire
        if _last_eviction_at == 0.0:
            _last_eviction_at = now
        need_cap_evict = symbol not in _bars and len(_bars) >= _max_symbols
        if need_cap_evict:
            # Evict exactly the required overshoot (+1 for the incoming symbol)
            # in a single stale-sort pass to keep lock hold time bounded.
            overshoot_plus_incoming = (len(_bars) - _max_symbols) + 1
            _evict_n_stale_symbols_locked(overshoot_plus_incoming)
            _last_eviction_at = now
        if symbol not in _bars:
            _bars[symbol] = deque(maxlen=_rolling_bars_cap)
        _bars[symbol].append(bar)
        _bar_last_update[symbol] = now
        # L5: periodic eviction so stale symbols don't linger indefinitely
        if (
            _last_eviction_at > 0
            and not need_cap_evict
            and (now - _last_eviction_at) >= _EVICT_INTERVAL_SECS
        ):
            _evict_stale_symbols_locked()
            _last_eviction_at = now


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
    n_evict = max(1, len(_bars) // 10)
    _evict_n_stale_symbols_locked(n_evict)


def _evict_n_stale_symbols_locked(n_evict: int) -> None:
    """Evict N least-recently-updated symbols. Caller MUST hold _bar_lock."""
    if not _bar_last_update:
        return
    n_evict = max(0, min(n_evict, len(_bars)))
    if n_evict == 0:
        return
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
    """Return a deep defensive copy of the overlay payload for one symbol.

    HTTP handlers may mutate nested fields (e.g., injecting tf or recomputing
    stale flags) before serialising the response. A shallow copy would let
    those mutations leak back into the shared cache.
    """
    with _overlay_lock:
        payload = _overlay.get(symbol.upper())
        return copy.deepcopy(payload) if payload is not None else None


def patch_overlay(
    symbol: str,
    updates: dict[str, Any],
    *,
    allow_none_keys: set[str] | None = None,
) -> None:
    """Merge updates into an existing overlay entry (used for fast flow refresh).

    Only patches symbols that already have a full overlay payload; ignores
    symbols not yet computed to avoid serving incomplete payloads.

    None values in *updates* are skipped by default so failed/uncomputable
    refresh paths don't erase previously valid values. Callers can explicitly
    allow None overwrite for selected keys via ``allow_none_keys`` when
    ``None`` is the correct current-state value (for example, flow fields when
    the latest bar is malformed).
    """
    with _overlay_lock:
        upper = symbol.upper()
        if upper in _overlay:
            allowed_none = allow_none_keys or set()
            _overlay[upper].update(
                {
                    k: v
                    for k, v in updates.items()
                    if (
                        (v is not None or k in allowed_none)
                        and not ((isinstance(v, float) and not math.isfinite(v)) or (v.__class__.__name__ == "Decimal" and hasattr(v, "is_finite") and (not bool(v.is_finite()))))
                    )
                }
            )


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
    global _vix_level
    if not math.isfinite(level):
        logger.warning("Ignoring non-finite VIX level: %r", level)
        return
    with _vix_lock:
        _vix_level = level


def get_vix() -> float | None:
    with _vix_lock:
        return _vix_level
