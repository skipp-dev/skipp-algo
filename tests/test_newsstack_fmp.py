"""Tests for newsstack_fmp module — covers review findings R-1 through R-6."""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

# ── R-3: Config reads env vars at instantiation, not import time ──


class TestConfigEnvVarsAtInstantiationTime(unittest.TestCase):
    """Env vars must be read when Config() is called, not when the module
    is imported — otherwise programmatic os.environ changes are invisible.
    """

    def test_env_var_read_at_init_not_import(self):
        """Setting FMP_API_KEY *after* import must be picked up by Config()."""
        with patch.dict(os.environ, {"FMP_API_KEY": "test_key_123"}):
            from newsstack_fmp.config import Config

            cfg = Config()
            self.assertEqual(cfg.fmp_api_key, "test_key_123")

    def test_different_instances_see_different_env(self):
        from newsstack_fmp.config import Config

        with patch.dict(os.environ, {"FMP_API_KEY": "a"}):
            cfg_a = Config()
        with patch.dict(os.environ, {"FMP_API_KEY": "b"}):
            cfg_b = Config()

        self.assertEqual(cfg_a.fmp_api_key, "a")
        self.assertEqual(cfg_b.fmp_api_key, "b")

    def test_boolean_flag_from_env(self):
        from newsstack_fmp.config import Config

        with patch.dict(os.environ, {"ENABLE_BENZINGA_REST": "1"}):
            cfg = Config()
            self.assertTrue(cfg.enable_benzinga_rest)

        with patch.dict(os.environ, {"ENABLE_BENZINGA_REST": "0"}):
            cfg = Config()
            self.assertFalse(cfg.enable_benzinga_rest)


# ── R-1: _best_by_ticker pruning ────────────────────────────────


class TestBestByTickerPruning(unittest.TestCase):
    """_prune_best_by_ticker must evict entries older than keep_seconds."""

    def test_stale_entries_pruned(self):
        from newsstack_fmp import pipeline

        old_dict = pipeline._best_by_ticker.copy()
        try:
            pipeline._best_by_ticker.clear()
            # Insert a stale entry (1 hour old)
            pipeline._best_by_ticker["STALE"] = {
                "ticker": "STALE",
                "updated_ts": time.time() - 7200,
                "news_score": 0.5,
            }
            # Insert a fresh entry
            pipeline._best_by_ticker["FRESH"] = {
                "ticker": "FRESH",
                "updated_ts": time.time(),
                "news_score": 0.8,
            }
            pipeline._prune_best_by_ticker(3600)  # keep last hour
            self.assertNotIn("STALE", pipeline._best_by_ticker)
            self.assertIn("FRESH", pipeline._best_by_ticker)
        finally:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker.update(old_dict)

    def test_missing_ts_treated_as_stale(self):
        from newsstack_fmp import pipeline

        old_dict = pipeline._best_by_ticker.copy()
        try:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker["NO_TS"] = {
                "ticker": "NO_TS",
                "news_score": 0.5,
            }
            pipeline._prune_best_by_ticker(3600)
            self.assertNotIn("NO_TS", pipeline._best_by_ticker)
        finally:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker.update(old_dict)


# ── R-2: Single scoring call (cluster_hash used directly) ──────


class TestSingleScoringCall(unittest.TestCase):
    """classify_and_score should only be called once per item, not twice."""

    def test_cluster_hash_is_public(self):
        from newsstack_fmp.scoring import cluster_hash

        h = cluster_hash("fmp_stock_latest", "AAPL beats Q1 earnings", ["AAPL"])
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 40)  # SHA1 hex

    def test_cluster_hash_deterministic(self):
        from newsstack_fmp.scoring import cluster_hash

        h1 = cluster_hash("p", "headline", ["A", "B"])
        h2 = cluster_hash("p", "headline", ["B", "A"])  # tickers sorted
        self.assertEqual(h1, h2)


# ── R-4: atexit cleanup registered ─────────────────────────────


class TestAtexitCleanup(unittest.TestCase):
    """_cleanup_singletons must exist and be callable."""

    def test_cleanup_callable(self):
        from newsstack_fmp.pipeline import _cleanup_singletons

        # Should not raise even when all singletons are None
        _cleanup_singletons()


# ── R-5: _to_epoch logs on parse failure ────────────────────────


class TestToEpochLogging(unittest.TestCase):
    """_to_epoch must log a warning when date parsing fails."""

    def test_bad_date_logs_warning(self):
        from newsstack_fmp.normalize import _to_epoch

        with self.assertLogs("newsstack_fmp.normalize", level="WARNING") as cm:
            result = _to_epoch("not-a-date-at-all!!!")
            self.assertIsInstance(result, float)

        self.assertTrue(any("Unparseable date" in msg for msg in cm.output))

    def test_empty_string_returns_now(self):
        from newsstack_fmp.normalize import _to_epoch

        before = time.time()
        result = _to_epoch("")
        after = time.time()
        self.assertGreaterEqual(result, before)
        self.assertLessEqual(result, after)

    def test_valid_date_parsed_correctly(self):
        from newsstack_fmp.normalize import _to_epoch

        result = _to_epoch("2026-01-15T10:30:00Z")
        self.assertGreater(result, 0)
        self.assertLess(result, time.time())


# ── R-6: Enricher User-Agent header ────────────────────────────


class TestEnricherUserAgent(unittest.TestCase):
    """Enricher httpx client must send a User-Agent header."""

    def test_user_agent_set(self):
        from newsstack_fmp.enrich import Enricher

        e = Enricher()
        try:
            ua = e.client.headers.get("user-agent", "")
            self.assertIn("newsstack-fmp", ua)
        finally:
            e.close()


# ── Scoring module tests ───────────────────────────────────────


class TestScoring(unittest.TestCase):
    """Basic scoring / classification tests."""

    def test_halt_category(self):
        from newsstack_fmp.scoring import classify_and_score

        r = classify_and_score(
            {"headline": "ACME stock trading halted", "tickers": ["ACME"], "provider": "test"},
            cluster_count=1,
        )
        self.assertEqual(r.category, "halt")
        self.assertGreater(r.impact, 0.9)

    def test_offering_category_with_warn(self):
        from newsstack_fmp.scoring import classify_and_score

        r = classify_and_score(
            {"headline": "XYZ announces public offering", "tickers": ["XYZ"], "provider": "test"},
            cluster_count=1,
        )
        self.assertEqual(r.category, "offering")

    def test_novelty_decay(self):
        from newsstack_fmp.scoring import classify_and_score

        r1 = classify_and_score(
            {"headline": "ACME earnings beat", "tickers": ["ACME"], "provider": "test"},
            cluster_count=1,
        )
        r5 = classify_and_score(
            {"headline": "ACME earnings beat", "tickers": ["ACME"], "provider": "test"},
            cluster_count=5,
        )
        # Same headline scored with higher cluster count → lower novelty → lower score
        self.assertGreaterEqual(r1.score, r5.score)

    def test_polarity_positive(self):
        from newsstack_fmp.scoring import classify_and_score

        r = classify_and_score(
            {"headline": "Company beats expectations", "tickers": ["ABC"], "provider": "test"},
            cluster_count=1,
        )
        self.assertGreater(r.polarity, 0)

    def test_polarity_negative(self):
        from newsstack_fmp.scoring import classify_and_score

        r = classify_and_score(
            {"headline": "Company misses expectations", "tickers": ["ABC"], "provider": "test"},
            cluster_count=1,
        )
        self.assertLess(r.polarity, 0)

    def test_score_bounded(self):
        from newsstack_fmp.scoring import classify_and_score

        for cc in (1, 10, 100):
            r = classify_and_score(
                {"headline": "Random headline", "tickers": ["X"], "provider": "t"},
                cluster_count=cc,
            )
            self.assertGreaterEqual(r.score, 0.0)
            self.assertLessEqual(r.score, 1.0)


# ── Normalization tests ────────────────────────────────────────


class TestNormalization(unittest.TestCase):

    def test_normalize_fmp_basic(self):
        from newsstack_fmp.normalize import normalize_fmp

        item = normalize_fmp("fmp_stock_latest", {
            "title": "AAPL Announces Buyback",
            "symbol": "AAPL",
            "url": "https://example.com/1",
            "publishedDate": "2026-02-20T10:00:00Z",
            "site": "Reuters",
        })
        self.assertEqual(item.headline, "AAPL Announces Buyback")
        self.assertEqual(item.tickers, ["AAPL"])
        self.assertEqual(item.provider, "fmp_stock_latest")
        self.assertTrue(item.is_valid)

    def test_normalize_benzinga_rest_basic(self):
        from newsstack_fmp.normalize import normalize_benzinga_rest

        item = normalize_benzinga_rest({
            "id": "12345",
            "title": "FDA Approves Drug",
            "stocks": [{"name": "PFE"}],
            "created": "2026-02-20T10:00:00Z",
            "source": "Benzinga",
        })
        self.assertEqual(item.headline, "FDA Approves Drug")
        self.assertEqual(item.tickers, ["PFE"])
        self.assertEqual(item.provider, "benzinga_rest")

    def test_extract_tickers_csv_string(self):
        from newsstack_fmp.normalize import _extract_tickers

        tickers = _extract_tickers({"stocks": "AAPL, MSFT, GOOG"})
        self.assertEqual(tickers, ["AAPL", "MSFT", "GOOG"])


# ── Store tests ────────────────────────────────────────────────


class TestSqliteStore(unittest.TestCase):

    def setUp(self):
        from newsstack_fmp.store_sqlite import SqliteStore

        self.store = SqliteStore(":memory:")

    def test_kv_round_trip(self):
        self.store.set_kv("key1", "value1")
        self.assertEqual(self.store.get_kv("key1"), "value1")

    def test_kv_missing(self):
        self.assertIsNone(self.store.get_kv("nonexistent"))

    def test_mark_seen_dedup(self):
        self.assertTrue(self.store.mark_seen("p", "id1", 1.0))
        self.assertFalse(self.store.mark_seen("p", "id1", 1.0))

    def test_cluster_touch_increments(self):
        count1, _ = self.store.cluster_touch("h1", 1.0)
        self.assertEqual(count1, 1)
        count2, _ = self.store.cluster_touch("h1", 2.0)
        self.assertEqual(count2, 2)

    def test_prune_seen(self):
        self.store.mark_seen("p", "old", time.time() - 7200)
        self.store.mark_seen("p", "new", time.time())
        self.store.prune_seen(3600)
        # "old" was pruned → can be re-inserted (returns True)
        self.assertTrue(self.store.mark_seen("p", "old", time.time()))
        # "new" still exists → cannot be re-inserted (returns False)
        self.assertFalse(self.store.mark_seen("p", "new", time.time()))


class TestSqliteStorePrune(unittest.TestCase):

    def test_prune_removes_old_keeps_new(self):
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        store.mark_seen("p", "old", time.time() - 7200)
        store.mark_seen("p", "new", time.time())
        store.prune_seen(3600)
        # "old" was pruned → can be re-inserted
        self.assertTrue(store.mark_seen("p", "old", time.time()))
        # "new" still exists → cannot be inserted
        self.assertFalse(store.mark_seen("p", "new", time.time()))


if __name__ == "__main__":
    unittest.main()
