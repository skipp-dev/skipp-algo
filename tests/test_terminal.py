"""Unit tests for the Bloomberg Terminal components.

Tests terminal_poller (poll_and_classify, _classify_item, ClassifiedItem),
terminal_export (append_jsonl, rotate_jsonl, fire_webhook), and the
integration of all open_prep classifiers on Benzinga-shaped data.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp.scoring import ScoreResult, classify_and_score, cluster_hash
from newsstack_fmp.store_sqlite import SqliteStore


# ═════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path: Path) -> SqliteStore:
    """Temporary SQLite store for tests."""
    return SqliteStore(str(tmp_path / "test_terminal.db"))


@pytest.fixture
def sample_raw_benzinga() -> Dict[str, Any]:
    """Simulated raw Benzinga REST /api/v2/news response item."""
    return {
        "id": 99900001,
        "author": "Jane Doe",
        "created": "Mon, 20 Jan 2025 09:30:00 -0500",
        "updated": "Mon, 20 Jan 2025 09:31:00 -0500",
        "title": "NVIDIA Reports Record Q4 Earnings, Beats Estimates on AI Demand",
        "teaser": "NVIDIA posted Q4 earnings that topped analyst expectations...",
        "body": "<p>Full article body…</p>",
        "url": "https://www.benzinga.com/news/99900001",
        "channels": [{"name": "Earnings"}, {"name": "Tech"}, {"name": "Top Stories"}],
        "stocks": [{"name": "NVDA", "exchange": "NASDAQ"}],
        "tags": [{"name": "AI"}, {"name": "earnings"}],
        "image": [{"size": "thumb", "url": "https://img.example.com/thumb.jpg"}],
    }


@pytest.fixture
def sample_newsitem(sample_raw_benzinga: Dict[str, Any]) -> NewsItem:
    """Pre-normalised NewsItem from Benzinga REST."""
    from newsstack_fmp.normalize import normalize_benzinga_rest
    return normalize_benzinga_rest(sample_raw_benzinga)


@pytest.fixture
def bearish_newsitem() -> NewsItem:
    """NewsItem with a bearish headline."""
    return NewsItem(
        provider="benzinga_rest",
        item_id="99900002",
        published_ts=time.time() - 120,  # 2 minutes ago
        updated_ts=time.time() - 60,
        headline="Company XYZ Misses Q4 Estimates, Shares Plunge 15%",
        snippet="Revenue came in below expectations as the company warned of weak guidance.",
        tickers=["XYZ"],
        url="https://www.benzinga.com/news/99900002",
        source="Benzinga",
        raw={
            "channels": [{"name": "Earnings"}, {"name": "Movers"}],
            "tags": [{"name": "earnings"}],
        },
    )


@pytest.fixture
def halt_newsitem() -> NewsItem:
    """NewsItem about a trading halt."""
    return NewsItem(
        provider="benzinga_rest",
        item_id="99900003",
        published_ts=time.time() - 30,
        updated_ts=time.time() - 10,
        headline="Trading Halt: ABC Corp halted pending news",
        snippet="NASDAQ has halted trading in ABC pending a company announcement.",
        tickers=["ABC"],
        url=None,
        source="NASDAQ",
        raw={"channels": [{"name": "Equities"}], "tags": []},
    )


# ═════════════════════════════════════════════════════════════════
# terminal_poller tests
# ═════════════════════════════════════════════════════════════════

class TestClassifyItem:
    """Tests for terminal_poller._classify_item."""

    def test_basic_classification(self, sample_newsitem: NewsItem, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        now = datetime.now(UTC)
        results = _classify_item(sample_newsitem, tmp_db, now)
        assert len(results) >= 1
        ci = results[0]
        assert ci.ticker == "NVDA"
        assert ci.category == "earnings"
        assert ci.sentiment_label == "bullish"
        assert ci.news_score > 0
        assert ci.event_label in ("earnings", "guidance")
        assert ci.source_tier in ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
        assert ci.recency_bucket in ("ULTRA_FRESH", "FRESH", "WARM", "AGING", "STALE", "UNKNOWN")

    def test_dedup_prevents_duplicate(self, sample_newsitem: NewsItem, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        now = datetime.now(UTC)
        first = _classify_item(sample_newsitem, tmp_db, now)
        assert len(first) >= 1
        second = _classify_item(sample_newsitem, tmp_db, now)
        assert len(second) == 0, "Duplicate item should be filtered"

    def test_bearish_sentiment(self, bearish_newsitem: NewsItem, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        now = datetime.now(UTC)
        results = _classify_item(bearish_newsitem, tmp_db, now)
        assert len(results) >= 1
        ci = results[0]
        assert ci.sentiment_label == "bearish"
        assert ci.sentiment_score < 0

    def test_halt_category(self, halt_newsitem: NewsItem, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        now = datetime.now(UTC)
        results = _classify_item(halt_newsitem, tmp_db, now)
        assert len(results) >= 1
        ci = results[0]
        assert ci.category == "halt"
        assert ci.impact >= 0.90

    def test_channels_extracted(self, sample_newsitem: NewsItem, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        now = datetime.now(UTC)
        results = _classify_item(sample_newsitem, tmp_db, now)
        ci = results[0]
        assert "Earnings" in ci.channels
        assert "Tech" in ci.channels

    def test_invalid_item_returns_empty(self, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        invalid = NewsItem(
            provider="test", item_id="", published_ts=0, updated_ts=0,
            headline="", snippet="", tickers=[], url=None, source="", raw={},
        )
        results = _classify_item(invalid, tmp_db, datetime.now(UTC))
        assert results == []

    def test_no_ticker_gets_market_label(self, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        item = NewsItem(
            provider="benzinga_rest", item_id="noticker1",
            published_ts=time.time(), updated_ts=time.time(),
            headline="Federal Reserve raises interest rates by 25bps",
            snippet="The FOMC voted unanimously to raise rates.",
            tickers=[], url=None, source="Reuters", raw={},
        )
        results = _classify_item(item, tmp_db, datetime.now(UTC))
        assert len(results) == 1
        assert results[0].ticker == "MARKET"

    def test_to_dict_roundtrip(self, sample_newsitem: NewsItem, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        results = _classify_item(sample_newsitem, tmp_db, datetime.now(UTC))
        ci = results[0]
        d = ci.to_dict()
        assert isinstance(d, dict)
        assert d["ticker"] == "NVDA"
        assert isinstance(d["news_score"], float)
        assert isinstance(d["channels"], list)

    def test_recency_ultra_fresh(self, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        item = NewsItem(
            provider="benzinga_rest", item_id="fresh1",
            published_ts=time.time() - 60,  # 1 minute ago
            updated_ts=time.time() - 30,
            headline="Breaking: New FDA approval for drug XYZ",
            snippet="FDA grants emergency approval.",
            tickers=["PFE"], url=None, source="FDA.gov", raw={},
        )
        results = _classify_item(item, tmp_db, datetime.now(UTC))
        assert results[0].recency_bucket == "ULTRA_FRESH"
        assert results[0].is_actionable is True

    def test_multi_ticker_creates_multiple_items(self, tmp_db: SqliteStore) -> None:
        from terminal_poller import _classify_item
        item = NewsItem(
            provider="benzinga_rest", item_id="multi1",
            published_ts=time.time(), updated_ts=time.time(),
            headline="AAPL and MSFT both report earnings above estimates",
            snippet="Both companies beat.",
            tickers=["AAPL", "MSFT"], url=None, source="Benzinga", raw={},
        )
        results = _classify_item(item, tmp_db, datetime.now(UTC))
        assert len(results) == 2
        tickers = {r.ticker for r in results}
        assert tickers == {"AAPL", "MSFT"}


class TestPollAndClassify:
    """Tests for terminal_poller.poll_and_classify with mocked adapter."""

    def test_basic_poll(self, sample_newsitem: NewsItem, tmp_db: SqliteStore) -> None:
        from terminal_poller import poll_and_classify
        mock_adapter = MagicMock(spec=["fetch_news"])
        mock_adapter.fetch_news.return_value = [sample_newsitem]

        items, cursor = poll_and_classify(mock_adapter, tmp_db, cursor=None, page_size=100)
        assert len(items) >= 1
        assert cursor  # cursor should be non-empty
        mock_adapter.fetch_news.assert_called_once()

    def test_empty_poll(self, tmp_db: SqliteStore) -> None:
        from terminal_poller import poll_and_classify
        mock_adapter = MagicMock(spec=["fetch_news"])
        mock_adapter.fetch_news.return_value = []

        items, cursor = poll_and_classify(mock_adapter, tmp_db, cursor=None)
        assert items == []

    def test_cursor_advances(self, tmp_db: SqliteStore) -> None:
        from terminal_poller import poll_and_classify
        now = time.time()
        item = NewsItem(
            provider="benzinga_rest", item_id="cur1",
            published_ts=now - 10, updated_ts=now - 5,
            headline="Some earnings report beats expectations",
            snippet="Details.", tickers=["TST"],
            url=None, source="Test", raw={},
        )
        mock_adapter = MagicMock(spec=["fetch_news"])
        mock_adapter.fetch_news.return_value = [item]

        _, cursor1 = poll_and_classify(mock_adapter, tmp_db, cursor=None)
        assert float(cursor1) > 0

        # Second poll with same item → deduped, cursor stays
        mock_adapter.fetch_news.return_value = [item]
        items2, cursor2 = poll_and_classify(mock_adapter, tmp_db, cursor=cursor1)
        assert len(items2) == 0  # deduped


# ═════════════════════════════════════════════════════════════════
# terminal_export tests
# ═════════════════════════════════════════════════════════════════

class TestJsonlExport:
    """Tests for terminal_export.append_jsonl and rotate_jsonl."""

    def _make_classified_item(self, **overrides: Any) -> "ClassifiedItem":
        from terminal_poller import ClassifiedItem
        defaults = dict(
            item_id="test1", ticker="NVDA", tickers_all=["NVDA"],
            headline="Test headline", snippet="Test snippet",
            url="https://example.com", source="Test",
            published_ts=time.time(), updated_ts=time.time(),
            provider="benzinga_rest",
            category="earnings", impact=0.80, clarity=0.70,
            polarity=0.5, news_score=0.85, cluster_hash="abc123",
            novelty_count=1,
            sentiment_label="bullish", sentiment_score=0.6,
            event_class="SCHEDULED", event_label="earnings",
            materiality="MEDIUM",
            recency_bucket="FRESH", age_minutes=5.0, is_actionable=True,
            source_tier="TIER_2", source_rank=2,
            channels=["Earnings"], tags=["AI"],
            relevance=0.5, entity_count=1,
        )
        defaults.update(overrides)
        return ClassifiedItem(**defaults)

    def test_append_creates_file(self, tmp_path: Path) -> None:
        from terminal_export import append_jsonl
        path = str(tmp_path / "test_feed.jsonl")
        ci = self._make_classified_item()
        append_jsonl(ci, path)

        assert os.path.exists(path)
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["ticker"] == "NVDA"
        assert data["sentiment_label"] == "bullish"

    def test_append_multiple_lines(self, tmp_path: Path) -> None:
        from terminal_export import append_jsonl
        path = str(tmp_path / "test_multi.jsonl")
        for i in range(5):
            ci = self._make_classified_item(item_id=f"item{i}", ticker=f"T{i}")
            append_jsonl(ci, path)

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_rotate_trims_lines(self, tmp_path: Path) -> None:
        from terminal_export import append_jsonl, rotate_jsonl
        path = str(tmp_path / "test_rotate.jsonl")

        # Write 20 lines
        for i in range(20):
            ci = self._make_classified_item(item_id=f"r{i}")
            append_jsonl(ci, path)

        # Rotate to 10
        rotate_jsonl(path, max_lines=10)

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 10
        # The last line should be the most recent item
        last = json.loads(lines[-1])
        assert last["item_id"] == "r19"

    def test_rotate_noop_when_small(self, tmp_path: Path) -> None:
        from terminal_export import append_jsonl, rotate_jsonl
        path = str(tmp_path / "test_noop.jsonl")
        ci = self._make_classified_item()
        append_jsonl(ci, path)

        rotate_jsonl(path, max_lines=100)
        with open(path) as f:
            assert len(f.readlines()) == 1


class TestWebhookStub:
    """Tests for terminal_export.fire_webhook."""

    def _make_ci(self, **kw: Any) -> "ClassifiedItem":
        from terminal_poller import ClassifiedItem
        defaults = dict(
            item_id="wh1", ticker="NVDA", tickers_all=["NVDA"],
            headline="NVIDIA beats estimates", snippet="Details",
            url="https://example.com", source="Benzinga",
            published_ts=time.time(), updated_ts=time.time(),
            provider="benzinga_rest",
            category="earnings", impact=0.80, clarity=0.70,
            polarity=0.5, news_score=0.85, cluster_hash="abc",
            novelty_count=1,
            sentiment_label="bullish", sentiment_score=0.6,
            event_class="SCHEDULED", event_label="earnings",
            materiality="MEDIUM",
            recency_bucket="FRESH", age_minutes=5.0, is_actionable=True,
            source_tier="TIER_2", source_rank=2,
            channels=[], tags=[],
            relevance=0.5, entity_count=1,
        )
        defaults.update(kw)
        return ClassifiedItem(**defaults)

    def test_disabled_when_no_url(self) -> None:
        from terminal_export import fire_webhook
        ci = self._make_ci()
        result = fire_webhook(ci, url="", secret="ignored")
        assert result is None

    def test_skipped_when_low_score(self) -> None:
        from terminal_export import fire_webhook
        ci = self._make_ci(news_score=0.30)
        result = fire_webhook(ci, url="https://example.com/webhook", min_score=0.70)
        assert result is None

    @patch("terminal_export.httpx.Client")
    def test_fires_on_high_score(self, mock_client_cls: MagicMock) -> None:
        from terminal_export import fire_webhook

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        ci = self._make_ci(news_score=0.90)
        result = fire_webhook(ci, url="https://example.com/webhook")
        assert result == {"ok": True}
        mock_client.post.assert_called_once()

        # Verify payload shape
        call_kwargs = mock_client.post.call_args
        body = json.loads(call_kwargs.kwargs.get("content", call_kwargs[1].get("content", b"")))
        assert body["ticker"] == "NVDA"
        assert body["action"] == "buy"  # bullish + high score


# ═════════════════════════════════════════════════════════════════
# Integration: classifier pipeline on Benzinga data
# ═════════════════════════════════════════════════════════════════

class TestClassifierIntegration:
    """End-to-end tests of the classifier chain on realistic data."""

    def test_earnings_beat_full_chain(self) -> None:
        """Earnings beat → bullish sentiment, SCHEDULED event, earnings category."""
        from open_prep.news import classify_article_sentiment
        from open_prep.playbook import classify_news_event, classify_recency, classify_source_quality

        title = "NVIDIA Reports Record Q4 Revenue, Beats Estimates on Strong AI Chip Demand"
        content = "NVIDIA posted record quarterly revenue of $22.1 billion, beating analyst estimates."

        label, score = classify_article_sentiment(title, content)
        assert label == "bullish"
        assert score > 0

        event = classify_news_event(title, content)
        assert event["event_label"] in ("earnings", "guidance")
        assert event["event_class"] == "SCHEDULED"

        recency = classify_recency(datetime.now(UTC), datetime.now(UTC))
        assert recency["recency_bucket"] == "ULTRA_FRESH"
        assert recency["is_actionable"] is True

        source = classify_source_quality("Benzinga", title)
        assert source["source_tier"] == "TIER_2"
        assert source["source_rank"] == 2

    def test_trading_halt_chain(self) -> None:
        from open_prep.news import classify_article_sentiment
        from open_prep.playbook import classify_news_event

        title = "Trading Halt: ACME Corp halted pending company news"
        label, score = classify_article_sentiment(title)
        # Halts are typically neutral sentiment (no directional keywords)
        assert label in ("neutral", "bearish")

        event = classify_news_event(title)
        # halt is unscheduled
        assert event["event_class"] in ("UNSCHEDULED", "UNKNOWN")

    def test_fda_approval_chain(self) -> None:
        from open_prep.news import classify_article_sentiment
        from open_prep.playbook import classify_news_event

        title = "FDA Grants Approval for New Drug Treatment by PharmaCo"
        label, score = classify_article_sentiment(title)
        assert label == "bullish"

        event = classify_news_event(title)
        assert event["materiality"] == "HIGH"

    def test_offering_chain(self) -> None:
        from newsstack_fmp.scoring import classify_and_score
        item = NewsItem(
            provider="benzinga_rest", item_id="off1",
            published_ts=time.time(), updated_ts=time.time(),
            headline="Small Cap Corp Announces $50M Public Offering",
            snippet="The company will use proceeds for general corporate purposes.",
            tickers=["SCC"], url=None, source="Benzinga", raw={},
        )
        result = classify_and_score(item, cluster_count=1)
        assert result.category == "offering"
        assert result.impact >= 0.90


class TestTerminalConfig:
    """Tests for TerminalConfig env-var driven defaults."""

    def test_defaults(self) -> None:
        from terminal_poller import TerminalConfig
        # Clear any env vars that might interfere
        with patch.dict(os.environ, {}, clear=False):
            cfg = TerminalConfig()
            assert cfg.poll_interval_s == 5.0
            assert cfg.page_size == 100
            assert cfg.max_items == 500
            assert cfg.display_output == "abstract"

    def test_env_override(self) -> None:
        from terminal_poller import TerminalConfig
        env = {
            "TERMINAL_POLL_INTERVAL_S": "10.0",
            "TERMINAL_MAX_ITEMS": "200",
            "BENZINGA_API_KEY": "test_key_123",
        }
        with patch.dict(os.environ, env):
            cfg = TerminalConfig()
            assert cfg.poll_interval_s == 10.0
            assert cfg.max_items == 200
            assert cfg.benzinga_api_key == "test_key_123"


# ═════════════════════════════════════════════════════════════════
# VisiData Per-Symbol Snapshot
# ═════════════════════════════════════════════════════════════════

class TestVdSnapshot:
    """Tests for build_vd_snapshot / save_vd_snapshot."""

    def _make_feed_item(self, ticker: str, score: float, **overrides: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "ticker": ticker,
            "news_score": score,
            "sentiment_label": "bullish",
            "sentiment_score": 0.6,
            "category": "earnings",
            "event_label": "earnings",
            "materiality": "MEDIUM",
            "impact": 0.80,
            "clarity": 0.80,
            "polarity": 0.5,
            "recency_bucket": "FRESH",
            "age_minutes": 5.0,
            "is_actionable": True,
            "source_tier": "TIER_1",
            "source": "Benzinga",
            "published_ts": time.time(),
        }
        base.update(overrides)
        return base

    def test_build_basic(self) -> None:
        from terminal_export import build_vd_snapshot
        feed = [
            self._make_feed_item("AAPL", 0.85),
            self._make_feed_item("TSLA", 0.60),
        ]
        rows = build_vd_snapshot(feed, max_age_s=0)
        assert len(rows) == 2
        # Should be sorted by score desc
        assert rows[0]["symbol"] == "AAPL"
        assert rows[1]["symbol"] == "TSLA"

    def test_aggregates_per_ticker(self) -> None:
        from terminal_export import build_vd_snapshot
        feed = [
            self._make_feed_item("AAPL", 0.50),
            self._make_feed_item("AAPL", 0.85),
            self._make_feed_item("AAPL", 0.40),
        ]
        rows = build_vd_snapshot(feed, max_age_s=0)
        assert len(rows) == 1
        assert rows[0]["N"] == 3
        assert rows[0]["score"] == 0.85  # best score wins

    def test_skips_market_ticker(self) -> None:
        from terminal_export import build_vd_snapshot
        feed = [
            self._make_feed_item("MARKET", 0.90),
            self._make_feed_item("NVDA", 0.70),
        ]
        rows = build_vd_snapshot(feed, max_age_s=0)
        assert len(rows) == 1
        assert rows[0]["symbol"] == "NVDA"

    def test_all_columns_present(self) -> None:
        from terminal_export import build_vd_snapshot
        expected_cols = [
            "symbol", "N", "sentiment", "tick", "score", "relevance",
            "streak", "category", "event", "materiality", "impact",
            "clarity", "sentiment_score", "polarity", "recency",
            "age_min", "actionable", "provider", "price", "chg_pct", "vol_ratio",
        ]
        feed = [self._make_feed_item("META", 0.75)]
        rows = build_vd_snapshot(feed, max_age_s=0)
        assert len(rows) == 1
        for col in expected_cols:
            assert col in rows[0], f"Missing column: {col}"

    def test_sentiment_emoji(self) -> None:
        from terminal_export import build_vd_snapshot
        feed = [
            self._make_feed_item("BULL", 0.5, sentiment_label="bullish"),
            self._make_feed_item("BEAR", 0.5, sentiment_label="bearish"),
            self._make_feed_item("NEU", 0.5, sentiment_label="neutral"),
        ]
        rows = build_vd_snapshot(feed, max_age_s=0)
        by_sym = {r["symbol"]: r for r in rows}
        assert by_sym["BULL"]["sentiment"] == "🟢"
        assert by_sym["BEAR"]["sentiment"] == "🔴"
        assert by_sym["NEU"]["sentiment"] == "🟡"

    def test_save_atomic_write(self, tmp_path: Path) -> None:
        from terminal_export import save_vd_snapshot
        feed = [
            self._make_feed_item("GOOG", 0.90),
            self._make_feed_item("MSFT", 0.70),
        ]
        out = str(tmp_path / "vd_test.jsonl")
        save_vd_snapshot(feed, path=out)

        lines = Path(out).read_text().strip().split("\n")
        assert len(lines) == 2
        row0 = json.loads(lines[0])
        assert row0["symbol"] == "GOOG"  # highest score first

    def test_empty_feed_no_file(self, tmp_path: Path) -> None:
        from terminal_export import save_vd_snapshot
        out = str(tmp_path / "vd_empty.jsonl")
        save_vd_snapshot([], path=out)
        assert not Path(out).exists()


# ═════════════════════════════════════════════════════════════════
# RT Engine Integration (load_rt_quotes, merged snapshot)
# ═════════════════════════════════════════════════════════════════

class TestRtIntegration:
    """Tests for load_rt_quotes and RT-merged build_vd_snapshot."""

    def _make_feed_item(self, ticker: str, score: float, **kw: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "ticker": ticker,
            "news_score": score,
            "sentiment_label": "bullish",
            "sentiment_score": 0.6,
            "category": "earnings",
            "event_label": "earnings",
            "materiality": "MEDIUM",
            "impact": 0.80,
            "clarity": 0.80,
            "polarity": 0.5,
            "recency_bucket": "FRESH",
            "age_minutes": 5.0,
            "is_actionable": True,
            "published_ts": time.time(),
        }
        base.update(kw)
        return base

    def _write_rt_jsonl(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    # ── load_rt_quotes ─────────────────────────────────────────

    def test_load_file_not_found(self) -> None:
        from terminal_export import load_rt_quotes
        result = load_rt_quotes("/nonexistent/path.jsonl")
        assert result == {}

    def test_load_stale_file(self, tmp_path: Path) -> None:
        from terminal_export import load_rt_quotes
        p = tmp_path / "stale.jsonl"
        self._write_rt_jsonl(p, [{"symbol": "AAPL", "price": 150.0}])
        # Make the file 300 seconds old
        old_time = time.time() - 300
        os.utime(str(p), (old_time, old_time))
        result = load_rt_quotes(str(p), max_age_s=120.0)
        assert result == {}

    def test_load_fresh_file(self, tmp_path: Path) -> None:
        from terminal_export import load_rt_quotes
        p = tmp_path / "fresh.jsonl"
        self._write_rt_jsonl(p, [
            {"symbol": "AAPL", "price": 195.5, "chg_pct": 1.2},
            {"symbol": "TSLA", "price": 250.0, "chg_pct": -0.5},
        ])
        result = load_rt_quotes(str(p))
        assert len(result) == 2
        assert result["AAPL"]["price"] == 195.5
        assert result["TSLA"]["chg_pct"] == -0.5

    def test_load_skips_malformed_lines(self, tmp_path: Path) -> None:
        from terminal_export import load_rt_quotes
        p = tmp_path / "mixed.jsonl"
        with open(p, "w") as fh:
            fh.write('{"symbol": "OK", "price": 100}\n')
            fh.write("NOT VALID JSON\n")
            fh.write("\n")  # blank line
            fh.write('{"symbol": "ALSO_OK", "price": 200}\n')
        result = load_rt_quotes(str(p))
        assert len(result) == 2
        assert "OK" in result
        assert "ALSO_OK" in result

    def test_load_case_insensitive_symbol(self, tmp_path: Path) -> None:
        from terminal_export import load_rt_quotes
        p = tmp_path / "case.jsonl"
        self._write_rt_jsonl(p, [{"symbol": "aapl", "price": 100}])
        result = load_rt_quotes(str(p))
        assert "AAPL" in result  # uppercased

    def test_load_max_age_zero_accepts_any(self, tmp_path: Path) -> None:
        from terminal_export import load_rt_quotes
        p = tmp_path / "old_but_ok.jsonl"
        self._write_rt_jsonl(p, [{"symbol": "X", "price": 10}])
        old_time = time.time() - 999999
        os.utime(str(p), (old_time, old_time))
        # max_age_s=0 disables staleness check
        result = load_rt_quotes(str(p), max_age_s=0)
        assert len(result) == 1

    # ── build_vd_snapshot with RT merge ────────────────────────

    def test_merge_populates_quote_fields(self) -> None:
        from terminal_export import build_vd_snapshot
        feed = [self._make_feed_item("AAPL", 0.85)]
        rt = {"AAPL": {"tick": "↑", "streak": 3,
                        "price": 195.5, "chg_pct": 1.2, "vol_ratio": 2.1}}
        rows = build_vd_snapshot(feed, rt_quotes=rt, max_age_s=0)
        assert len(rows) == 1
        r = rows[0]
        assert r["tick"] == "↑"
        assert r["streak"] == 3
        assert r["price"] == 195.5
        assert r["chg_pct"] == 1.2
        assert r["vol_ratio"] == 2.1

    def test_merge_no_rt_match_gets_defaults(self) -> None:
        from terminal_export import build_vd_snapshot
        feed = [self._make_feed_item("NVDA", 0.90)]
        rt = {"AAPL": {"price": 195.0}}  # no NVDA
        rows = build_vd_snapshot(feed, rt_quotes=rt, max_age_s=0)
        r = rows[0]
        assert r["tick"] == ""
        assert r["streak"] == 0
        assert r["price"] is None
        assert r["chg_pct"] is None
        assert r["vol_ratio"] is None

    def test_merge_mixed_coverage(self) -> None:
        from terminal_export import build_vd_snapshot
        feed = [
            self._make_feed_item("AAPL", 0.85),
            self._make_feed_item("NVDA", 0.80),
            self._make_feed_item("TSLA", 0.75),
        ]
        rt = {
            "AAPL": {"price": 195.0, "chg_pct": 1.0,
                      "tick": "↑", "streak": 2, "vol_ratio": 1.5},
            "TSLA": {"price": 250.0, "chg_pct": -0.3,
                      "tick": "↓", "streak": -1, "vol_ratio": 0.8},
        }
        rows = build_vd_snapshot(feed, rt_quotes=rt, max_age_s=0)
        by_sym = {r["symbol"]: r for r in rows}
        # AAPL has RT data
        assert by_sym["AAPL"]["price"] == 195.0
        # NVDA has no RT data → defaults
        assert by_sym["NVDA"]["price"] is None
        # TSLA has RT data
        assert by_sym["TSLA"]["price"] == 250.0
        assert by_sym["TSLA"]["tick"] == "↓"

    def test_save_with_rt_merge(self, tmp_path: Path) -> None:
        from terminal_export import save_vd_snapshot
        # Create a fake RT engine JSONL
        rt_path = tmp_path / "rt_signals.jsonl"
        self._write_rt_jsonl(rt_path, [
            {"symbol": "GOOG", "price": 175.0,
             "chg_pct": 0.5, "tick": "↗", "streak": 1, "vol_ratio": 1.2},
        ])
        feed = [self._make_feed_item("GOOG", 0.92)]
        out = str(tmp_path / "vd_merged.jsonl")
        save_vd_snapshot(feed, path=out, rt_jsonl_path=str(rt_path))

        lines = Path(out).read_text().strip().split("\n")
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["symbol"] == "GOOG"
        assert row["price"] == 175.0
