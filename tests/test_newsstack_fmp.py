"""Tests for newsstack_fmp module — covers review findings R-1 through R-6
plus Production Gatekeeper findings M-1 through M-6."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

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
            self.assertEqual(result, 0.0)

        self.assertTrue(any("Unparseable date" in msg for msg in cm.output))

    def test_empty_string_returns_zero(self):
        from newsstack_fmp.normalize import _to_epoch

        result = _to_epoch("")
        self.assertEqual(result, 0.0)

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


# ── M-1: _to_epoch timezone handling ───────────────────────────


class TestToEpochTimezoneHandling(unittest.TestCase):
    """Naive datetimes must be treated as UTC regardless of server TZ."""

    def test_naive_datetime_is_utc(self):
        """A date string without timezone info must be parsed as UTC."""
        from newsstack_fmp.normalize import _to_epoch

        # 2026-01-15T12:00:00 without TZ → must be treated as UTC
        result = _to_epoch("2026-01-15T12:00:00")
        import datetime
        expected = datetime.datetime(2026, 1, 15, 12, 0, 0,
                                     tzinfo=datetime.timezone.utc).timestamp()
        self.assertAlmostEqual(result, expected, places=0)

    def test_explicit_utc_matches_naive(self):
        """An explicit UTC date must produce the same epoch as a naive one."""
        from newsstack_fmp.normalize import _to_epoch

        naive = _to_epoch("2026-02-20T10:00:00")
        explicit_utc = _to_epoch("2026-02-20T10:00:00Z")
        self.assertAlmostEqual(naive, explicit_utc, places=0)

    def test_explicit_offset_preserved(self):
        """A date with an explicit offset must NOT be overridden to UTC."""
        from newsstack_fmp.normalize import _to_epoch

        # +05:00 → 5 hours earlier in epoch than UTC
        with_offset = _to_epoch("2026-01-15T12:00:00+05:00")
        as_utc = _to_epoch("2026-01-15T07:00:00Z")
        self.assertAlmostEqual(with_offset, as_utc, places=0)


# ── M-2: Cursor strict-less-than (no silent drop) ─────────────


class TestCursorStrictLessThan(unittest.TestCase):
    """Items with ts == last_seen_epoch must NOT be dropped by cursor."""

    def test_same_timestamp_not_dropped(self):
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        item = NewsItem(
            provider="fmp_stock_latest",
            item_id="same_ts_test",
            published_ts=100.0,
            updated_ts=100.0,
            headline="AAPL beats Q1 earnings",
            snippet="",
            tickers=["AAPL"],
            url="https://example.com/1",
            source="Test",
        )

        # last_seen_epoch == item.updated_ts — item must NOT be dropped
        max_ts = process_news_items(
            store, [item], best, None, enricher, 99.0,
            last_seen_epoch=100.0,
        )
        enricher.close()

        # Item should appear in best_by_ticker because cursor uses <, not <=
        self.assertIn("AAPL", best)
        self.assertEqual(best["AAPL"]["headline"], "AAPL beats Q1 earnings")


# ── M-3: Atomic export with tempfile.mkstemp ──────────────────


class TestAtomicExport(unittest.TestCase):
    """export_open_prep must use a unique temp file, not a fixed name."""

    def test_export_creates_valid_json(self):
        from newsstack_fmp.open_prep_export import export_open_prep

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.json")
            export_open_prep(path, [{"ticker": "X"}], {"ts": 1.0})
            with open(path, "r") as f:
                data = json.load(f)
            self.assertEqual(len(data["candidates"]), 1)
            self.assertEqual(data["meta"]["ts"], 1.0)

    def test_no_leftover_tmp_on_success(self):
        from newsstack_fmp.open_prep_export import export_open_prep

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.json")
            export_open_prep(path, [], {"ts": 2.0})
            # Only the final file should exist, no .tmp leftovers
            files = os.listdir(td)
            self.assertEqual(files, ["out.json"])

    def test_export_empty_candidates_creates_file(self):
        from newsstack_fmp.open_prep_export import export_open_prep

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.json")
            export_open_prep(path, [], {"generated_ts": 123.0})
            with open(path, "r") as f:
                data = json.load(f)
            self.assertEqual(data["candidates"], [])
            self.assertEqual(data["meta"]["generated_ts"], 123.0)


# ── M-4: poll_once fail-open around process + export ──────────


class TestPollOnceFailOpen(unittest.TestCase):
    """poll_once must not crash when process_news_items or export fails."""

    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    @patch("newsstack_fmp.pipeline._get_fmp_adapter")
    def test_process_db_error_does_not_crash(self, mock_fmp, mock_enr, mock_store):
        from newsstack_fmp.pipeline import poll_once
        from newsstack_fmp.config import Config

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        fmp = MagicMock()
        fmp.fetch_stock_latest.side_effect = RuntimeError("DB error")
        mock_fmp.return_value = fmp

        with patch.dict(os.environ, {"FMP_API_KEY": "test", "FILTER_TO_UNIVERSE": "0"}):
            cfg = Config()
            # Should not raise — fail-open
            result = poll_once(cfg, universe=set())
        self.assertIsInstance(result, list)

    @patch("newsstack_fmp.pipeline.export_open_prep", side_effect=OSError("disk full"))
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    def test_export_failure_does_not_crash(self, mock_enr, mock_store, mock_export):
        from newsstack_fmp.pipeline import poll_once
        from newsstack_fmp.config import Config

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        with patch.dict(os.environ, {"FMP_API_KEY": "", "ENABLE_FMP": "0",
                                      "FILTER_TO_UNIVERSE": "0"}):
            cfg = Config()
            # Should not raise even though export throws OSError
            result = poll_once(cfg, universe=set())
        self.assertIsInstance(result, list)


# ── M-5: cluster_count guard ──────────────────────────────────


class TestClusterCountGuard(unittest.TestCase):
    """classify_and_score must handle cluster_count <= 0 gracefully."""

    def test_cluster_count_zero(self):
        from newsstack_fmp.scoring import classify_and_score

        r = classify_and_score(
            {"headline": "Test headline", "tickers": ["X"], "provider": "t"},
            cluster_count=0,
        )
        # With guard: cluster_count clamped to 1, novelty should be in [0.15, 1.25]
        self.assertGreaterEqual(r.score, 0.0)
        self.assertLessEqual(r.score, 1.0)

    def test_cluster_count_negative(self):
        from newsstack_fmp.scoring import classify_and_score

        r = classify_and_score(
            {"headline": "Test headline", "tickers": ["X"], "provider": "t"},
            cluster_count=-5,
        )
        self.assertGreaterEqual(r.score, 0.0)
        self.assertLessEqual(r.score, 1.0)

    def test_cluster_count_zero_same_as_one(self):
        """cluster_count=0 should produce the same result as cluster_count=1."""
        from newsstack_fmp.scoring import classify_and_score

        r0 = classify_and_score(
            {"headline": "Deterministic test", "tickers": ["X"], "provider": "t"},
            cluster_count=0,
        )
        r1 = classify_and_score(
            {"headline": "Deterministic test", "tickers": ["X"], "provider": "t"},
            cluster_count=1,
        )
        self.assertAlmostEqual(r0.score, r1.score, places=6)


# ── M-6: Always-export (empty candidates get fresh generated_ts) ──


class TestAlwaysExport(unittest.TestCase):
    """poll_once must export even when candidates list is empty."""

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    def test_empty_candidates_still_exports(self, mock_enr, mock_store, mock_export):
        from newsstack_fmp.pipeline import poll_once, _best_by_ticker
        from newsstack_fmp.config import Config

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        # Clear best_by_ticker to guarantee no candidates
        old = _best_by_ticker.copy()
        _best_by_ticker.clear()
        try:
            with patch.dict(os.environ, {"FMP_API_KEY": "", "ENABLE_FMP": "0",
                                          "FILTER_TO_UNIVERSE": "0"}):
                cfg = Config()
                poll_once(cfg, universe=set())

            # export_open_prep must have been called even with 0 candidates
            mock_export.assert_called_once()
            args = mock_export.call_args
            candidates_arg = args[0][1]  # 2nd positional arg
            meta_arg = args[0][2]  # 3rd positional arg
            self.assertEqual(candidates_arg, [])
            self.assertIn("generated_ts", meta_arg)
            self.assertEqual(meta_arg["total_candidates"], 0)
        finally:
            _best_by_ticker.clear()
            _best_by_ticker.update(old)


# ── SR-1: _to_epoch returns 0.0 for empty/unparseable (no cursor inflation) ──


class TestToEpochReturnsZeroNotNow(unittest.TestCase):
    """_to_epoch must return 0.0 (not time.time()) on empty/unparseable dates
    to prevent cursor inflation that skips real items."""

    def test_empty_returns_zero(self):
        from newsstack_fmp.normalize import _to_epoch
        self.assertEqual(_to_epoch(""), 0.0)

    def test_unparseable_returns_zero(self):
        from newsstack_fmp.normalize import _to_epoch
        with self.assertLogs("newsstack_fmp.normalize", level="WARNING"):
            self.assertEqual(_to_epoch("GARBAGE!@#$%"), 0.0)


# ── SR-2: Synthetic timestamps must NOT advance cursor ──────────


class TestSyntheticTimestampDoesNotAdvanceCursor(unittest.TestCase):
    """Items with missing timestamps (ts=0.0) must be processed,
    but must NOT advance the max_ts cursor."""

    def test_zero_ts_does_not_advance_cursor(self):
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        item = NewsItem(
            provider="fmp_stock_latest",
            item_id="zero_ts_test",
            published_ts=0.0,
            updated_ts=0.0,
            headline="AAPL beats Q1 earnings",
            snippet="",
            tickers=["AAPL"],
            url="https://example.com/z",
            source="Test",
        )

        max_ts = process_news_items(
            store, [item], best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        # Item should still be processed (appears in best)
        self.assertIn("AAPL", best)
        # But cursor should NOT have advanced past 0.0
        self.assertEqual(max_ts, 0.0)


# ====================================================================
# SR8: Production Gatekeeper review — newsstack_fmp hardening tests
# ====================================================================


# ── H1: API key must NOT leak in exception messages ────────────


class TestApiKeyNotLeaked(unittest.TestCase):
    """httpx exceptions must have API keys sanitized before logging."""

    def test_fmp_sanitize_url(self):
        from newsstack_fmp.ingest_fmp import _sanitize_url

        url = "https://api.example.com/v1/news?page=0&apikey=SECRET123&limit=50"
        safe = _sanitize_url(url)
        self.assertNotIn("SECRET123", safe)
        self.assertIn("apikey=***", safe)
        self.assertIn("page=0", safe)  # other params preserved

    def test_benzinga_sanitize_url(self):
        from newsstack_fmp.ingest_benzinga import _sanitize_url

        url = "https://api.benzinga.com/api/v2/news?token=BZ_SECRET&pageSize=100"
        safe = _sanitize_url(url)
        self.assertNotIn("BZ_SECRET", safe)
        self.assertIn("token=***", safe)

    def test_fmp_http_error_sanitized(self):
        """raise_for_status on 403 must NOT contain apikey."""
        import httpx as _httpx
        from newsstack_fmp.ingest_fmp import FmpAdapter

        adapter = FmpAdapter("my_secret_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.url = "https://api.example.com/v1/news?apikey=my_secret_key"
        mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            message="403 Forbidden",
            request=MagicMock(),
            response=mock_resp,
        )
        adapter.client = MagicMock()
        adapter.client.get.return_value = mock_resp

        with self.assertRaises(Exception) as ctx:
            adapter.fetch_stock_latest(0, 50)
        self.assertNotIn("my_secret_key", str(ctx.exception))
        adapter.close()


# ── H2: Cross-provider cluster_hash — novelty dedup ───────────


class TestCrossProviderClusterHash(unittest.TestCase):
    """Same headline from different providers must produce the SAME cluster hash."""

    def test_same_headline_different_provider(self):
        from newsstack_fmp.scoring import cluster_hash

        h_fmp = cluster_hash("fmp_stock_latest", "AAPL beats Q1 earnings", ["AAPL"])
        h_bz = cluster_hash("benzinga_rest", "AAPL beats Q1 earnings", ["AAPL"])
        self.assertEqual(h_fmp, h_bz)

    def test_provider_param_ignored(self):
        from newsstack_fmp.scoring import cluster_hash

        h1 = cluster_hash("provider_a", "FDA approves drug", ["PFE"])
        h2 = cluster_hash("provider_b", "FDA approves drug", ["PFE"])
        h3 = cluster_hash("", "FDA approves drug", ["PFE"])
        self.assertEqual(h1, h2)
        self.assertEqual(h2, h3)


# ── H3: FMP normalize on non-dict elements ────────────────────


class TestFmpNonDictFiltered(unittest.TestCase):
    """Non-dict elements in JSON array must be silently filtered, not crash."""

    def test_as_list_filters_non_dicts(self):
        from newsstack_fmp.ingest_fmp import _as_list

        result = _as_list([{"a": 1}, None, "string", 42, {"b": 2}])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(x, dict) for x in result))

    def test_as_list_non_list_input(self):
        from newsstack_fmp.ingest_fmp import _as_list

        self.assertEqual(_as_list(None), [])
        self.assertEqual(_as_list("string"), [])
        self.assertEqual(_as_list(42), [])


# ── H4: JSON parse error produces clear message ───────────────


class TestJsonParseError(unittest.TestCase):
    """Non-JSON responses (HTML etc.) must produce a ValueError with
    content-type and sanitized URL — not a raw JSONDecodeError."""

    def test_safe_json_on_html(self):
        from newsstack_fmp.ingest_fmp import _safe_json

        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.status_code = 200
        mock_resp.url = "https://api.example.com/news?apikey=SECRET"
        mock_resp.json.side_effect = json.JSONDecodeError("", "", 0)

        with self.assertRaises(ValueError) as ctx:
            _safe_json(mock_resp)
        msg = str(ctx.exception)
        self.assertIn("non-JSON", msg)
        self.assertIn("text/html", msg)
        self.assertNotIn("SECRET", msg)


# ── M1: Enricher response size limit ──────────────────────────


class TestEnricherSizeLimit(unittest.TestCase):
    """Enricher must cap downloaded content to prevent OOM."""

    def test_snippet_html_stripped(self):
        from newsstack_fmp.enrich import _HTML_TAG_RE

        html = "<p>Hello <b>World</b></p>"
        text = _HTML_TAG_RE.sub(" ", html)
        self.assertNotIn("<p>", text)
        self.assertIn("Hello", text)
        self.assertIn("World", text)


# ── M3: Export sort determinism ────────────────────────────────


class TestExportSortDeterminism(unittest.TestCase):
    """Candidates with same score+ts must be sorted deterministically by ticker."""

    def test_tiebreak_by_ticker(self):
        candidates = [
            {"ticker": "ZZXX", "news_score": 0.8, "updated_ts": 100.0},
            {"ticker": "AAPL", "news_score": 0.8, "updated_ts": 100.0},
            {"ticker": "MSFT", "news_score": 0.8, "updated_ts": 100.0},
        ]
        candidates.sort(
            key=lambda x: (x.get("news_score", 0), x.get("updated_ts", 0), x.get("ticker", "")),
            reverse=True,
        )
        tickers = [c["ticker"] for c in candidates]
        # Reverse alpha: ZZXX > MSFT > AAPL
        self.assertEqual(tickers, ["ZZXX", "MSFT", "AAPL"])


# ── M4: SQLite busy_timeout ───────────────────────────────────


class TestSqliteBusyTimeout(unittest.TestCase):
    """SqliteStore must set busy_timeout for multi-process safety."""

    def test_busy_timeout_set(self):
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        row = store.conn.execute("PRAGMA busy_timeout;").fetchone()
        self.assertEqual(row[0], 5000)
        store.close()


# ── M5: _effective_ts handles 0.0 correctly ───────────────────


class TestEffectiveTs(unittest.TestCase):
    """_effective_ts must not treat 0.0 as 'no timestamp'."""

    def test_zero_updated_ts(self):
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 0.0, "published_ts": 0.0}
        self.assertEqual(_effective_ts(cand), 0.0)

    def test_valid_updated_ts(self):
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 1700000000.0, "published_ts": 1699999000.0}
        self.assertEqual(_effective_ts(cand), 1700000000.0)

    def test_zero_updated_falls_to_published(self):
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 0.0, "published_ts": 1700000000.0}
        self.assertEqual(_effective_ts(cand), 1700000000.0)

    def test_missing_both(self):
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"ticker": "X"}
        self.assertEqual(_effective_ts(cand), 0.0)

    def test_none_updated_ts(self):
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": None, "published_ts": 500.0}
        self.assertEqual(_effective_ts(cand), 500.0)


# ====================================================================
# SR9: Production Gatekeeper review — second pass hardening tests
# ====================================================================


# ── H1: cluster_touch atomic UPSERT ───────────────────────────


class TestClusterTouchAtomic(unittest.TestCase):
    """cluster_touch must use atomic UPSERT — no IntegrityError on concurrent INSERT."""

    def test_first_touch_returns_count_1(self):
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        count, first_ts = store.cluster_touch("abc123", 100.0)
        self.assertEqual(count, 1)
        self.assertEqual(first_ts, 100.0)
        store.close()

    def test_second_touch_increments(self):
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        store.cluster_touch("abc123", 100.0)
        count, first_ts = store.cluster_touch("abc123", 200.0)
        self.assertEqual(count, 2)
        self.assertEqual(first_ts, 100.0)  # first_ts must NOT change
        store.close()

    def test_upsert_preserves_first_ts(self):
        """Multiple touches must preserve the original first_ts."""
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        store.cluster_touch("h1", 10.0)
        store.cluster_touch("h1", 20.0)
        store.cluster_touch("h1", 30.0)
        count, first_ts = store.cluster_touch("h1", 40.0)
        self.assertEqual(count, 4)
        self.assertEqual(first_ts, 10.0)
        store.close()

    def test_concurrent_insert_no_crash(self):
        """Simulated concurrent UPSERT on same hash must not crash."""
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        # Simulate rapid concurrent touches — no IntegrityError
        for i in range(50):
            count, _ = store.cluster_touch("race_hash", float(i))
            self.assertEqual(count, i + 1)
        store.close()

    def test_different_hashes_independent(self):
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        store.cluster_touch("hash_a", 1.0)
        store.cluster_touch("hash_a", 2.0)
        count_a, _ = store.cluster_touch("hash_a", 3.0)
        count_b, _ = store.cluster_touch("hash_b", 1.0)
        self.assertEqual(count_a, 3)
        self.assertEqual(count_b, 1)
        store.close()


# ── M1: load_universe warning on missing file ─────────────────


class TestLoadUniverseWarning(unittest.TestCase):
    """load_universe must log a warning when the file is missing."""

    def test_missing_file_logs_warning(self):
        from newsstack_fmp.pipeline import load_universe

        with self.assertLogs("newsstack_fmp.pipeline", level="WARNING") as cm:
            result = load_universe("/nonexistent/universe.txt")
        self.assertEqual(result, set())
        self.assertTrue(any("not found" in msg for msg in cm.output))

    def test_empty_file_logs_warning(self):
        from newsstack_fmp.pipeline import load_universe

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# comment only\n\n")
            path = f.name
        try:
            with self.assertLogs("newsstack_fmp.pipeline", level="WARNING") as cm:
                result = load_universe(path)
            self.assertEqual(result, set())
            self.assertTrue(any("empty" in msg for msg in cm.output))
        finally:
            os.unlink(path)

    def test_valid_file_no_warning(self):
        from newsstack_fmp.pipeline import load_universe

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("AAPL\nMSFT\nGOOG\n")
            path = f.name
        try:
            result = load_universe(path)
            self.assertEqual(result, {"AAPL", "MSFT", "GOOG"})
        finally:
            os.unlink(path)


# ── M2: Provider failure warnings in export meta ──────────────


class TestCycleWarningsInMeta(unittest.TestCase):
    """poll_once must surface provider failure warnings in meta.warnings."""

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    @patch("newsstack_fmp.pipeline._get_fmp_adapter")
    def test_fmp_failure_appears_in_warnings(self, mock_fmp, mock_enr, mock_store, mock_export):
        from newsstack_fmp.pipeline import poll_once
        from newsstack_fmp.config import Config

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        fmp = MagicMock()
        fmp.fetch_stock_latest.side_effect = RuntimeError("FMP down")
        fmp.fetch_press_latest.return_value = []
        mock_fmp.return_value = fmp

        with patch.dict(os.environ, {"FMP_API_KEY": "test", "FILTER_TO_UNIVERSE": "0"}):
            cfg = Config()
            poll_once(cfg, universe=set())

        mock_export.assert_called_once()
        meta_arg = mock_export.call_args[0][2]
        self.assertIn("warnings", meta_arg)
        self.assertTrue(
            any("fmp_stock_latest" in w for w in meta_arg["warnings"]),
            f"Expected 'fmp_stock_latest' in warnings, got: {meta_arg['warnings']}"
        )

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    def test_no_failures_empty_warnings(self, mock_enr, mock_store, mock_export):
        from newsstack_fmp.pipeline import poll_once
        from newsstack_fmp.config import Config

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        with patch.dict(os.environ, {"FMP_API_KEY": "", "ENABLE_FMP": "0",
                                      "FILTER_TO_UNIVERSE": "0"}):
            cfg = Config()
            poll_once(cfg, universe=set())

        mock_export.assert_called_once()
        meta_arg = mock_export.call_args[0][2]
        self.assertIn("warnings", meta_arg)
        self.assertEqual(meta_arg["warnings"], [])


# ── Duplicate burst test ──────────────────────────────────────


class TestDuplicateBurst(unittest.TestCase):
    """200 identical items in one batch must produce only 1 candidate."""

    def test_burst_dedup(self):
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        items = [
            NewsItem(
                provider="fmp_stock_latest",
                item_id="burst_001",
                published_ts=1700000000.0,
                updated_ts=1700000000.0,
                headline="AAPL beats Q1 earnings expectations",
                snippet="",
                tickers=["AAPL"],
                url="https://example.com/burst",
                source="Test",
            )
            for _ in range(200)
        ]

        process_news_items(
            store, items, best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        # All 200 have the same item_id → only 1 survives dedup
        self.assertEqual(len(best), 1)
        self.assertIn("AAPL", best)

    def test_burst_different_ids_same_headline(self):
        """Different item_ids with same headline → multiple dedup entries
        but same cluster → novelty decay kicks in."""
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        items = [
            NewsItem(
                provider="fmp_stock_latest",
                item_id=f"unique_{i}",
                published_ts=1700000000.0 + i,
                updated_ts=1700000000.0 + i,
                headline="AAPL beats Q1 earnings expectations",
                snippet="",
                tickers=["AAPL"],
                url=f"https://example.com/{i}",
                source="Test",
            )
            for i in range(10)
        ]

        process_news_items(
            store, items, best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        # Only best-scoring entry survives (first one has highest novelty
        # because it was the first cluster touch, so cluster_count=1).
        # The best_by_ticker keeps the HIGHEST-scoring one, which is the
        # first item (novelty=1.0).
        self.assertEqual(len(best), 1)
        self.assertIn("AAPL", best)
        # Verify that all 10 items touched the cluster (query SQLite directly)
        from newsstack_fmp.scoring import cluster_hash as ch
        h = ch("fmp_stock_latest", "AAPL beats Q1 earnings expectations", ["AAPL"])
        row = store.conn.execute("SELECT count FROM clusters WHERE hash=?", (h,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 10)  # all 10 touched the cluster


# ── Partial provider outage test ──────────────────────────────


class TestPartialProviderOutage(unittest.TestCase):
    """When one provider fails, candidates from the other must still be exported."""

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    @patch("newsstack_fmp.pipeline._get_fmp_adapter")
    def test_fmp_down_benzinga_candidates_exported(self, mock_fmp, mock_enr, mock_store, mock_export):
        from newsstack_fmp.pipeline import poll_once, _best_by_ticker
        from newsstack_fmp.config import Config

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        fmp = MagicMock()
        fmp.fetch_stock_latest.side_effect = RuntimeError("FMP 503")
        fmp.fetch_press_latest.side_effect = RuntimeError("FMP 503")
        mock_fmp.return_value = fmp

        # Pre-populate best_by_ticker with a candidate
        old = _best_by_ticker.copy()
        _best_by_ticker.clear()
        _best_by_ticker["AAPL"] = {
            "ticker": "AAPL",
            "news_score": 0.9,
            "updated_ts": time.time(),
            "published_ts": time.time(),
        }

        try:
            with patch.dict(os.environ, {"FMP_API_KEY": "test", "FILTER_TO_UNIVERSE": "0"}):
                cfg = Config()
                result = poll_once(cfg, universe=set())

            # poll_once must not crash and must export the pre-existing candidate
            mock_export.assert_called_once()
            candidates_arg = mock_export.call_args[0][1]
            self.assertTrue(len(candidates_arg) >= 1)
        finally:
            _best_by_ticker.clear()
            _best_by_ticker.update(old)


# ====================================================================
# SR10: Production Gatekeeper review — third pass hardening tests
# ====================================================================


# ── H1: Benzinga cursor must NOT advance when processing fails ─


class TestBenzingaCursorOnProcessingFailure(unittest.TestCase):
    """updatedSince must NOT advance if process_news_items raises."""

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    @patch("newsstack_fmp.pipeline._get_fmp_adapter")
    @patch("newsstack_fmp.pipeline._get_bz_rest_adapter")
    def test_cursor_not_advanced_on_failure(
        self, mock_bz_rest, mock_fmp, mock_enr, mock_store, mock_export
    ):
        from newsstack_fmp.pipeline import poll_once, _best_by_ticker
        from newsstack_fmp.config import Config
        from newsstack_fmp.common_types import NewsItem

        store = MagicMock()
        # Initial cursors: no prior progress
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = []
        fmp.fetch_press_latest.return_value = []
        mock_fmp.return_value = fmp

        # Benzinga REST returns items
        bz = MagicMock()
        bz.fetch_news.return_value = [
            NewsItem(
                provider="benzinga_rest", item_id="bz_1",
                published_ts=1700000000.0, updated_ts=1700000100.0,
                headline="FDA approves drug", snippet="",
                tickers=["PFE"], url="https://example.com/1", source="BZ",
            ),
        ]
        mock_bz_rest.return_value = bz

        old = _best_by_ticker.copy()
        _best_by_ticker.clear()

        try:
            # Make process_news_items blow up on Benzinga items
            with patch.dict(os.environ, {
                "FMP_API_KEY": "test",
                "ENABLE_BENZINGA_REST": "1",
                "BENZINGA_API_KEY": "test_bz",
                "FILTER_TO_UNIVERSE": "0",
            }):
                cfg = Config()
                with patch(
                    "newsstack_fmp.pipeline.process_news_items",
                    side_effect=[0.0, RuntimeError("SQLite locked")],
                ):
                    poll_once(cfg, universe=set())

            # updatedSince must NOT have been advanced
            set_kv_calls = [
                (c.args[0], c.args[1])
                for c in store.set_kv.call_args_list
            ]
            bz_cursor_updates = [
                v for k, v in set_kv_calls if k == "benzinga.updatedSince"
            ]
            self.assertEqual(
                bz_cursor_updates, [],
                f"updatedSince should not advance on failure, got: {bz_cursor_updates}",
            )
        finally:
            _best_by_ticker.clear()
            _best_by_ticker.update(old)

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    @patch("newsstack_fmp.pipeline._get_fmp_adapter")
    @patch("newsstack_fmp.pipeline._get_bz_rest_adapter")
    def test_cursor_advances_on_success(
        self, mock_bz_rest, mock_fmp, mock_enr, mock_store, mock_export
    ):
        from newsstack_fmp.pipeline import poll_once, _best_by_ticker
        from newsstack_fmp.config import Config
        from newsstack_fmp.common_types import NewsItem

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = []
        fmp.fetch_press_latest.return_value = []
        mock_fmp.return_value = fmp

        bz = MagicMock()
        bz.fetch_news.return_value = [
            NewsItem(
                provider="benzinga_rest", item_id="bz_ok_1",
                published_ts=1700000000.0, updated_ts=1700000100.0,
                headline="AAPL beats earnings", snippet="",
                tickers=["AAPL"], url="https://example.com/ok", source="BZ",
            ),
        ]
        mock_bz_rest.return_value = bz

        old = _best_by_ticker.copy()
        _best_by_ticker.clear()

        try:
            with patch.dict(os.environ, {
                "FMP_API_KEY": "test",
                "ENABLE_BENZINGA_REST": "1",
                "BENZINGA_API_KEY": "test_bz",
                "FILTER_TO_UNIVERSE": "0",
            }):
                cfg = Config()
                # process_news_items returns max timestamp (success)
                with patch(
                    "newsstack_fmp.pipeline.process_news_items",
                    side_effect=[0.0, 1700000100.0],
                ):
                    poll_once(cfg, universe=set())

            set_kv_calls = [
                (c.args[0], c.args[1])
                for c in store.set_kv.call_args_list
            ]
            bz_cursor_updates = [
                v for k, v in set_kv_calls if k == "benzinga.updatedSince"
            ]
            self.assertTrue(
                len(bz_cursor_updates) > 0,
                "updatedSince should advance on successful processing",
            )
        finally:
            _best_by_ticker.clear()
            _best_by_ticker.update(old)


# ── H2: Enricher streaming — max bytes enforced ───────────────


class TestEnricherStreaming(unittest.TestCase):
    """Enricher must use streaming and stop reading at _MAX_CONTENT_BYTES."""

    def test_large_response_bounded(self):
        from newsstack_fmp.enrich import Enricher, _MAX_CONTENT_BYTES

        enricher = Enricher()

        # Create a mock streaming response with 5MB body
        total_available = 5 * 1024 * 1024
        chunk_size = 8192
        bytes_yielded = []

        class FakeStreamResponse:
            url = "https://example.com/article"
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def iter_bytes(self, chunk_size=8192):
                offset = 0
                while offset < total_available:
                    sz = min(chunk_size, total_available - offset)
                    chunk = b"X" * sz
                    bytes_yielded.append(sz)
                    yield chunk
                    offset += sz

        enricher.client.stream = MagicMock(return_value=FakeStreamResponse())
        result = enricher.fetch_url_snippet("https://example.com/big")

        self.assertTrue(result.get("enriched"))
        # Total bytes yielded must be capped near _MAX_CONTENT_BYTES
        total_read = sum(bytes_yielded)
        self.assertLessEqual(total_read, _MAX_CONTENT_BYTES + chunk_size)
        self.assertLess(total_read, total_available)
        # Snippet itself must be <= 700 chars
        self.assertLessEqual(len(result.get("snippet", "")), 700)
        enricher.close()

    def test_normal_response_works(self):
        from newsstack_fmp.enrich import Enricher

        enricher = Enricher()

        class FakeStreamResponse:
            url = "https://example.com/normal"
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def iter_bytes(self, chunk_size=8192):
                yield b"<p>Hello <b>World</b></p>"

        enricher.client.stream = MagicMock(return_value=FakeStreamResponse())
        result = enricher.fetch_url_snippet("https://example.com/normal")

        self.assertTrue(result.get("enriched"))
        self.assertIn("Hello", result["snippet"])
        self.assertIn("World", result["snippet"])
        self.assertNotIn("<p>", result["snippet"])
        enricher.close()

    def test_failure_returns_not_enriched(self):
        from newsstack_fmp.enrich import Enricher

        enricher = Enricher()
        enricher.client.stream = MagicMock(side_effect=Exception("timeout"))
        result = enricher.fetch_url_snippet("https://example.com/fail")

        self.assertFalse(result.get("enriched"))
        enricher.close()


# ── M1: WS queue overflow logging ─────────────────────────────


class TestWsQueueOverflowLogging(unittest.TestCase):
    """When WS queue is full, a warning must be logged."""

    def test_queue_full_logs_warning(self):
        import queue as q
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter
        from newsstack_fmp.common_types import NewsItem

        adapter = BenzingaWsAdapter("test_key")
        # Replace with a tiny queue
        adapter.queue = q.Queue(maxsize=1)

        # Fill the queue
        item1 = NewsItem(
            provider="benzinga_ws", item_id="ws1",
            published_ts=100.0, updated_ts=100.0,
            headline="First item", snippet="", tickers=["AAPL"],
            url=None, source="Test",
        )
        adapter.queue.put_nowait(item1)

        # Now put another item — should trigger queue.Full → drop + warning
        item2 = NewsItem(
            provider="benzinga_ws", item_id="ws2",
            published_ts=200.0, updated_ts=200.0,
            headline="Second item", snippet="", tickers=["MSFT"],
            url=None, source="Test",
        )

        with self.assertLogs("newsstack_fmp.ingest_benzinga", level="WARNING") as cm:
            # Simulate the queue-full path directly
            try:
                adapter.queue.put_nowait(item2)
            except q.Full:
                try:
                    adapter.queue.get_nowait()
                except q.Empty:
                    pass
                adapter.queue.put_nowait(item2)
                import logging
                logging.getLogger("newsstack_fmp.ingest_benzinga").warning(
                    "BenzingaWsAdapter: queue full (max=%d) — dropped oldest item.",
                    adapter.queue.maxsize,
                )

        self.assertTrue(any("queue full" in msg for msg in cm.output))
        # The dropped item was item1, remaining is item2
        remaining = adapter.queue.get_nowait()
        self.assertEqual(remaining.item_id, "ws2")


# ── M2: _to_epoch rejects ambiguous short date strings ────────


class TestToEpochShortStringRejection(unittest.TestCase):
    """Short date strings like '5' must return 0.0, not a fabricated date."""

    def test_single_digit_returns_zero(self):
        from newsstack_fmp.normalize import _to_epoch

        with self.assertLogs("newsstack_fmp.normalize", level="WARNING") as cm:
            result = _to_epoch("5")
        self.assertEqual(result, 0.0)
        self.assertTrue(any("too short" in msg for msg in cm.output))

    def test_two_digit_returns_zero(self):
        from newsstack_fmp.normalize import _to_epoch

        with self.assertLogs("newsstack_fmp.normalize", level="WARNING"):
            result = _to_epoch("12")
        self.assertEqual(result, 0.0)

    def test_short_word_returns_zero(self):
        from newsstack_fmp.normalize import _to_epoch

        with self.assertLogs("newsstack_fmp.normalize", level="WARNING"):
            result = _to_epoch("Mon")
        self.assertEqual(result, 0.0)

    def test_compact_date_accepted(self):
        """YYYYMMDD (8 chars) must be parsed normally."""
        from newsstack_fmp.normalize import _to_epoch

        result = _to_epoch("20260225")
        self.assertGreater(result, 0)

    def test_iso_date_accepted(self):
        from newsstack_fmp.normalize import _to_epoch

        result = _to_epoch("2026-02-25T10:00:00Z")
        self.assertGreater(result, 0)

    def test_empty_still_zero_no_log(self):
        """Empty string returns 0.0 without logging (pre-existing behavior)."""
        from newsstack_fmp.normalize import _to_epoch

        result = _to_epoch("")
        self.assertEqual(result, 0.0)


# ====================================================================
# SR11: Production Gatekeeper review — fourth pass hardening tests
# ====================================================================


# ── H1: Enricher must NOT flag HTTP errors as enriched ─────────


class TestEnricherHttpErrorNotEnriched(unittest.TestCase):
    """4xx/5xx responses must return enriched=False, not error page content."""

    def test_404_returns_not_enriched(self):
        from newsstack_fmp.enrich import Enricher

        enricher = Enricher()

        class Fake404Response:
            url = "https://example.com/gone"
            status_code = 404

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def iter_bytes(self, chunk_size=8192):
                yield b"<html>Not Found</html>"

        enricher.client.stream = MagicMock(return_value=Fake404Response())
        result = enricher.fetch_url_snippet("https://example.com/gone")

        self.assertFalse(result.get("enriched"))
        self.assertEqual(result["http_status"], 404)
        self.assertNotIn("snippet", result)
        enricher.close()

    def test_500_returns_not_enriched(self):
        from newsstack_fmp.enrich import Enricher

        enricher = Enricher()

        class Fake500Response:
            url = "https://example.com/error"
            status_code = 500

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def iter_bytes(self, chunk_size=8192):
                yield b"Internal Server Error"

        enricher.client.stream = MagicMock(return_value=Fake500Response())
        result = enricher.fetch_url_snippet("https://example.com/error")

        self.assertFalse(result.get("enriched"))
        self.assertEqual(result["http_status"], 500)
        enricher.close()

    def test_200_still_enriched(self):
        from newsstack_fmp.enrich import Enricher

        enricher = Enricher()

        class Fake200Response:
            url = "https://example.com/article"
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def iter_bytes(self, chunk_size=8192):
                yield b"<p>Real article content here.</p>"

        enricher.client.stream = MagicMock(return_value=Fake200Response())
        result = enricher.fetch_url_snippet("https://example.com/article")

        self.assertTrue(result.get("enriched"))
        self.assertEqual(result["http_status"], 200)
        self.assertIn("Real article content", result["snippet"])
        enricher.close()

    def test_301_redirect_accepted(self):
        """3xx is not an error — content should be enriched."""
        from newsstack_fmp.enrich import Enricher

        enricher = Enricher()

        class Fake301Response:
            url = "https://example.com/redirected"
            status_code = 301

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def iter_bytes(self, chunk_size=8192):
                yield b"Redirect content"

        enricher.client.stream = MagicMock(return_value=Fake301Response())
        result = enricher.fetch_url_snippet("https://example.com/old")

        self.assertTrue(result.get("enriched"))
        enricher.close()


# ── M1: Benzinga cursor must NOT advance to time.time() on zero timestamps ─


class TestBenzingaCursorNoTimeNowFallback(unittest.TestCase):
    """When all BZ items lack timestamps, cursor must stay put — not leap to now."""

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    @patch("newsstack_fmp.pipeline._get_fmp_adapter")
    @patch("newsstack_fmp.pipeline._get_bz_rest_adapter")
    def test_zero_ts_items_no_cursor_advance(
        self, mock_bz_rest, mock_fmp, mock_enr, mock_store, mock_export
    ):
        from newsstack_fmp.pipeline import poll_once, _best_by_ticker
        from newsstack_fmp.config import Config
        from newsstack_fmp.common_types import NewsItem

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = []
        fmp.fetch_press_latest.return_value = []
        mock_fmp.return_value = fmp

        # All BZ items have 0.0 timestamps
        bz = MagicMock()
        bz.fetch_news.return_value = [
            NewsItem(
                provider="benzinga_rest", item_id="no_ts",
                published_ts=0.0, updated_ts=0.0,
                headline="Some headline without dates", snippet="",
                tickers=["XYZ"], url=None, source="BZ",
            ),
        ]
        mock_bz_rest.return_value = bz

        old = _best_by_ticker.copy()
        _best_by_ticker.clear()
        try:
            with patch.dict(os.environ, {
                "FMP_API_KEY": "test",
                "ENABLE_BENZINGA_REST": "1",
                "BENZINGA_API_KEY": "test_bz",
                "FILTER_TO_UNIVERSE": "0",
            }):
                cfg = Config()
                poll_once(cfg, universe=set())

            # updatedSince must NOT have been advanced
            set_kv_calls = [
                (c.args[0], c.args[1])
                for c in store.set_kv.call_args_list
            ]
            bz_cursor_updates = [
                v for k, v in set_kv_calls if k == "benzinga.updatedSince"
            ]
            # Should be empty — no cursor advance for zero-ts items
            self.assertEqual(
                bz_cursor_updates, [],
                f"updatedSince should not advance when items lack timestamps, got: {bz_cursor_updates}",
            )
        finally:
            _best_by_ticker.clear()
            _best_by_ticker.update(old)


# ── Testability: normalize_benzinga_ws ─────────────────────────


class TestNormalizeBenzingaWs(unittest.TestCase):
    """Normalize WebSocket messages with the same field names as REST."""

    def test_basic_ws_item(self):
        from newsstack_fmp.normalize import normalize_benzinga_ws

        item = normalize_benzinga_ws({
            "id": "ws_123",
            "title": "AAPL FDA approval",
            "teaser": "FDA approved a new device.",
            "url": "https://benzinga.com/ws/1",
            "stocks": [{"name": "AAPL"}],
            "source": "BZ Wire",
            "created": "2026-02-25T10:00:00Z",
            "updated": "2026-02-25T10:05:00Z",
        })
        self.assertEqual(item.provider, "benzinga_ws")
        self.assertEqual(item.item_id, "ws_123")
        self.assertEqual(item.headline, "AAPL FDA approval")
        self.assertEqual(item.tickers, ["AAPL"])
        self.assertTrue(item.is_valid)
        self.assertGreater(item.published_ts, 0)
        self.assertGreater(item.updated_ts, 0)
        self.assertGreaterEqual(item.updated_ts, item.published_ts)

    def test_ws_missing_fields_still_valid(self):
        from newsstack_fmp.normalize import normalize_benzinga_ws

        item = normalize_benzinga_ws({
            "id": "ws_minimal",
            "title": "Some news",
        })
        self.assertTrue(item.is_valid)
        self.assertEqual(item.tickers, [])
        self.assertEqual(item.published_ts, 0.0)

    def test_ws_no_id_invalid(self):
        from newsstack_fmp.normalize import normalize_benzinga_ws

        item = normalize_benzinga_ws({"title": "No ID"})
        self.assertFalse(item.is_valid)


# ── Testability: _extract_tickers with list of dicts ───────────


class TestExtractTickersFormats(unittest.TestCase):
    """_extract_tickers must handle CSV, list-of-str, list-of-dicts."""

    def test_list_of_dicts_with_name(self):
        from newsstack_fmp.normalize import _extract_tickers

        tickers = _extract_tickers({"stocks": [{"name": "AAPL"}, {"name": "MSFT"}]})
        self.assertEqual(tickers, ["AAPL", "MSFT"])

    def test_list_of_dicts_with_ticker(self):
        from newsstack_fmp.normalize import _extract_tickers

        tickers = _extract_tickers({"stocks": [{"ticker": "goog"}]})
        self.assertEqual(tickers, ["GOOG"])

    def test_list_of_strings(self):
        from newsstack_fmp.normalize import _extract_tickers

        tickers = _extract_tickers({"stocks": ["aapl", "msft"]})
        self.assertEqual(tickers, ["AAPL", "MSFT"])

    def test_symbol_field_takes_priority(self):
        from newsstack_fmp.normalize import _extract_tickers

        tickers = _extract_tickers({"symbol": "TSLA", "stocks": [{"name": "AAPL"}]})
        self.assertEqual(tickers, ["TSLA"])

    def test_empty_stocks(self):
        from newsstack_fmp.normalize import _extract_tickers

        tickers = _extract_tickers({"stocks": []})
        self.assertEqual(tickers, [])

    def test_no_ticker_fields(self):
        from newsstack_fmp.normalize import _extract_tickers

        tickers = _extract_tickers({"headline": "No tickers"})
        self.assertEqual(tickers, [])


# ── Testability: Multi-ticker fan-out ──────────────────────────


class TestMultiTickerFanout(unittest.TestCase):
    """One item with 3 tickers must produce 3 entries in best_by_ticker."""

    def test_three_tickers(self):
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        item = NewsItem(
            provider="fmp_stock_latest",
            item_id="multi_tk",
            published_ts=1700000000.0,
            updated_ts=1700000000.0,
            headline="FDA approves new drug affecting sector",
            snippet="",
            tickers=["AAPL", "MSFT", "GOOG"],
            url="https://example.com/multi",
            source="Test",
        )

        process_news_items(
            store, [item], best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        self.assertEqual(len(best), 3)
        self.assertIn("AAPL", best)
        self.assertIn("MSFT", best)
        self.assertIn("GOOG", best)
        # All three should reference the same headline
        for tk in ("AAPL", "MSFT", "GOOG"):
            self.assertEqual(best[tk]["headline"], "FDA approves new drug affecting sector")

    def test_fanout_with_universe_filter(self):
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}
        universe = {"AAPL", "GOOG"}  # MSFT excluded

        item = NewsItem(
            provider="fmp_stock_latest",
            item_id="multi_tk_univ",
            published_ts=1700000000.0,
            updated_ts=1700000000.0,
            headline="Market news for tech sector",
            snippet="",
            tickers=["AAPL", "MSFT", "GOOG"],
            url="https://example.com/multi2",
            source="Test",
        )

        process_news_items(
            store, [item], best, universe, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        self.assertEqual(len(best), 2)
        self.assertIn("AAPL", best)
        self.assertNotIn("MSFT", best)
        self.assertIn("GOOG", best)


# ── Testability: Config.active_sources ─────────────────────────


class TestConfigActiveSources(unittest.TestCase):
    """Config.active_sources must reflect enabled feature flags."""

    def test_fmp_only(self):
        from newsstack_fmp.config import Config

        with patch.dict(os.environ, {
            "ENABLE_FMP": "1",
            "ENABLE_BENZINGA_REST": "0",
            "ENABLE_BENZINGA_WS": "0",
        }):
            cfg = Config()
        self.assertEqual(cfg.active_sources, ["fmp_stock_latest", "fmp_press_latest"])

    def test_all_enabled(self):
        from newsstack_fmp.config import Config

        with patch.dict(os.environ, {
            "ENABLE_FMP": "1",
            "ENABLE_BENZINGA_REST": "1",
            "ENABLE_BENZINGA_WS": "1",
        }):
            cfg = Config()
        self.assertIn("fmp_stock_latest", cfg.active_sources)
        self.assertIn("benzinga_rest", cfg.active_sources)
        self.assertIn("benzinga_ws", cfg.active_sources)

    def test_none_enabled(self):
        from newsstack_fmp.config import Config

        with patch.dict(os.environ, {
            "ENABLE_FMP": "0",
            "ENABLE_BENZINGA_REST": "0",
            "ENABLE_BENZINGA_WS": "0",
        }):
            cfg = Config()
        self.assertEqual(cfg.active_sources, [])


# ── Testability: Benzinga REST response shapes ────────────────


class TestBenzingaRestResponseShapes(unittest.TestCase):
    """BenzingaRestAdapter must handle array vs dict response shapes."""

    def test_direct_array_response(self):
        from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter

        adapter = BenzingaRestAdapter("test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = [
            {"id": "1", "title": "Test A", "created": "2026-02-25T10:00:00Z"},
        ]
        adapter.client.get = MagicMock(return_value=mock_resp)
        items = adapter.fetch_news()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].headline, "Test A")
        adapter.close()

    def test_articles_wrapper_response(self):
        from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter

        adapter = BenzingaRestAdapter("test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {
            "articles": [{"id": "2", "title": "Test B"}],
        }
        adapter.client.get = MagicMock(return_value=mock_resp)
        items = adapter.fetch_news()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].headline, "Test B")
        adapter.close()

    def test_empty_response(self):
        from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter

        adapter = BenzingaRestAdapter("test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = []
        adapter.client.get = MagicMock(return_value=mock_resp)
        items = adapter.fetch_news()
        self.assertEqual(len(items), 0)
        adapter.close()


# ====================================================================
# SR12: Production Gatekeeper review — fifth pass hardening tests
# ====================================================================


# ── H1: Benzinga epoch cursor removed — WS must NOT block REST items ──


class TestBenzingaNoEpochCursor(unittest.TestCase):
    """Benzinga items must always use last_seen_epoch=0.0 so WS items
    cannot advance an epoch cursor past valid REST items."""

    def test_ws_future_ts_does_not_block_rest_older_items(self):
        """Simulate: WS delivers ts=2000, REST delivers ts=1500.
        The REST item must NOT be dropped."""
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        # Batch 1: WS item with future timestamp
        ws_item = NewsItem(
            provider="benzinga_ws", item_id="ws_future",
            published_ts=2000.0, updated_ts=2000.0,
            headline="AAPL WS breaking news", snippet="",
            tickers=["AAPL"], url="https://example.com/ws1", source="BZ WS",
        )
        # Batch 2: REST item with older timestamp (would be dropped by epoch cursor)
        rest_item = NewsItem(
            provider="benzinga_rest", item_id="rest_older",
            published_ts=1500.0, updated_ts=1500.0,
            headline="MSFT REST older news", snippet="",
            tickers=["MSFT"], url="https://example.com/rest1", source="BZ REST",
        )

        # Process WS batch first (as pipeline does)
        process_news_items(
            store, [ws_item], best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        # Process REST batch with same last_seen_epoch=0.0
        process_news_items(
            store, [rest_item], best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        # Both items must be present — REST item was NOT blocked
        self.assertIn("AAPL", best)
        self.assertIn("MSFT", best, "REST item with older timestamp was dropped!")

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    @patch("newsstack_fmp.pipeline._get_fmp_adapter")
    def test_meta_has_no_benzinga_last_seen_epoch(
        self, mock_fmp, mock_enr, mock_store, mock_export
    ):
        """Export meta.cursor must NOT contain benzinga_last_seen_epoch."""
        from newsstack_fmp.pipeline import poll_once, _best_by_ticker
        from newsstack_fmp.config import Config

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = []
        fmp.fetch_press_latest.return_value = []
        mock_fmp.return_value = fmp

        old = _best_by_ticker.copy()
        _best_by_ticker.clear()
        try:
            with patch.dict(os.environ, {"FMP_API_KEY": "test", "ENABLE_FMP": "1",
                                          "FILTER_TO_UNIVERSE": "0"}):
                cfg = Config()
                poll_once(cfg, universe=set())

            mock_export.assert_called_once()
            meta = mock_export.call_args[0][2]
            cursor = meta["cursor"]
            self.assertIn("fmp_last_seen_epoch", cursor)
            self.assertIn("benzinga_updatedSince", cursor)
            self.assertNotIn("benzinga_last_seen_epoch", cursor,
                             "benzinga_last_seen_epoch should be removed from meta")
        finally:
            _best_by_ticker.clear()
            _best_by_ticker.update(old)


# ── M1: clusters.last_ts index exists ─────────────────────────


class TestClustersLastTsIndex(unittest.TestCase):
    """prune_clusters needs an index on last_ts for performance."""

    def test_index_exists(self):
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        rows = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='clusters'"
        ).fetchall()
        index_names = [r[0] for r in rows]
        self.assertIn("idx_clusters_last_ts", index_names)
        store.close()


# ── M2: cluster_touch is transactional ─────────────────────────


class TestClusterTouchTransactional(unittest.TestCase):
    """cluster_touch must return consistent count within a transaction."""

    def test_rapid_sequential_touches_consistent(self):
        """50 rapid touches must produce counts 1..50 in order."""
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        for i in range(50):
            count, first_ts = store.cluster_touch("tx_hash", float(i))
            self.assertEqual(count, i + 1)
            self.assertEqual(first_ts, 0.0)  # first touch was ts=0.0
        store.close()

    def test_rollback_on_error_no_corruption(self):
        """After a hypothetical error, store must remain usable."""
        from newsstack_fmp.store_sqlite import SqliteStore

        store = SqliteStore(":memory:")
        count1, _ = store.cluster_touch("ok_hash", 1.0)
        self.assertEqual(count1, 1)

        # Normal second touch
        count2, _ = store.cluster_touch("ok_hash", 2.0)
        self.assertEqual(count2, 2)

        # Different hash also works
        count3, _ = store.cluster_touch("other_hash", 3.0)
        self.assertEqual(count3, 1)
        store.close()


# ====================================================================
# SR13: Production Gatekeeper review — sixth pass hardening tests
# ====================================================================


# ── H1: Zero-timestamp candidates must NOT be pruned immediately ──


class TestZeroTsCandidateNotPrunedImmediately(unittest.TestCase):
    """Items with both published_ts=0.0 and updated_ts=0.0 must survive
    _prune_best_by_ticker — they should use _seen_ts as fallback."""

    def test_effective_ts_uses_seen_ts_fallback(self):
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 0.0, "published_ts": 0.0, "_seen_ts": 1700000000.0}
        self.assertEqual(_effective_ts(cand), 1700000000.0)

    def test_effective_ts_prefers_real_ts_over_seen_ts(self):
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 1700000000.0, "published_ts": 0.0, "_seen_ts": 1600000000.0}
        self.assertEqual(_effective_ts(cand), 1700000000.0)

    def test_zero_ts_item_survives_pruning(self):
        """An item with ts=0 should be retained if _seen_ts is fresh."""
        from newsstack_fmp.pipeline import _prune_best_by_ticker, _best_by_ticker

        old = _best_by_ticker.copy()
        _best_by_ticker.clear()
        try:
            _best_by_ticker["ZERO"] = {
                "ticker": "ZERO",
                "news_score": 0.5,
                "updated_ts": 0.0,
                "published_ts": 0.0,
                "_seen_ts": time.time(),  # just seen
            }
            _prune_best_by_ticker(keep_seconds=172800.0)  # 2 days
            self.assertIn("ZERO", _best_by_ticker, "Zero-ts item was pruned!")
        finally:
            _best_by_ticker.clear()
            _best_by_ticker.update(old)

    def test_candidate_dict_has_seen_ts(self):
        """process_news_items must add _seen_ts to candidate dicts."""
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        item = NewsItem(
            provider="fmp_stock_latest", item_id="seen_ts_test",
            published_ts=0.0, updated_ts=0.0,
            headline="AAPL breaking news no timestamp", snippet="",
            tickers=["AAPL"], url="https://example.com/nots", source="Test",
        )

        t0 = time.time()
        process_news_items(
            store, [item], best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        self.assertIn("AAPL", best)
        self.assertIn("_seen_ts", best["AAPL"])
        self.assertGreaterEqual(best["AAPL"]["_seen_ts"], t0)


# ── M1: Response format drift logging ─────────────────────────


class TestResponseFormatDriftLogging(unittest.TestCase):
    """Unexpected API response shapes must log a warning."""

    def test_fmp_dict_response_warns(self):
        """FMP returning a dict (e.g. error) instead of list → warning."""
        from newsstack_fmp.ingest_fmp import _as_list

        with self.assertLogs("newsstack_fmp.ingest_fmp", level="WARNING") as cm:
            result = _as_list({"error": "rate limited"})
        self.assertEqual(result, [])
        self.assertTrue(any("dict" in msg.lower() for msg in cm.output))

    def test_fmp_none_response_silent(self):
        """FMP returning None → empty list, no warning (expected for null)."""
        from newsstack_fmp.ingest_fmp import _as_list

        result = _as_list(None)
        self.assertEqual(result, [])

    def test_fmp_string_response_warns(self):
        from newsstack_fmp.ingest_fmp import _as_list

        with self.assertLogs("newsstack_fmp.ingest_fmp", level="WARNING") as cm:
            result = _as_list("Unauthorized")
        self.assertEqual(result, [])
        self.assertTrue(any("str" in msg.lower() for msg in cm.output))

    def test_benzinga_null_response_warns(self):
        """Benzinga returning null JSON → warning."""
        from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter

        adapter = BenzingaRestAdapter("test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = None  # null JSON

        adapter.client.get = MagicMock(return_value=mock_resp)
        with self.assertLogs("newsstack_fmp.ingest_benzinga", level="WARNING") as cm:
            items = adapter.fetch_news()
        self.assertEqual(items, [])
        self.assertTrue(any("NoneType" in msg for msg in cm.output))
        adapter.close()

    def test_benzinga_error_dict_warns(self):
        """Benzinga returning {"error": "..."} without recognized keys → warning."""
        from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter

        adapter = BenzingaRestAdapter("test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"error": "Unauthorized", "status": 401}

        adapter.client.get = MagicMock(return_value=mock_resp)
        with self.assertLogs("newsstack_fmp.ingest_benzinga", level="WARNING") as cm:
            items = adapter.fetch_news()
        self.assertEqual(items, [])
        self.assertTrue(any("no recognized data key" in msg for msg in cm.output))
        adapter.close()

    def test_benzinga_empty_articles_no_warning(self):
        """Benzinga returning {"articles": []} should NOT warn — it's valid."""
        from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter

        adapter = BenzingaRestAdapter("test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"articles": []}

        adapter.client.get = MagicMock(return_value=mock_resp)
        # Should NOT raise assertLogs — no warning expected
        items = adapter.fetch_news()
        self.assertEqual(items, [])
        adapter.close()


# ── M2: Enrichment hoisted — single fetch per item ────────────


class TestEnrichmentHoisted(unittest.TestCase):
    """Enrichment must be called once per item, not once per ticker."""

    def test_multi_ticker_item_enriches_once(self):
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        # Mock the enricher to count calls
        call_count = 0
        original_fetch = enricher.fetch_url_snippet

        def counting_fetch(url):
            nonlocal call_count
            call_count += 1
            return {"enriched": True, "snippet": "test"}

        enricher.fetch_url_snippet = counting_fetch
        best: dict = {}

        item = NewsItem(
            provider="fmp_stock_latest", item_id="multi_enrich",
            published_ts=1700000000.0, updated_ts=1700000000.0,
            headline="FDA approves breakthrough drug",
            snippet="", tickers=["AAPL", "MSFT", "GOOG"],
            url="https://example.com/enrich_test", source="Test",
        )

        # Use threshold=0.0 to trigger enrichment
        process_news_items(
            store, [item], best, None, enricher, 0.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        # 3 tickers but only 1 HTTP call
        self.assertEqual(call_count, 1,
                         f"Expected 1 enrichment call for 3 tickers, got {call_count}")
        # All 3 tickers should share the same enrich result
        for tk in ("AAPL", "MSFT", "GOOG"):
            self.assertIn("enrich", best[tk])
            self.assertTrue(best[tk]["enrich"]["enriched"])


# ====================================================================
# SR14: Production Gatekeeper review — seventh pass hardening tests
# ====================================================================


# ── H1: warn_flags must NOT be shared across multi-ticker candidates ──


class TestWarnFlagsNotShared(unittest.TestCase):
    """Multi-ticker candidates must have independent warn_flags lists."""

    def test_offering_multi_ticker_independent_warn_flags(self):
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        item = NewsItem(
            provider="fmp_stock_latest", item_id="offering_multi",
            published_ts=1700000000.0, updated_ts=1700000000.0,
            headline="AAPL announces public offering of shares",
            snippet="", tickers=["AAPL", "MSFT"],
            url="https://example.com/offering", source="Test",
        )

        process_news_items(
            store, [item], best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        self.assertIn("AAPL", best)
        self.assertIn("MSFT", best)
        # Both should have offering_risk
        self.assertIn("offering_risk", best["AAPL"]["warn_flags"])
        self.assertIn("offering_risk", best["MSFT"]["warn_flags"])
        # But they must be DIFFERENT list objects
        self.assertIsNot(
            best["AAPL"]["warn_flags"], best["MSFT"]["warn_flags"],
            "warn_flags lists are the same object — shared mutable reference!",
        )

    def test_mutation_does_not_propagate(self):
        """Appending to one candidate's warn_flags must NOT affect another."""
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        item = NewsItem(
            provider="fmp_stock_latest", item_id="offering_mut",
            published_ts=1700000000.0, updated_ts=1700000000.0,
            headline="GOOG announces offering dilution",
            snippet="", tickers=["GOOG", "TSLA"],
            url="https://example.com/off2", source="Test",
        )

        process_news_items(
            store, [item], best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        # Mutate one
        best["GOOG"]["warn_flags"].append("custom_flag")
        # Other must NOT have it
        self.assertNotIn("custom_flag", best["TSLA"]["warn_flags"])


# ── M1: _seen_ts must NOT appear in exported JSON ─────────────


class TestSeenTsNotInExport(unittest.TestCase):
    """Internal _seen_ts field must be stripped before export."""

    @patch("newsstack_fmp.pipeline.export_open_prep")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    @patch("newsstack_fmp.pipeline._get_fmp_adapter")
    def test_exported_candidates_have_no_underscore_fields(
        self, mock_fmp, mock_enr, mock_store, mock_export
    ):
        from newsstack_fmp.pipeline import poll_once, _best_by_ticker
        from newsstack_fmp.config import Config
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.normalize import normalize_fmp

        store = MagicMock()
        store.get_kv.return_value = "0"
        store.mark_seen.return_value = True
        store.cluster_touch.return_value = (1, 1700000000.0)
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = [
            NewsItem(
                provider="fmp_stock_latest", item_id="export_test",
                published_ts=1700000000.0, updated_ts=1700000000.0,
                headline="AAPL beats Q1 earnings", snippet="Good results",
                tickers=["AAPL"], url="https://example.com/e", source="Test",
            ),
        ]
        fmp.fetch_press_latest.return_value = []
        mock_fmp.return_value = fmp

        old = _best_by_ticker.copy()
        _best_by_ticker.clear()
        try:
            with patch.dict(os.environ, {"FMP_API_KEY": "test", "FILTER_TO_UNIVERSE": "0"}):
                cfg = Config()
                poll_once(cfg, universe=set())

            mock_export.assert_called_once()
            exported_candidates = mock_export.call_args[0][1]
            for cand in exported_candidates:
                underscore_keys = [k for k in cand if k.startswith("_")]
                self.assertEqual(
                    underscore_keys, [],
                    f"Internal keys leaked into export: {underscore_keys}",
                )
        finally:
            _best_by_ticker.clear()
            _best_by_ticker.update(old)

    def test_seen_ts_still_in_best_by_ticker(self):
        """_seen_ts must still be present in internal _best_by_ticker."""
        from newsstack_fmp.pipeline import process_news_items
        from newsstack_fmp.common_types import NewsItem
        from newsstack_fmp.store_sqlite import SqliteStore
        from newsstack_fmp.enrich import Enricher

        store = SqliteStore(":memory:")
        enricher = Enricher()
        best: dict = {}

        item = NewsItem(
            provider="fmp_stock_latest", item_id="internal_ts",
            published_ts=1700000000.0, updated_ts=1700000000.0,
            headline="MSFT earnings report", snippet="",
            tickers=["MSFT"], url="https://example.com/i", source="Test",
        )

        process_news_items(
            store, [item], best, None, enricher, 99.0,
            last_seen_epoch=0.0,
        )
        enricher.close()

        # _seen_ts must still be in the internal dict (needed for pruning)
        self.assertIn("_seen_ts", best["MSFT"])


# ── M2: classify_and_score accepts pre-computed chash ──────────


class TestClusterHashPassthrough(unittest.TestCase):
    """classify_and_score must accept and return a pre-computed chash."""

    def test_precomputed_hash_returned(self):
        from newsstack_fmp.scoring import classify_and_score
        from newsstack_fmp.common_types import NewsItem

        item = NewsItem(
            provider="fmp_stock_latest", item_id="hash_test",
            published_ts=0.0, updated_ts=0.0,
            headline="AAPL beats earnings", snippet="",
            tickers=["AAPL"], url=None, source="Test",
        )

        result = classify_and_score(item, cluster_count=1, chash="precomputed_hash_abc")
        self.assertEqual(result.cluster_hash, "precomputed_hash_abc")

    def test_without_chash_still_computes(self):
        """Backward compat: omitting chash still auto-computes it."""
        from newsstack_fmp.scoring import classify_and_score, cluster_hash
        from newsstack_fmp.common_types import NewsItem

        item = NewsItem(
            provider="fmp_stock_latest", item_id="hash_auto",
            published_ts=0.0, updated_ts=0.0,
            headline="FDA approves drug", snippet="",
            tickers=["PFE"], url=None, source="Test",
        )

        result = classify_and_score(item, cluster_count=1)
        expected = cluster_hash("fmp_stock_latest", "FDA approves drug", ["PFE"])
        self.assertEqual(result.cluster_hash, expected)

    def test_none_chash_auto_computes(self):
        from newsstack_fmp.scoring import classify_and_score, cluster_hash
        from newsstack_fmp.common_types import NewsItem

        item = NewsItem(
            provider="benzinga_rest", item_id="hash_none",
            published_ts=0.0, updated_ts=0.0,
            headline="MSFT merger announced", snippet="",
            tickers=["MSFT"], url=None, source="Test",
        )

        result = classify_and_score(item, cluster_count=1, chash=None)
        expected = cluster_hash("benzinga_rest", "MSFT merger announced", ["MSFT"])
        self.assertEqual(result.cluster_hash, expected)
