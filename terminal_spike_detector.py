"""Real-time Price Spike Detector.

Detects sub-minute price spikes by comparing consecutive quote snapshots.
Unlike the daily-change spike scanner (``terminal_spike_scanner``), this
module tracks **intra-poll price deltas** to surface *new* rapid moves
in real time — the same behavior as Benzinga Pro's "Price Spike" signals.

Architecture
~~~~~~~~~~~~
A persistent ``SpikeDetector`` instance lives in ``st.session_state``.
Each Streamlit refresh cycle calls ``detector.update(quotes)`` with the
latest FMP gainers/losers/actives data.  The detector:

  1. Records current prices per symbol in a rolling buffer.
  2. Compares the current price to the price seen ``lookback_s`` seconds
     ago (default 60 s).
  3. If the price changed by ≥ ``spike_threshold_pct`` within that
     window, emits a **SpikeEvent**.
  4. Spike events are kept in a rolling history (newest first) with a
     configurable max length and max age.

All logic is pure Python — no Streamlit dependency — so it can be
tested independently.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SpikeEvent:
    """A single detected price spike."""

    symbol: str
    direction: str          # "UP" or "DOWN"
    spike_pct: float        # signed % change that triggered the spike
    price: float            # current price
    prev_price: float       # price ``lookback_s`` ago
    change_pct: float       # day change % (from FMP)
    change: float           # day change $ (from FMP)
    volume: int
    name: str
    asset_type: str         # "STOCK" or "ETF"
    ts: float               # epoch when detected

    @property
    def icon(self) -> str:
        return "🟢" if self.direction == "UP" else "🔴"

    @property
    def age_s(self) -> float:
        return time.time() - self.ts


@dataclass
class _PriceSnapshot:
    """A single price observation for a symbol."""
    price: float
    ts: float


# ═══════════════════════════════════════════════════════════════════════════
# Spike Detector
# ═══════════════════════════════════════════════════════════════════════════

class SpikeDetector:
    """Stateful detector that compares consecutive quote snapshots.

    Parameters
    ----------
    spike_threshold_pct : float
        Minimum absolute % move within *lookback_s* to trigger a spike.
    lookback_s : float
        Time window in seconds to compare prices across.
    max_history : int
        Maximum number of spike events to retain.
    max_event_age_s : float
        Events older than this are pruned from history.
    cooldown_s : float
        Minimum seconds between spike events for the *same* symbol.
    """

    def __init__(
        self,
        *,
        spike_threshold_pct: float = 1.0,
        lookback_s: float = 60.0,
        max_history: int = 200,
        max_event_age_s: float = 3600.0,
        cooldown_s: float = 120.0,
    ) -> None:
        self.spike_threshold_pct = spike_threshold_pct
        self.lookback_s = lookback_s
        self.max_history = max_history
        self.max_event_age_s = max_event_age_s
        self.cooldown_s = cooldown_s

        # symbol → deque of _PriceSnapshot (oldest first)
        self._price_buf: dict[str, deque[_PriceSnapshot]] = {}
        # Rolling spike history (newest first)
        self._events: deque[SpikeEvent] = deque(maxlen=max_history)
        # symbol → epoch of last emitted spike
        self._last_spike_ts: dict[str, float] = {}
        # Counters
        self.total_spikes_detected: int = 0
        self._poll_count: int = 0

    # ── Public API ─────────────────────────────────────────────

    def update(
        self,
        quotes: list[dict[str, Any]],
    ) -> list[SpikeEvent]:
        """Ingest a batch of quotes and return newly detected spikes.

        Parameters
        ----------
        quotes : list[dict]
            List of dicts with at minimum ``symbol`` and ``price`` keys.
            Typically the merged gainers + losers + actives from FMP.
            Also accepts: ``changesPercentage``, ``change``, ``volume``,
            ``name``, ``companyName``.

        Returns
        -------
        list[SpikeEvent]
            Newly detected spikes in this poll cycle (may be empty).
        """
        now = time.time()
        self._poll_count += 1
        new_spikes: list[SpikeEvent] = []

        for q in quotes:
            symbol = (q.get("symbol") or "").upper().strip()
            if not symbol:
                continue

            price = _safe_float(q.get("price"))
            if price <= 0:
                continue

            # Record snapshot
            buf = self._price_buf.get(symbol)
            if buf is None:
                buf = deque(maxlen=120)  # ~2 min at 1s polls, plenty
                self._price_buf[symbol] = buf
            buf.append(_PriceSnapshot(price=price, ts=now))

            # Prune old snapshots (keep only lookback window + margin)
            max_age = self.lookback_s * 3
            while buf and (now - buf[0].ts) > max_age:
                buf.popleft()

            # Find the earliest snapshot within the lookback window
            ref_snap = self._find_reference_snapshot(buf, now)
            if ref_snap is None:
                continue  # Not enough history yet

            # Calculate spike
            delta_pct = ((price - ref_snap.price) / ref_snap.price) * 100.0
            if abs(delta_pct) < self.spike_threshold_pct:
                continue

            # Cooldown check
            last_ts = self._last_spike_ts.get(symbol, 0.0)
            if (now - last_ts) < self.cooldown_s:
                continue

            direction = "UP" if delta_pct > 0 else "DOWN"
            change_pct = _safe_float(q.get("changesPercentage"))
            change = _safe_float(q.get("change"))
            volume = int(_safe_float(q.get("volume")))
            name = q.get("name") or q.get("companyName") or ""
            asset_type = _asset_type(symbol, name)

            event = SpikeEvent(
                symbol=symbol,
                direction=direction,
                spike_pct=round(delta_pct, 2),
                price=round(price, 4),
                prev_price=round(ref_snap.price, 4),
                change_pct=round(change_pct, 2),
                change=round(change, 2),
                volume=volume,
                name=name[:60],
                asset_type=asset_type,
                ts=now,
            )
            new_spikes.append(event)
            self._events.appendleft(event)
            self._last_spike_ts[symbol] = now
            self.total_spikes_detected += 1

        # Prune old events
        self._prune_old_events(now)

        # Prune stale symbol buffers every 100 polls to prevent unbounded growth
        if self._poll_count % 100 == 0:
            stale_syms = [
                s for s, buf in self._price_buf.items()
                if buf and (now - buf[-1].ts) > self.max_event_age_s
            ]
            for s in stale_syms:
                del self._price_buf[s]
                self._last_spike_ts.pop(s, None)

        if new_spikes:
            logger.info(
                "Spike detector: %d new spikes (poll #%d, total %d)",
                len(new_spikes),
                self._poll_count,
                self.total_spikes_detected,
            )

        return new_spikes

    @property
    def events(self) -> list[SpikeEvent]:
        """Return all spike events (newest first)."""
        return list(self._events)

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def poll_count(self) -> int:
        return self._poll_count

    @property
    def symbols_tracked(self) -> int:
        return len(self._price_buf)

    def clear(self) -> None:
        """Reset all state."""
        self._price_buf.clear()
        self._events.clear()
        self._last_spike_ts.clear()
        self.total_spikes_detected = 0
        self._poll_count = 0

    # ── Internal ───────────────────────────────────────────────

    def _find_reference_snapshot(
        self,
        buf: deque[_PriceSnapshot],
        now: float,
    ) -> _PriceSnapshot | None:
        """Find the snapshot closest to ``lookback_s`` ago.

        Scans the buffer for the snapshot whose timestamp is closest to
        ``now - lookback_s``.  Returns None if no snapshot is old enough
        (i.e. all snapshots are within the lookback window start).
        """
        target_ts = now - self.lookback_s
        best: _PriceSnapshot | None = None
        best_dist = float("inf")

        for snap in buf:
            dist = abs(snap.ts - target_ts)
            if dist < best_dist and snap.ts <= target_ts:
                best = snap
                best_dist = dist

        return best

    def _prune_old_events(self, now: float) -> None:
        """Remove events older than max_event_age_s."""
        while self._events and (now - self._events[-1].ts) > self.max_event_age_s:
            self._events.pop()


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _asset_type(symbol: str, name: str = "") -> str:
    _name_upper = (name or "").upper()
    if any(kw in _name_upper for kw in ("ETF", "FUND", "TRUST", "INDEX")):
        return "ETF"
    return "STOCK"


def format_spike_description(event: SpikeEvent) -> str:
    """Format a spike event description like Benzinga Pro.

    Example: ``Price Spike DOWN -1.52% < 1 minute. (Quote: 14.6 +0.04 +0.2747%)``
    """
    sign = "+" if event.spike_pct > 0 else ""
    chg_sign = "+" if event.change > 0 else ""
    chg_pct_sign = "+" if event.change_pct > 0 else ""
    return (
        f"Price Spike {event.direction} {sign}{event.spike_pct:.1f}% < 1 minute. "
        f"(Quote: {event.price:.4g} {chg_sign}{event.change:.2f} "
        f"{chg_pct_sign}{event.change_pct:.4f}%)"
    )


def format_time_et(epoch: float) -> str:
    """Format epoch as HH:MM:SS AM/PM in Eastern Time."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    _et = ZoneInfo("America/New_York")
    dt = datetime.fromtimestamp(epoch, tz=_et)
    return dt.strftime("%-I:%M:%S %p")
