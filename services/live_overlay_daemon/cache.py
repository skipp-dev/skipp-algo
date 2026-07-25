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

from . import config, request_hotspots

logger = logging.getLogger(__name__)

# BarCache: symbol → deque of bar dicts (OHLCV), capped at rolling_bars
_bar_lock = threading.Lock()
_bars: dict[str, deque[dict[str, Any]]] = {}
_bar_last_update: dict[str, float] = {}  # symbol → monotonic timestamp of last push
_rolling_bars_cap: int = 60  # set by feed.py on init
_max_symbols: int = 2000  # configurable via init_bar_cache()
_last_eviction_at: float = 0.0  # monotonic ts of last eviction pass (L5)
_EVICT_INTERVAL_SECS: float = 60.0  # periodic eviction interval
# Eviction-log throttle: cap-eviction fires once per new symbol while the cache
# sits at capacity, so at market open it logs hundreds of single-symbol
# evictions per second — enough to blow past Railway's 500 lines/s limit and get
# real log lines dropped. Aggregate the churn and emit at most one INFO summary
# per window instead (per-eviction detail stays available at DEBUG).
_EVICT_SUMMARY_INTERVAL_SECS: float = 60.0  # min gap between eviction summaries


class _EvictSummary:
    """Throttle state for the aggregated eviction log. Mutated in place under
    ``_bar_lock`` so no module-level ``global`` is needed (see
    tests/test_global_statement_budget.py)."""

    __slots__ = ("at", "pending")

    def __init__(self) -> None:
        self.pending: int = 0  # symbols evicted since the last summary line
        self.at: float = 0.0  # monotonic ts of the last summary; 0.0 = unseeded


_evict_summary = _EvictSummary()

# OverlayCache: symbol → overlay payload dict (pre-computed)
_overlay_lock = threading.Lock()
_overlay: dict[str, dict[str, Any]] = {}
_overlay_computed_at: float = 0.0

# Bar-cache eviction counters. Cap churn had NO metric before 2026-07-22, so
# the cache thrashing that starved every rolling metric was invisible to
# monitoring; `evicted_protected_total` rising means the cap is genuinely too
# small for actual demand (not just for the ALL_SYMBOLS firehose).
# Mutated in place under `_bar_lock` — no ``global`` statement (statement-budget
# guard) and trivially resettable in tests.
_evict_counters: dict[str, int] = {"total": 0, "protected": 0}


# VIX level (updated separately since it's a single value)
_vix_lock = threading.Lock()
_vix_level: float | None = None


# ---------------------------------------------------------------------------
# Bar cache API
# ---------------------------------------------------------------------------

def init_bar_cache(rolling_bars: int, *, max_symbols: int = 2000) -> None:
    global _rolling_bars_cap, _max_symbols
    if rolling_bars < 1:
        raise ValueError(f"rolling_bars must be >= 1, got {rolling_bars}")
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
            _evict_stale_symbols_locked(now)
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


def evicted_symbols_total() -> int:
    """Symbols dropped from the bar cache since process start."""
    with _bar_lock:
        return _evict_counters["total"]


def evicted_protected_total() -> int:
    """Evictions that hit a REQUESTED symbol — the cap is too small when >0."""
    with _bar_lock:
        return _evict_counters["protected"]


def total_bar_count() -> int:
    with _bar_lock:
        return sum(len(dq) for dq in _bars.values())


def requested_bar_depth() -> tuple[int, float]:
    """Depth of the bar cache restricted to symbols a consumer actually reads.

    Returns ``(count, mean_bars)`` over the intersection of the cache and
    ``request_hotspots.requested_symbols()``. This — not the global
    ``bar_count / bar_symbols`` — is the number that gates the rolling
    features: with an ``ALL_SYMBOLS`` feed the cache pins at the cap with the
    unrequested majority holding a single bar, so the global mean sits at ~1.0
    by design (demand-aware retention, #3903) even while every watched symbol
    carries full history. ``count`` is 0 when no requested symbol is cached, so
    callers can leave the "no consumer" case to the request-rate watchdog.

    Lock order matches ``_evict_n_stale_symbols_locked``: hold ``_bar_lock``
    first, then read the hotspots snapshot, so the two never deadlock.
    """
    with _bar_lock:
        requested = request_hotspots.requested_symbols()
        depths = [len(_bars[sym]) for sym in requested if sym in _bars]
    if not depths:
        return 0, 0.0
    return len(depths), sum(depths) / len(depths)


def _evict_stale_symbols_locked(now: float) -> None:
    """Evict old, unrequested symbols periodically. Caller MUST hold _bar_lock."""
    stale_before = now - config.max_stale_secs()
    protected = request_hotspots.requested_symbols()
    candidates = {
        symbol
        for symbol, updated_at in _bar_last_update.items()
        if updated_at < stale_before and symbol not in protected
    }
    n_evict = max(1, len(_bars) // 10)
    _evict_n_stale_symbols_locked(n_evict, candidates=candidates)


def _evict_n_stale_symbols_locked(
    n_evict: int, *, candidates: set[str] | None = None
) -> None:
    """Evict N least-recently-updated symbols. Caller MUST hold _bar_lock."""
    available = _bar_last_update.keys() if candidates is None else candidates
    if not available:
        return
    n_evict = max(0, min(n_evict, len(available)))
    if n_evict == 0:
        return
    # Demand-aware retention: with an ALL_SYMBOLS feed every tracked symbol
    # ticks about once a minute, so `_bar_last_update` is near-uniform and
    # sorting by it alone evicts essentially at random — including the few
    # symbols someone is actually watching. Observed 2026-07-22 in production:
    # bar_symbols pinned at the 2000 cap with bar_count also 2000, i.e. ONE bar
    # per symbol, so every rolling metric (relative volume needs 19 prior bars,
    # squeeze 20, ATS z-score history) was structurally unavailable and the
    # sidecar's technical feed rendered "—" for every symbol.
    # Requested symbols are therefore evicted only when nothing else is left;
    # the cap stays a hard limit.
    protected = request_hotspots.requested_symbols()
    victims = sorted(
        available,
        key=lambda s: (s in protected, _bar_last_update[s]),
    )[:n_evict]
    for sym in victims:
        _bars.pop(sym, None)
        _bar_last_update.pop(sym, None)
        _evict_counters["total"] += 1
        if sym in protected:
            _evict_counters["protected"] += 1
    logger.debug("Evicted %d stale symbols from bar cache (cap=%d)", len(victims), _max_symbols)

    # Throttle the INFO line: aggregate churn and emit at most one summary per
    # _EVICT_SUMMARY_INTERVAL_SECS so steady cap-eviction can't flood the log.
    _evict_summary.pending += len(victims)
    now = time.monotonic()
    if _evict_summary.at == 0.0:
        _evict_summary.at = now
        return
    elapsed = now - _evict_summary.at
    if elapsed >= _EVICT_SUMMARY_INTERVAL_SECS:
        logger.info(
            "Bar cache evicted %d stale symbols in the last %.0fs (cap=%d, tracked=%d)",
            _evict_summary.pending, elapsed, _max_symbols, len(_bars),
        )
        _evict_summary.pending = 0
        _evict_summary.at = now


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
) -> bool:
    """Merge updates into an existing overlay entry (used for fast flow refresh).

    Only patches symbols that already have a full overlay payload; ignores
    symbols not yet computed to avoid serving incomplete payloads. Returns
    ``True`` when the symbol existed and was patched, ``False`` when it was
    ignored.

    None values in *updates* are skipped by default so failed/uncomputable
    refresh paths don't erase previously valid values. Callers can explicitly
    allow None overwrite for selected keys via ``allow_none_keys`` when
    ``None`` is the correct current-state value (for example, flow fields when
    the latest bar is malformed).
    """
    with _overlay_lock:
        upper = symbol.upper()
        if upper not in _overlay:
            return False
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
        return True


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
        _vix_updated_at["ts"] = time.monotonic()


def get_vix() -> float | None:
    with _vix_lock:
        return _vix_level


# Monotonic timestamp of the last ACCEPTED set_vix. Kept in a mutable holder
# (declared below the pinned `global` sites) instead of a rebound module global:
# a new `global` statement would add a site to the global-statement budget
# ledger. Mirrors the feed._runtime precedent.
_vix_updated_at: dict[str, float] = {}


def vix_age_secs() -> float:
    """Seconds since the last accepted VIX refresh (``inf`` before the first).

    Rejected non-finite quotes do not stamp the timestamp, so a poll loop that
    only ever yields garbage keeps ageing instead of masquerading as fresh.
    """
    with _vix_lock:
        ts = _vix_updated_at.get("ts")
    return float("inf") if ts is None else time.monotonic() - ts
