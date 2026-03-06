"""SQLite-backed state store: cursor tracking, de-duplication, novelty clusters.

Uses WAL mode + NORMAL synchronous for maximum write throughput while
retaining crash safety.

Implements a **singleton-per-path** pattern so that all callers within
the same process share a single connection + threading lock, avoiding
"database is locked" errors from concurrent connections.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seen (
  provider TEXT NOT NULL,
  item_id TEXT NOT NULL,
  ts REAL NOT NULL,
  PRIMARY KEY(provider, item_id)
);
CREATE INDEX IF NOT EXISTS idx_seen_ts ON seen(ts);

CREATE TABLE IF NOT EXISTS clusters (
  hash TEXT PRIMARY KEY,
  first_ts REAL NOT NULL,
  last_ts REAL NOT NULL,
  count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clusters_last_ts ON clusters(last_ts);
"""

# ── Retry parameters ───────────────────────────────────────────
_MAX_RETRIES = 5
_BASE_BACKOFF_S = 0.1  # 100ms, 200ms, 400ms, 800ms, 1600ms

# ── Singleton registry ─────────────────────────────────────────
_instances: dict[str, SqliteStore] = {}
_instances_lock = threading.Lock()


def _retry_on_locked(fn):
    """Decorator: retry on OperationalError / ProgrammingError (closed db).

    On ``ProgrammingError`` the connection is transparently reopened via
    ``_reconnect()`` before the retry.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        for attempt in range(_MAX_RETRIES):
            try:
                return fn(self, *args, **kwargs)
            except sqlite3.ProgrammingError:
                # Connection was closed — reconnect transparently.
                _log = logger.info if attempt == 0 else logger.warning
                _log(
                    "SQLite connection closed — reconnecting (%s, attempt %d/%d)",
                    fn.__name__, attempt + 1, _MAX_RETRIES,
                )
                try:
                    self._reconnect()
                except Exception as re_exc:
                    logger.error("_reconnect failed: %s", re_exc)
                    if attempt >= _MAX_RETRIES - 1:
                        raise
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BASE_BACKOFF_S)
                    continue
                raise
            except sqlite3.OperationalError:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BASE_BACKOFF_S * (2 ** attempt))
                    continue
                logger.error(
                    "SQLite OperationalError after %d retries in %s",
                    _MAX_RETRIES, fn.__name__,
                )
                raise
    return wrapper


class SqliteStore:
    """Key-value + dedup + novelty store backed by SQLite.

    Use ``SqliteStore.get_instance(path)`` to obtain a shared singleton.
    Direct ``SqliteStore(path)`` also works but returns the singleton.
    """

    def __new__(cls, path: str) -> SqliteStore:
        """Return the singleton instance for the resolved *path*.

        ``:memory:`` databases are exempt from singleton caching because
        each SQLite ``:memory:`` connection is independent.
        """
        if path == ":memory:":
            inst = super().__new__(cls)
            inst._initialized = False  # type: ignore[attr-defined]
            return inst
        resolved = os.path.realpath(path)
        with _instances_lock:
            inst = _instances.get(resolved)
            if inst is not None:
                return inst
            inst = super().__new__(cls)
            inst._initialized = False  # type: ignore[attr-defined]
            _instances[resolved] = inst
            return inst

    def __init__(self, path: str) -> None:
        if self._initialized:  # type: ignore[has-type]
            return
        self._initialized = True
        self._lock = threading.RLock()
        self._path = path if path == ":memory:" else os.path.realpath(path)
        self.conn = self._connect(self._path)

        # Quick integrity check — if the DB is corrupted, delete and
        # recreate rather than silently dropping every article.
        try:
            result = self.conn.execute("PRAGMA quick_check;").fetchone()
            if result and result[0] != "ok":
                raise sqlite3.DatabaseError(f"integrity: {result[0]}")
        except sqlite3.DatabaseError as exc:
            logger.warning("SQLite DB corrupt (%s) — recreating: %s", self._path, exc)
            self.conn.close()
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(self._path + suffix)
                except FileNotFoundError:
                    pass
            self.conn = self._connect(self._path)

        self.conn.executescript(SCHEMA)
        logger.debug("SqliteStore singleton ready: %s", self._path)

    @classmethod
    def get_instance(cls, path: str) -> SqliteStore:
        """Explicit singleton accessor (equivalent to ``SqliteStore(path)``)."""
        return cls(path)

    @staticmethod
    def _connect(path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=15000;")
        return conn

    def _reconnect(self) -> None:
        """Re-open a closed connection and re-apply schema."""
        with self._lock:
            # Double-check: another thread may have already reconnected.
            try:
                self.conn.execute("SELECT 1")
                return  # already alive
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                pass
            try:
                self.conn.close()
            except Exception:
                pass
            logger.info("Reconnecting SQLite: %s", self._path)
            self.conn = self._connect(self._path)
            self.conn.executescript(SCHEMA)

    # ── Key-value ───────────────────────────────────────────────

    @_retry_on_locked
    def get_kv(self, k: str) -> str | None:
        with self._lock:
            row = self.conn.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    @_retry_on_locked
    def set_kv(self, k: str, v: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, v),
            )

    # ── Dedup ───────────────────────────────────────────────────

    @_retry_on_locked
    def mark_seen(self, provider: str, item_id: str, ts: float) -> bool:
        """Return True if newly inserted; False if already seen."""
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO seen(provider,item_id,ts) VALUES(?,?,?)",
                    (provider, item_id, ts),
                )
                return True
        except sqlite3.IntegrityError:
            return False

    # ── Novelty clustering ──────────────────────────────────────

    @_retry_on_locked
    def cluster_touch(self, h: str, ts: float) -> tuple[int, float]:
        """Atomically touch a cluster and return ``(count, first_ts)``."""
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute(
                    "INSERT INTO clusters(hash, first_ts, last_ts, count) VALUES(?,?,?,1) "
                    "ON CONFLICT(hash) DO UPDATE SET last_ts=MAX(clusters.last_ts, excluded.last_ts), count=count+1",
                    (h, ts, ts),
                )
                row = self.conn.execute(
                    "SELECT count, first_ts FROM clusters WHERE hash=?", (h,)
                ).fetchone()
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
        return (row[0], row[1])

    # ── Maintenance ─────────────────────────────────────────────

    @_retry_on_locked
    def prune_seen(self, keep_seconds: float) -> None:
        cutoff = time.time() - keep_seconds
        with self._lock:
            self.conn.execute("DELETE FROM seen WHERE ts < ?", (cutoff,))
            # Checkpoint WAL to keep file size bounded
            self.conn.execute("PRAGMA wal_checkpoint(PASSIVE);")

    @_retry_on_locked
    def prune_clusters(self, keep_seconds: float) -> None:
        cutoff = time.time() - keep_seconds
        with self._lock:
            self.conn.execute("DELETE FROM clusters WHERE last_ts < ?", (cutoff,))

    def close(self, *, force: bool = False) -> None:
        """Close the connection and remove from singleton registry.

        The instance stays in the registry so that existing references
        can auto-reconnect via ``_reconnect()`` rather than hitting a
        permanently dead connection.

        For shared on-disk singleton stores, ``close()`` defaults to a
        no-op to avoid frequent close/reopen churn in long-running apps.
        Pass ``force=True`` for explicit shutdown workflows (e.g. deleting
        the database files during a reset).
        """
        if self._path != ":memory:" and not force:
            logger.debug("Ignoring close() on shared SqliteStore: %s", self._path)
            return
        try:
            self.conn.close()
        except Exception:
            pass
