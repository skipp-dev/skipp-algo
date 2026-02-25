"""SQLite-backed state store: cursor tracking, de-duplication, novelty clusters.

Uses WAL mode + NORMAL synchronous for maximum write throughput while
retaining crash safety.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Optional, Tuple

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


class SqliteStore:
    """Key-value + dedup + novelty store backed by SQLite."""

    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.conn.executescript(SCHEMA)

    # ── Key-value ───────────────────────────────────────────────

    def get_kv(self, k: str) -> Optional[str]:
        row = self.conn.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def set_kv(self, k: str, v: str) -> None:
        self.conn.execute(
            "INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, v),
        )

    # ── Dedup ───────────────────────────────────────────────────

    def mark_seen(self, provider: str, item_id: str, ts: float) -> bool:
        """Return True if newly inserted; False if already seen."""
        try:
            self.conn.execute(
                "INSERT INTO seen(provider,item_id,ts) VALUES(?,?,?)",
                (provider, item_id, ts),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    # ── Novelty clustering ──────────────────────────────────────

    def cluster_touch(self, h: str, ts: float) -> Tuple[int, float]:
        """Atomically touch a cluster and return ``(count, first_ts)``.

        Uses UPSERT inside a single IMMEDIATE transaction so the
        returned count is never stale when another process touches
        the same hash concurrently.
        """
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "INSERT INTO clusters(hash, first_ts, last_ts, count) VALUES(?,?,?,1) "
                "ON CONFLICT(hash) DO UPDATE SET last_ts=excluded.last_ts, count=count+1",
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

    def prune_seen(self, keep_seconds: float) -> None:
        cutoff = time.time() - keep_seconds
        self.conn.execute("DELETE FROM seen WHERE ts < ?", (cutoff,))

    def prune_clusters(self, keep_seconds: float) -> None:
        cutoff = time.time() - keep_seconds
        self.conn.execute("DELETE FROM clusters WHERE last_ts < ?", (cutoff,))

    def close(self) -> None:
        self.conn.close()
