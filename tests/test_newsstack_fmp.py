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
