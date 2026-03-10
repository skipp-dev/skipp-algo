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

        self._queue: queue.Queue[list[Any]] = queue.Queue(maxsize=500)
        self._cursor: str | None = None
        self._lock = threading.Lock()
        self._stats_lock = threading.Lock()  # protects observable counters
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()  # signal to interrupt sleep
        self._thread: threading.Thread | None = None

        # Observable status (read from Streamlit main thread)
        self.poll_count: int = 0
        self.poll_attempts: int = 0
        self.last_poll_ts: float = 0.0
        self.last_poll_status: str = "—"
        self.last_poll_error: str = ""
        self.total_items_ingested: int = 0
        self.total_items_dropped: int = 0
        self.consecutive_empty_polls: int = 0
        self.last_poll_duration_s: float = 0.0
        self._last_periodic_prune_ts: float = 0.0  # for 30s dedup reset

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
        self._wake_event.set()  # interrupt sleep so thread exits promptly
        logger.info("Background poller stop requested")

    def stop_and_join(self, timeout: float = 5.0) -> None:
        """Signal the thread to stop and wait for it to finish.

        Use this when the caller needs the BG thread to be fully stopped
        before proceeding (e.g. before deleting the SQLite DB file).
        """
        self.stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("Background poller thread did not exit within %.1fs", timeout)

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

    def wake_and_reset_cursor(self) -> None:
        """Atomically reset cursor to None AND wake the poll thread.

        This ensures the next poll uses cursor=None (fetch latest) even
        if the thread is mid-sleep.  The wake event interrupts the
        sleep so the poll happens immediately instead of waiting for
        the remaining interval.
        """
        with self._lock:
            self._cursor = None
        self._wake_event.set()

    # ── Internal poll loop ──────────────────────────────────

    def _get_interval(self) -> float:
        with self._lock:
            return float(getattr(self, "_interval_override", self._cfg.poll_interval_s))

    def _run_loop(self) -> None:
        """Main loop running in the background thread."""
        import re as _re

        from terminal_poller import poll_and_classify_multi

        logger.info("Background poll loop entered")

        _first_iteration = True
        while not self._stop_event.is_set():
            interval = self._get_interval()

            # First iteration: poll immediately so the counter increments
            # on startup instead of waiting the full interval.
            if _first_iteration:
                _first_iteration = False
            else:
                # Sleep for the poll interval, but wake early on:
                #   - _stop_event: graceful shutdown
                #   - _wake_event: stale recovery / forced re-poll
                # We use _wake_event.wait() as the primary sleep so that
                # wake_and_reset_cursor() can interrupt it immediately.
                self._wake_event.clear()
                self._wake_event.wait(timeout=interval)
                self._wake_event.clear()
                if self._stop_event.is_set():
                    break

            # Grab adapters under lock
            with self._lock:
                bz = self._benzinga
                fmp = self._fmp

            if bz is None and fmp is None:
                continue

            with self._stats_lock:
                self.poll_attempts += 1
            _t0 = time.monotonic()
            # Snapshot cursor under lock so a concurrent reset is
            # not overwritten by the new_cursor assignment below.
            with self._lock:
                _use_cursor = self._cursor
            try:
                items, new_cursor = poll_and_classify_multi(
                    benzinga_adapter=bz,
                    fmp_adapter=fmp,
                    store=self._store,
                    cursor=_use_cursor,
                    page_size=self._cfg.page_size,
                    channels=getattr(self._cfg, "channels", None) or None,
                    topics=getattr(self._cfg, "topics", None) or None,
                )
            except Exception as exc:
                _safe = _re.sub(
                    r"(apikey|api_key|token|key)=[^&\s]+", r"\1=***",
                    str(exc), flags=_re.IGNORECASE,
                )
                logger.exception("Background poll failed: %s", _safe)
                with self._stats_lock:
                    self.last_poll_error = _safe
                    self.last_poll_status = "ERROR"
                    self.last_poll_ts = time.time()
                    self.last_poll_duration_s = time.monotonic() - _t0
                    self.consecutive_empty_polls += 1
                continue

            with self._lock:
                # Only advance cursor if it wasn't reset while we were polling
                if self._cursor == _use_cursor:
                    self._cursor = new_cursor

            with self._stats_lock:
                self.last_poll_duration_s = time.monotonic() - _t0
                self.poll_count += 1
                self.last_poll_ts = time.time()
                self.total_items_ingested += len(items)
                self.last_poll_error = ""

            src = "BZ"
            if fmp is not None:
                src = "BZ+FMP"

            with self._stats_lock:
                self.last_poll_status = f"{len(items)} items [{src}]"

            # Track consecutive empties → auto-prune dedup
            if not items:
                with self._stats_lock:
                    self.consecutive_empty_polls += 1
                    _empties = self.consecutive_empty_polls
                if _empties >= 3:
                    # Full clear: partial keeps (feed_max_age_s) re-block
                    # items that the API returns on cursor reset, causing
                    # a 3-poll oscillation cycle.  Always clear everything.
                    _keep = 0.0
                    for _prune_fn, _tbl in (
                        (self._store.prune_seen, "seen"),
                        (self._store.prune_clusters, "clusters"),
                    ):
                        try:
                            _prune_fn(keep_seconds=_keep)
                        except Exception as exc:
                            logger.warning("BG poller prune(%s) failed: %s", _tbl, exc, exc_info=True)
                    # Cursor reset MUST happen even if prune failed — the
                    # cursor is the primary recovery action.
                    with self._lock:
                        self._cursor = None
                    logger.info(
                        "BG poller: reset cursor + pruned SQLite after %d empty polls",
                        _empties,
                    )
                    with self._stats_lock:
                        self.consecutive_empty_polls = 0
            else:
                with self._stats_lock:
                    self.consecutive_empty_polls = 0

            # Enqueue items for the main thread (ring-buffer: evict oldest
            # batches when full so the newest data always gets through)
            if items:
                evicted = 0
                while True:
                    try:
                        self._queue.put_nowait(items)
                        break
                    except queue.Full:
                        try:
                            old = self._queue.get_nowait()
                            evicted += len(old)
                        except queue.Empty:
                            # Shouldn't happen, but guard anyway
                            break
                if evicted:
                    with self._stats_lock:
                        self.total_items_dropped += evicted
                    logger.info(
                        "BG poller evicted %d stale items to make room (total dropped: %d)",
                        evicted, self.total_items_dropped,
                    )

            # Periodic SQLite prune (every 100 polls)
            if self.poll_count % 100 == 0:
                try:
                    self._store.prune_seen(keep_seconds=86400)
                    self._store.prune_clusters(keep_seconds=86400)
                except Exception as exc:
                    logger.warning("BG poller periodic prune failed: %s", exc, exc_info=True)

            # ── Periodic dedup reset (every 30s) ─────────────────
            # Keeps the dedup DB fresh so genuinely new articles aren't
            # blocked by stale seen-entries.  The in-memory dedup in
            # _process_new_items() prevents duplicates from reaching the UI.
            _DEDUP_RESET_INTERVAL_S = float(
                getattr(self._cfg, "dedup_reset_interval_s", 0)
                or 30.0
            )
            _now_mono = time.monotonic()
            if (
                self._last_periodic_prune_ts > 0
                and (_now_mono - self._last_periodic_prune_ts) >= _DEDUP_RESET_INTERVAL_S
            ):
                for _prune_fn, _tbl in (
                    (self._store.prune_seen, "seen"),
                    (self._store.prune_clusters, "clusters"),
                ):
                    try:
                        _prune_fn(keep_seconds=0)
                    except Exception as exc:
                        logger.warning("BG poller periodic dedup reset (%s) failed: %s", _tbl, exc, exc_info=True)
                with self._lock:
                    self._cursor = None
                self._last_periodic_prune_ts = _now_mono
                logger.debug(
                    "BG poller: periodic dedup reset (every %.0fs)",
                    _DEDUP_RESET_INTERVAL_S,
                )
            elif self._last_periodic_prune_ts == 0:
                # Initialise timer on first poll
                self._last_periodic_prune_ts = _now_mono

        logger.info("Background poll loop exited")
