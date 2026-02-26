"""Background polling thread for the News Terminal.

Moves the API poll cycle off the Streamlit rerun loop into a dedicated
``threading.Thread``.  The thread writes new items into a
``queue.Queue`` which the Streamlit main loop drains on each rerun —
ensuring the UI never blocks on network I/O.

Usage in ``streamlit_terminal.py``::

    from terminal_background_poller import BackgroundPoller

    poller = BackgroundPoller(cfg, adapter, fmp_adapter, store)
    poller.start()

    # On each Streamlit rerun:
    new_items = poller.drain()
    feed = new_items + feed
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class BackgroundPoller:
    """Runs ``poll_and_classify_multi`` in a background thread.

    Thread-safe: all shared state is accessed via a ``queue.Queue``
    (items) and atomic attribute reads (status, error, etc.).

    Parameters
    ----------
    cfg : TerminalConfig
        Terminal configuration.
    benzinga_adapter : BenzingaRestAdapter or None
    fmp_adapter : FmpAdapter or None
    store : SqliteStore
    """

    def __init__(
        self,
        cfg: Any,
        benzinga_adapter: Any | None,
        fmp_adapter: Any | None,
        store: Any,
    ) -> None:
        self._cfg = cfg
        self._benzinga = benzinga_adapter
        self._fmp = fmp_adapter
        self._store = store

        self._queue: queue.Queue[list[Any]] = queue.Queue(maxsize=100)
        self._cursor: str | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Observable status (read from Streamlit main thread)
        self.poll_count: int = 0
        self.last_poll_ts: float = 0.0
        self.last_poll_status: str = "—"
        self.last_poll_error: str = ""
        self.total_items_ingested: int = 0
        self.consecutive_empty_polls: int = 0

    # ── Thread lifecycle ────────────────────────────────────

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, cursor: str | None = None) -> None:
        """Start the background polling thread (idempotent)."""
        if self.is_alive:
            return
        self._cursor = cursor
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="terminal-bg-poller",
            daemon=True,
        )
        self._thread.start()
        logger.info("Background poller started (interval=%.1fs)", self._cfg.poll_interval_s)

    def stop(self) -> None:
        """Signal the thread to stop (non-blocking)."""
        self._stop_event.set()
        logger.info("Background poller stop requested")

    def update_interval(self, interval_s: float) -> None:
        """Update poll interval at runtime (thread-safe)."""
        # TerminalConfig is frozen, so we store override separately
        with self._lock:
            self._interval_override = interval_s

    def update_adapters(
        self,
        benzinga_adapter: Any | None = None,
        fmp_adapter: Any | None = None,
    ) -> None:
        """Swap adapters at runtime (e.g. after API key change)."""
        with self._lock:
            if benzinga_adapter is not None:
                self._benzinga = benzinga_adapter
            if fmp_adapter is not None:
                self._fmp = fmp_adapter

    # ── Drain results (called from Streamlit main thread) ───

    def drain(self) -> list[Any]:
        """Drain all pending batches from the queue.

        Returns a flat list of ClassifiedItem objects (newest batch first).
        """
        batches: list[list[Any]] = []
        while True:
            try:
                batch = self._queue.get_nowait()
                batches.append(batch)
            except queue.Empty:
                break
        # Flatten: newest batch first
        items: list[Any] = []
        for batch in reversed(batches):
            items.extend(batch)
        return items

    @property
    def cursor(self) -> str | None:
        return self._cursor

    @cursor.setter
    def cursor(self, value: str | None) -> None:
        with self._lock:
            self._cursor = value

    # ── Internal poll loop ──────────────────────────────────

    def _get_interval(self) -> float:
        with self._lock:
            return getattr(self, "_interval_override", self._cfg.poll_interval_s)

    def _run_loop(self) -> None:
        """Main loop running in the background thread."""
        import re as _re

        from terminal_poller import poll_and_classify_multi

        logger.info("Background poll loop entered")

        while not self._stop_event.is_set():
            interval = self._get_interval()

            # Wait for the poll interval (interruptible by stop_event)
            if self._stop_event.wait(timeout=interval):
                break

            # Grab adapters under lock
            with self._lock:
                bz = self._benzinga
                fmp = self._fmp

            if bz is None and fmp is None:
                continue

            try:
                items, new_cursor = poll_and_classify_multi(
                    benzinga_adapter=bz,
                    fmp_adapter=fmp,
                    store=self._store,
                    cursor=self._cursor,
                    page_size=self._cfg.page_size,
                )
            except Exception as exc:
                _safe = _re.sub(
                    r"(apikey|token)=[^&\s]+", r"\1=***",
                    str(exc), flags=_re.IGNORECASE,
                )
                logger.exception("Background poll failed: %s", _safe)
                self.last_poll_error = _safe
                self.last_poll_status = "ERROR"
                self.last_poll_ts = time.time()
                continue

            with self._lock:
                self._cursor = new_cursor

            self.poll_count += 1
            self.last_poll_ts = time.time()
            self.total_items_ingested += len(items)
            self.last_poll_error = ""

            src = "BZ"
            if fmp is not None:
                src = "BZ+FMP"
            self.last_poll_status = f"{len(items)} items [{src}]"

            # Track consecutive empties → auto-prune dedup
            if not items:
                self.consecutive_empty_polls += 1
                if self.consecutive_empty_polls >= 3:
                    try:
                        # Partial prune when items have been ingested before;
                        # full clear only when nothing was ever ingested (the
                        # dedup DB is blocking everything from the start).
                        _keep = 0.0 if self.total_items_ingested == 0 else self._cfg.feed_max_age_s
                        self._store.prune_seen(keep_seconds=_keep)
                        self._store.prune_clusters(keep_seconds=_keep)
                        with self._lock:
                            self._cursor = None
                        logger.info(
                            "BG poller: reset cursor + pruned SQLite after %d empty polls",
                            self.consecutive_empty_polls,
                        )
                    except Exception as exc:
                        logger.warning("BG poller SQLite prune failed: %s", exc)
                    self.consecutive_empty_polls = 0
            else:
                self.consecutive_empty_polls = 0

            # Enqueue items for the main thread
            if items:
                try:
                    self._queue.put_nowait(items)
                except queue.Full:
                    logger.warning("BG poller queue full, dropping %d items", len(items))

            # Periodic SQLite prune (every 100 polls)
            if self.poll_count % 100 == 0:
                try:
                    self._store.prune_seen(keep_seconds=86400)
                    self._store.prune_clusters(keep_seconds=86400)
                except Exception as exc:
                    logger.warning("BG poller periodic prune failed: %s", exc)

        logger.info("Background poll loop exited")
