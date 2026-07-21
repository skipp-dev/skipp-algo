"""Bounded, fail-closed handoff buffer for A0-Fast one-second bars."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from .a0_stream_state import StreamBar


@dataclass(frozen=True, slots=True)
class BufferedBar:
    bar: StreamBar
    resync_required: bool


@dataclass(frozen=True, slots=True)
class BufferOffer:
    dropped: StreamBar | None
    depth: int


@dataclass(frozen=True, slots=True)
class BufferSnapshot:
    capacity: int
    depth: int
    high_watermark: int
    dropped_total: int
    resync_required_symbols: tuple[str, ...]
    closed: bool
    close_reason: str | None


class BoundedBarBuffer:
    """Drop oldest on overflow and force that symbol through reconstruction."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("buffer capacity must be positive")
        self._capacity = int(capacity)
        self._items: deque[StreamBar] = deque()
        self._dirty_symbols: set[str] = set()
        self._high_watermark = 0
        self._dropped_total = 0
        self._closed = False
        self._close_reason: str | None = None
        self._condition = threading.Condition()

    def offer(self, bar: StreamBar) -> BufferOffer:
        """Add one bar without blocking the reader thread."""
        dropped: StreamBar | None = None
        with self._condition:
            if self._closed:
                raise RuntimeError("cannot offer to a closed stream buffer")
            if len(self._items) >= self._capacity:
                dropped = self._items.popleft()
                self._dirty_symbols.add(dropped.symbol.strip().upper())
                self._dropped_total += 1
            self._items.append(bar)
            self._high_watermark = max(self._high_watermark, len(self._items))
            self._condition.notify()
            return BufferOffer(dropped=dropped, depth=len(self._items))

    def put(self, bar: StreamBar) -> BufferOffer:
        """Add one bar with backpressure, without dropping replay history."""
        with self._condition:
            while len(self._items) >= self._capacity and not self._closed:
                self._condition.wait()
            if self._closed:
                raise RuntimeError("cannot put into a closed stream buffer")
            self._items.append(bar)
            self._high_watermark = max(self._high_watermark, len(self._items))
            self._condition.notify()
            return BufferOffer(dropped=None, depth=len(self._items))

    def take(self, *, timeout: float | None = None) -> BufferedBar | None:
        """Take one bar, or return None on timeout / a drained closed buffer."""
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            while not self._items and not self._closed:
                remaining = (
                    None if deadline is None else max(0.0, deadline - time.monotonic())
                )
                if remaining == 0.0:
                    return None
                self._condition.wait(remaining)
            if not self._items:
                return None
            bar = self._items.popleft()
            symbol = bar.symbol.strip().upper()
            resync_required = symbol in self._dirty_symbols
            self._condition.notify_all()
            return BufferedBar(bar=bar, resync_required=resync_required)

    def acknowledge_resync(self, symbol: str) -> None:
        """Clear a drop marker only after historical reconstruction succeeds."""
        with self._condition:
            self._dirty_symbols.discard(symbol.strip().upper())

    def discard_all(self) -> int:
        """Discard queued bars after disconnect and retain their resync markers."""
        with self._condition:
            discarded = len(self._items)
            self._dirty_symbols.update(
                item.symbol.strip().upper() for item in self._items
            )
            self._items.clear()
            self._dropped_total += discarded
            self._condition.notify_all()
            return discarded

    def close(self, reason: str | None = None) -> None:
        with self._condition:
            self._closed = True
            self._close_reason = str(reason) if reason else None
            self._condition.notify_all()

    def snapshot(self) -> BufferSnapshot:
        with self._condition:
            return BufferSnapshot(
                capacity=self._capacity,
                depth=len(self._items),
                high_watermark=self._high_watermark,
                dropped_total=self._dropped_total,
                resync_required_symbols=tuple(sorted(self._dirty_symbols)),
                closed=self._closed,
                close_reason=self._close_reason,
            )
