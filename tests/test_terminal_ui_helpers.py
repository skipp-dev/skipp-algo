"""Comprehensive tests for terminal_ui_helpers.py.

Covers every pure function extracted from streamlit_terminal.py:
  - Feed pruning
  - Feed filtering (search, sentiment, category, date range)
  - Formatting (score badge, age string, provider icon, safe markdown)
  - Highlight / enrichment helpers
  - Feed stats computation
  - Top movers aggregation
  - Segment aggregation + split + summary rows
  - Heatmap data building
  - Alert rule matching
  - Dedup merge
  - Rankings enrichment
"""

from __future__ import annotations

import time
from typing import Any

from terminal_ui_helpers import (
    _SKIP_CHANNELS,
    MATERIALITY_COLORS,
    MATERIALITY_EMOJI,
    RECENCY_COLORS,
    RECENCY_EMOJI,
    SENTIMENT_COLORS,
    aggregate_segments,
    build_heatmap_data,
    build_segment_summary_rows,
    compute_feed_stats,
    compute_top_movers,
    dedup_merge,
    enrich_materiality,
    enrich_rank_rows,
    enrich_recency,
    filter_feed,
    format_age_string,
    format_score_badge,
    highlight_fresh_row,
    item_dedup_key,
    match_alert_rule,
    provider_icon,
    prune_stale_items,
    safe_markdown_text,
    safe_url,
    split_segments_by_sentiment,
)

# ── Helpers ─────────────────────────────────────────────────────


def _item(
    ticker: str = "AAPL",
    news_score: float = 0.75,
    published_ts: float | None = None,
    sentiment_label: str = "neutral",
    category: str = "earnings",
    materiality: str = "MEDIUM",
    headline: str = "Apple reports earnings",
    is_actionable: bool = False,
    relevance: float = 0.5,
    item_id: str = "",
    channels: list[str] | None = None,
    provider: str = "benzinga",
    url: str = "",
    snippet: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Factory for a minimal feed item dict."""
    if published_ts is None:
        published_ts = time.time() - 300  # 5 min ago
    return {
        "ticker": ticker,
        "news_score": news_score,
        "published_ts": published_ts,
        "sentiment_label": sentiment_label,
        "category": category,
        "materiality": materiality,
        "headline": headline,
        "is_actionable": is_actionable,
        "relevance": relevance,
        "item_id": item_id or f"id-{ticker}-{news_score}",
        "channels": channels if channels is not None else [],
        "provider": provider,
        "url": url,
        "snippet": snippet,
        **extra,
    }


# ═══════════════════════════════════════════════════════════════
# Icon / colour map constants
# ═══════════════════════════════════════════════════════════════


class TestIconMaps:
    def test_sentiment_colors_complete(self):
        assert set(SENTIMENT_COLORS.keys()) == {"bullish", "bearish", "neutral"}

    def test_materiality_colors_complete(self):
        assert set(MATERIALITY_COLORS.keys()) == {"HIGH", "MEDIUM", "LOW"}

    def test_recency_colors_complete(self):
        for key in ("ULTRA_FRESH", "FRESH", "WARM", "AGING", "STALE", "UNKNOWN"):
            assert key in RECENCY_COLORS

    def test_emoji_maps_match_color_maps(self):
        assert MATERIALITY_EMOJI == MATERIALITY_COLORS
        assert RECENCY_EMOJI == RECENCY_COLORS

    def test_skip_channels(self):
        assert "" in _SKIP_CHANNELS
        assert "news" in _SKIP_CHANNELS
        assert "earnings" not in _SKIP_CHANNELS


# ═══════════════════════════════════════════════════════════════
# prune_stale_items
# ═══════════════════════════════════════════════════════════════


class TestPruneStaleItems:
    def test_keeps_fresh_items(self):
        now = time.time()
        feed = [_item(published_ts=now - 60)]
        assert len(prune_stale_items(feed, max_age_s=120)) == 1

    def test_drops_old_items(self):
        now = time.time()
        feed = [_item(published_ts=now - 7200)]
        assert len(prune_stale_items(feed, max_age_s=3600)) == 0

    def test_disabled_when_zero(self):
        feed = [_item(published_ts=1.0)]  # very old
        assert prune_stale_items(feed, max_age_s=0) == feed

    def test_disabled_when_negative(self):
        feed = [_item(published_ts=1.0)]
        assert prune_stale_items(feed, max_age_s=-1) == feed

    def test_empty_feed(self):
        assert prune_stale_items([], max_age_s=3600) == []

    def test_missing_published_ts_kept(self):
        """Items with no published_ts are not provably stale so should be kept."""
        feed = [{"ticker": "X"}]  # no published_ts
        result = prune_stale_items(feed, max_age_s=3600)
        assert len(result) == 1

    def test_mixed_ages(self):
        now = time.time()
        feed = [
            _item(ticker="OLD", published_ts=now - 7200),
            _item(ticker="NEW", published_ts=now - 60),
        ]
        result = prune_stale_items(feed, max_age_s=3600)
        assert len(result) == 1
        assert result[0]["ticker"] == "NEW"


# ═══════════════════════════════════════════════════════════════
# filter_feed
# ═══════════════════════════════════════════════════════════════


class TestFilterFeed:
    def _sample(self) -> list[dict[str, Any]]:
        now = time.time()
        return [
            _item(ticker="AAPL", news_score=0.9, sentiment_label="bullish",
                  category="earnings", headline="Apple beats", published_ts=now - 60),
            _item(ticker="MSFT", news_score=0.5, sentiment_label="neutral",
                  category="tech", headline="MSFT update", published_ts=now - 120),
            _item(ticker="TSLA", news_score=0.3, sentiment_label="bearish",
                  category="earnings", headline="Tesla misses", published_ts=now - 180),
        ]

    def test_no_filters(self):
        feed = self._sample()
        result = filter_feed(feed)
        assert len(result) == 3
        # Sorted by score desc
        assert result[0]["ticker"] == "AAPL"

    def test_search_headline(self):
        result = filter_feed(self._sample(), search_q="beats")
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"

    def test_search_ticker(self):
        result = filter_feed(self._sample(), search_q="tsla")
        assert len(result) == 1
        assert result[0]["ticker"] == "TSLA"

    def test_search_snippet(self):
        feed = [_item(snippet="custom snippet text")]
        result = filter_feed(feed, search_q="custom snippet")
        assert len(result) == 1

    def test_search_case_insensitive(self):
        result = filter_feed(self._sample(), search_q="APPLE")
        assert len(result) == 1

    def test_sentiment_filter(self):
        result = filter_feed(self._sample(), sentiment="bearish")
        assert len(result) == 1
        assert result[0]["ticker"] == "TSLA"

    def test_category_filter(self):
        result = filter_feed(self._sample(), category="tech")
        assert len(result) == 1
        assert result[0]["ticker"] == "MSFT"

    def test_date_range_filter(self):
        now = time.time()
        result = filter_feed(
            self._sample(),
            from_epoch=now - 90,
            to_epoch=now,
        )
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"

    def test_combined_filters(self):
        result = filter_feed(
            self._sample(),
            sentiment="bullish",
            category="earnings",
        )
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"

    def test_no_match(self):
        result = filter_feed(self._sample(), search_q="nonexistent xyz")
        assert result == []

    def test_sort_order_score_descending(self):
        now = time.time()
        feed = [
            _item(ticker="B", news_score=0.3, published_ts=now),
            _item(ticker="A", news_score=0.7, published_ts=now),
            _item(ticker="C", news_score=0.5, published_ts=now),
        ]
        result = filter_feed(feed)
        assert [r["ticker"] for r in result] == ["A", "C", "B"]

    def test_empty_feed(self):
        assert filter_feed([]) == []


# ═══════════════════════════════════════════════════════════════
# Formatting helpers
# ═══════════════════════════════════════════════════════════════


class TestFormatScoreBadge:
    def test_high_score_red(self):
        badge = format_score_badge(0.85)
        assert ":red[" in badge
        assert "0.85" in badge

    def test_mid_score_orange(self):
        badge = format_score_badge(0.55)
        assert ":orange[" in badge

    def test_low_score_plain(self):
        badge = format_score_badge(0.30)
        assert ":" not in badge
        assert "0.30" in badge

    def test_boundary_080(self):
        badge = format_score_badge(0.80)
        assert ":red[" in badge

    def test_boundary_050(self):
        badge = format_score_badge(0.50)
        assert ":orange[" in badge

    def test_zero(self):
        badge = format_score_badge(0.0)
        assert "0.00" in badge


class TestFormatAgeString:
    def test_recent(self):
        now = 1000.0
        assert format_age_string(now - 120, now=now) == "0:00:02:00"

    def test_none_ts(self):
        assert format_age_string(None) == "?"

    def test_zero_ts(self):
        assert format_age_string(0) == "?"

    def test_negative_ts(self):
        assert format_age_string(-5) == "?"

    def test_future_ts_clamped(self):
        now = 1000.0
        result = format_age_string(1500, now=now)
        assert result == "0:00:00:00"

    def test_uses_current_time_by_default(self):
        ts = time.time() - 600  # 10 min ago
        result = format_age_string(ts)
        assert "00:10:0" in result  # matches 0:00:10:00

    def test_days_format(self):
        now = 100000.0
        result = format_age_string(now - 90061, now=now)  # 1 day, 1 hour, 1 min, 1 sec
        assert result == "1:01:01:01"

    def test_hours_format(self):
        now = 10000.0
        result = format_age_string(now - 3723, now=now)  # 1h 2m 3s
        assert result == "0:01:02:03"


class TestProviderIcon:
    def test_benzinga(self):
        assert provider_icon("benzinga") == "🅱️"

    def test_fmp(self):
        assert provider_icon("fmp_news") == "📊"

    def test_unknown(self):
        assert provider_icon("reuters") == ""

    def test_empty(self):
        assert provider_icon("") == ""


class TestSafeMarkdownText:
    def test_escapes_brackets(self):
        assert safe_markdown_text("[test]") == "\\[test\\]"

    def test_no_brackets_unchanged(self):
        assert safe_markdown_text("hello world") == "hello world"

    def test_nested_brackets(self):
        assert safe_markdown_text("[[nested]]") == "\\[\\[nested\\]\\]"


class TestSafeUrl:
    def test_escapes_parens(self):
        assert safe_url("https://example.com/path(1)") == "https://example.com/path%281%29"

    def test_empty(self):
        assert safe_url("") == ""

    def test_normal_url_unchanged(self):
        assert safe_url("https://example.com/path") == "https://example.com/path"


# ═══════════════════════════════════════════════════════════════
# Highlight / Enrichment
# ═══════════════════════════════════════════════════════════════


class TestHighlightFreshRow:
    def test_fresh_row(self):
        styles = highlight_fresh_row(5, 4)
        assert all(s == "color: #FF8C00" for s in styles)
        assert len(styles) == 4

    def test_old_row(self):
        styles = highlight_fresh_row(25, 4)
        assert all(s == "" for s in styles)

    def test_boundary_20(self):
        styles = highlight_fresh_row(20, 3)
        assert all(s == "" for s in styles)

    def test_boundary_19(self):
        styles = highlight_fresh_row(19, 3)
        assert all(s == "color: #FF8C00" for s in styles)

    def test_non_numeric(self):
        styles = highlight_fresh_row("N/A", 3)
        assert all(s == "" for s in styles)

    def test_none(self):
        styles = highlight_fresh_row(None, 3)
        assert all(s == "" for s in styles)


class TestEnrichMateriality:
    def test_high(self):
        assert enrich_materiality("HIGH") == "🔴 HIGH"

    def test_medium(self):
        assert enrich_materiality("MEDIUM") == "🟠 MEDIUM"

    def test_low(self):
        assert enrich_materiality("LOW") == "⚪ LOW"

    def test_unknown(self):
        assert enrich_materiality("NONE") == "NONE"


class TestEnrichRecency:
    def test_fresh(self):
        assert enrich_recency("FRESH") == "🟢 FRESH"

    def test_stale(self):
        assert enrich_recency("STALE") == "⚫ STALE"

    def test_unknown(self):
        assert enrich_recency("UNKNOWN") == "❓ UNKNOWN"


# ═══════════════════════════════════════════════════════════════
# compute_feed_stats
# ═══════════════════════════════════════════════════════════════


class TestComputeFeedStats:
    def test_basic(self):
        now = time.time()
        feed = [
            _item(ticker="AAPL", is_actionable=True, materiality="HIGH",
                  relevance=0.8, published_ts=now - 60),
            _item(ticker="MSFT", is_actionable=False, materiality="LOW",
                  relevance=0.4, published_ts=now - 120),
            _item(ticker="AAPL", is_actionable=True, materiality="HIGH",
                  relevance=0.6, published_ts=now - 180),
        ]
        stats = compute_feed_stats(feed)
        assert stats["count"] == 3
        assert stats["unique_tickers"] == 2
        assert stats["actionable"] == 2
        assert stats["high_materiality"] == 2
        assert 0.59 < stats["avg_relevance"] < 0.61
        assert stats["newest_age_min"] < 2

    def test_excludes_market_from_unique_tickers(self):
        feed = [
            _item(ticker="MARKET"),
            _item(ticker="AAPL"),
        ]
        stats = compute_feed_stats(feed)
        assert stats["unique_tickers"] == 1

    def test_empty_feed(self):
        stats = compute_feed_stats([])
        assert stats["count"] == 0
        assert stats["unique_tickers"] == 0
        assert stats["avg_relevance"] == 0
        assert stats["newest_age_min"] == 0


# ═══════════════════════════════════════════════════════════════
# compute_top_movers
# ═══════════════════════════════════════════════════════════════


class TestComputeTopMovers:
    def test_within_window(self):
        now = 100000.0
        feed = [
            _item(ticker="AAPL", news_score=0.9, published_ts=now - 60),
            _item(ticker="MSFT", news_score=0.5, published_ts=now - 120),
        ]
        movers = compute_top_movers(feed, now=now)
        assert len(movers) == 2
        assert movers[0]["ticker"] == "AAPL"

    def test_outside_window(self):
        now = 100000.0
        feed = [_item(ticker="AAPL", published_ts=now - 3600)]
        movers = compute_top_movers(feed, now=now)
        assert movers == []

    def test_best_per_ticker(self):
        now = 100000.0
        feed = [
            _item(ticker="AAPL", news_score=0.3, published_ts=now - 60),
            _item(ticker="AAPL", news_score=0.9, published_ts=now - 120, item_id="hi"),
        ]
        movers = compute_top_movers(feed, now=now)
        assert len(movers) == 1
        assert movers[0]["news_score"] == 0.9

    def test_excludes_market(self):
        now = 100000.0
        feed = [_item(ticker="MARKET", published_ts=now - 60)]
        assert compute_top_movers(feed, now=now) == []

    def test_limit(self):
        now = 100000.0
        feed = [_item(ticker=f"T{i}", published_ts=now - 60) for i in range(30)]
        movers = compute_top_movers(feed, now=now, limit=5)
        assert len(movers) == 5

    def test_custom_window(self):
        now = 100000.0
        feed = [_item(ticker="AAPL", published_ts=now - 600)]
        assert len(compute_top_movers(feed, now=now, window_s=300)) == 0
        assert len(compute_top_movers(feed, now=now, window_s=900)) == 1


# ═══════════════════════════════════════════════════════════════
# aggregate_segments
# ═══════════════════════════════════════════════════════════════


class TestAggregateSegments:
    def test_basic_aggregation(self):
        feed = [
            _item(ticker="AAPL", channels=["Tech"], sentiment_label="bullish",
                  news_score=0.8),
            _item(ticker="MSFT", channels=["Tech"], sentiment_label="neutral",
                  news_score=0.6, item_id="msft-1"),
        ]
        segs = aggregate_segments(feed)
        assert len(segs) == 1
        assert segs[0]["segment"] == "Tech"
        assert segs[0]["articles"] == 2
        assert segs[0]["tickers"] == 2
        assert segs[0]["bull"] == 1
        assert segs[0]["neut"] == 1

    def test_skip_channels_filtered(self):
        feed = [_item(channels=["news"])]
        assert aggregate_segments(feed) == []

    def test_skip_market_ticker(self):
        feed = [_item(ticker="MARKET", channels=["Tech"])]
        assert aggregate_segments(feed) == []

    def test_falls_back_to_category(self):
        feed = [_item(channels=[], category="biotech")]
        segs = aggregate_segments(feed)
        assert len(segs) == 1
        assert segs[0]["segment"] == "Biotech"  # .title()

    def test_sentiment_icon(self):
        feed = [
            _item(ticker="A", channels=["Sec"], sentiment_label="bullish"),
            _item(ticker="B", channels=["Sec"], sentiment_label="bullish", item_id="b"),
        ]
        segs = aggregate_segments(feed)
        assert segs[0]["sentiment"] == "🟢"
        assert segs[0]["net_sent"] == 2

    def test_bearish_sentiment(self):
        feed = [
            _item(ticker="A", channels=["Sec"], sentiment_label="bearish"),
            _item(ticker="B", channels=["Sec"], sentiment_label="bearish", item_id="b"),
        ]
        segs = aggregate_segments(feed)
        assert segs[0]["sentiment"] == "🔴"
        assert segs[0]["net_sent"] == -2

    def test_neutral_sentiment(self):
        feed = [
            _item(ticker="A", channels=["Sec"], sentiment_label="bullish"),
            _item(ticker="B", channels=["Sec"], sentiment_label="bearish", item_id="b"),
        ]
        segs = aggregate_segments(feed)
        assert segs[0]["sentiment"] == "🟡"
        assert segs[0]["net_sent"] == 0

    def test_best_ticker_kept(self):
        feed = [
            _item(ticker="AAPL", channels=["Tech"], news_score=0.3,
                  item_id="lo"),
            _item(ticker="AAPL", channels=["Tech"], news_score=0.9,
                  item_id="hi"),
        ]
        segs = aggregate_segments(feed)
        assert segs[0]["_ticker_map"]["AAPL"]["news_score"] == 0.9

    def test_sorted_by_article_count(self):
        feed = [
            _item(ticker="A", channels=["Small"], item_id="a"),
            _item(ticker="B", channels=["Big"], item_id="b1"),
            _item(ticker="C", channels=["Big"], item_id="b2"),
        ]
        segs = aggregate_segments(feed)
        assert segs[0]["segment"] == "Big"

    def test_multi_channel_item(self):
        feed = [_item(ticker="AAPL", channels=["Tech", "Earnings"])]
        segs = aggregate_segments(feed)
        assert len(segs) == 2
        seg_names = {s["segment"] for s in segs}
        assert seg_names == {"Tech", "Earnings"}

    def test_empty_feed(self):
        assert aggregate_segments([]) == []


class TestSplitSegmentsBySentiment:
    def test_split(self):
        rows = [
            {"net_sent": 2, "segment": "A"},
            {"net_sent": -1, "segment": "B"},
            {"net_sent": 0, "segment": "C"},
        ]
        bull, neut, bear = split_segments_by_sentiment(rows)
        assert len(bull) == 1
        assert bull[0]["segment"] == "A"
        assert len(neut) == 1
        assert neut[0]["segment"] == "C"
        assert len(bear) == 1
        assert bear[0]["segment"] == "B"

    def test_empty(self):
        assert split_segments_by_sentiment([]) == ([], [], [])


class TestBuildSegmentSummaryRows:
    def test_builds_display_dict(self):
        feed = [
            _item(ticker="AAPL", channels=["Tech"], sentiment_label="bullish",
                  news_score=0.8),
        ]
        segs = aggregate_segments(feed)
        summary = build_segment_summary_rows(segs)
        assert len(summary) == 1
        assert summary[0]["Segment"] == "Tech"
        assert summary[0]["Articles"] == 1
        assert "🟢" in summary[0]


# ═══════════════════════════════════════════════════════════════
# build_heatmap_data
# ═══════════════════════════════════════════════════════════════


class TestBuildHeatmapData:
    def test_basic(self):
        feed = [
            _item(ticker="AAPL", channels=["Tech"], news_score=0.8,
                  sentiment_label="bullish"),
        ]
        data = build_heatmap_data(feed)
        assert len(data) == 1
        assert data[0]["sector"] == "Tech"
        assert data[0]["ticker"] == "AAPL"
        assert data[0]["score"] == 0.8

    def test_excludes_market(self):
        feed = [_item(ticker="MARKET", channels=["Tech"])]
        assert build_heatmap_data(feed) == []

    def test_skips_generic_channels(self):
        feed = [_item(channels=["news"])]
        assert build_heatmap_data(feed) == []

    def test_multiple_tickers_same_sector(self):
        feed = [
            _item(ticker="AAPL", channels=["Tech"]),
            _item(ticker="MSFT", channels=["Tech"], item_id="msft"),
        ]
        data = build_heatmap_data(feed)
        assert len(data) == 2

    def test_article_counts(self):
        feed = [
            _item(ticker="AAPL", channels=["Tech"], item_id="a1"),
            _item(ticker="AAPL", channels=["Tech"], item_id="a2"),
        ]
        data = build_heatmap_data(feed)
        assert len(data) == 1
        assert data[0]["articles"] == 2

    def test_empty_feed(self):
        assert build_heatmap_data([]) == []


# ═══════════════════════════════════════════════════════════════
# match_alert_rule
# ═══════════════════════════════════════════════════════════════


class TestMatchAlertRule:
    def test_score_threshold_match(self):
        rule = {"ticker": "*", "condition": "score >= threshold", "threshold": 0.80}
        assert match_alert_rule(
            rule, ticker="AAPL", news_score=0.85, sentiment_label="neutral",
            materiality="LOW", category="other",
        )

    def test_score_threshold_no_match(self):
        rule = {"ticker": "*", "condition": "score >= threshold", "threshold": 0.80}
        assert not match_alert_rule(
            rule, ticker="AAPL", news_score=0.75, sentiment_label="neutral",
            materiality="LOW", category="other",
        )

    def test_ticker_filter(self):
        rule = {"ticker": "AAPL", "condition": "score >= threshold", "threshold": 0.5}
        assert match_alert_rule(
            rule, ticker="AAPL", news_score=0.6, sentiment_label="neutral",
            materiality="LOW", category="other",
        )
        assert not match_alert_rule(
            rule, ticker="MSFT", news_score=0.9, sentiment_label="neutral",
            materiality="LOW", category="other",
        )

    def test_wildcard_ticker(self):
        rule = {"ticker": "*", "condition": "sentiment == bearish"}
        assert match_alert_rule(
            rule, ticker="TSLA", news_score=0.5, sentiment_label="bearish",
            materiality="LOW", category="other",
        )

    def test_sentiment_bullish(self):
        rule = {"ticker": "*", "condition": "sentiment == bullish"}
        assert match_alert_rule(
            rule, ticker="X", news_score=0.5, sentiment_label="bullish",
            materiality="LOW", category="other",
        )
        assert not match_alert_rule(
            rule, ticker="X", news_score=0.5, sentiment_label="neutral",
            materiality="LOW", category="other",
        )

    def test_materiality_match(self):
        rule = {"ticker": "*", "condition": "materiality == HIGH"}
        assert match_alert_rule(
            rule, ticker="X", news_score=0.5, sentiment_label="neutral",
            materiality="HIGH", category="other",
        )
        assert not match_alert_rule(
            rule, ticker="X", news_score=0.5, sentiment_label="neutral",
            materiality="LOW", category="other",
        )

    def test_category_match(self):
        rule = {"ticker": "*", "condition": "category matches", "category": "halt"}
        assert match_alert_rule(
            rule, ticker="X", news_score=0.5, sentiment_label="neutral",
            materiality="LOW", category="halt",
        )
        assert not match_alert_rule(
            rule, ticker="X", news_score=0.5, sentiment_label="neutral",
            materiality="LOW", category="earnings",
        )

    def test_unknown_condition(self):
        rule = {"ticker": "*", "condition": "magic"}
        assert not match_alert_rule(
            rule, ticker="X", news_score=0.9, sentiment_label="bullish",
            materiality="HIGH", category="halt",
        )


# ═══════════════════════════════════════════════════════════════
# Dedup merge
# ═══════════════════════════════════════════════════════════════


class TestItemDedupKey:
    def test_basic(self):
        assert item_dedup_key({"item_id": "abc", "ticker": "AAPL"}) == "abc:AAPL"

    def test_missing_fields(self):
        assert item_dedup_key({}) == ":"


class TestDedupMerge:
    def test_no_overlap(self):
        existing = [_item(ticker="AAPL", item_id="a1")]
        incoming = [_item(ticker="MSFT", item_id="m1")]
        merged = dedup_merge(existing, incoming)
        assert len(merged) == 2
        # Incoming first
        assert merged[0]["ticker"] == "MSFT"

    def test_with_overlap(self):
        existing = [_item(ticker="AAPL", item_id="a1")]
        incoming = [_item(ticker="AAPL", item_id="a1")]
        merged = dedup_merge(existing, incoming)
        assert len(merged) == 1

    def test_partial_overlap(self):
        existing = [_item(ticker="AAPL", item_id="a1")]
        incoming = [
            _item(ticker="AAPL", item_id="a1"),
            _item(ticker="MSFT", item_id="m1"),
        ]
        merged = dedup_merge(existing, incoming)
        assert len(merged) == 2

    def test_empty_incoming(self):
        existing = [_item(ticker="AAPL", item_id="a1")]
        merged = dedup_merge(existing, [])
        assert len(merged) == 1

    def test_empty_existing(self):
        incoming = [_item(ticker="AAPL", item_id="a1")]
        merged = dedup_merge([], incoming)
        assert len(merged) == 1


# ═══════════════════════════════════════════════════════════════
# Rankings enrichment
# ═══════════════════════════════════════════════════════════════


class TestEnrichRankRows:
    def test_enriches_materiality_and_recency(self):
        rows = [
            {"materiality": "HIGH", "recency": "FRESH"},
            {"materiality": "LOW", "recency": "STALE"},
        ]
        result = enrich_rank_rows(rows)
        assert result[0]["materiality"] == "🔴 HIGH"
        assert result[0]["recency"] == "🟢 FRESH"
        assert result[1]["materiality"] == "⚪ LOW"
        assert result[1]["recency"] == "⚫ STALE"

    def test_unknown_values(self):
        rows = [{"materiality": "NONE", "recency": "NONE"}]
        result = enrich_rank_rows(rows)
        assert result[0]["materiality"] == "NONE"
        assert result[0]["recency"] == "NONE"

    def test_returns_same_list(self):
        rows = [{"materiality": "HIGH", "recency": "FRESH"}]
        assert enrich_rank_rows(rows) is rows

    def test_empty_list(self):
        assert enrich_rank_rows([]) == []


# ═══════════════════════════════════════════════════════════════
# Edge cases / regression guards
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_filter_feed_none_headline(self):
        """Feed items with None headline should not crash search."""
        feed = [_item(headline=None)]  # type: ignore[arg-type]
        # Should not raise
        result = filter_feed(feed, search_q="test")
        assert isinstance(result, list)

    def test_filter_feed_none_ticker(self):
        feed = [_item(ticker=None)]  # type: ignore[arg-type]
        result = filter_feed(feed, search_q="test")
        assert isinstance(result, list)

    def test_compute_feed_stats_no_published_ts(self):
        feed = [{"ticker": "X"}]
        stats = compute_feed_stats(feed)
        assert stats["newest_age_min"] == 0

    def test_compute_top_movers_no_published_ts(self):
        feed = [{"ticker": "X"}]
        movers = compute_top_movers(feed, now=100000.0)
        assert movers == []

    def test_heatmap_non_string_channel(self):
        feed = [_item(channels=[123])]  # type: ignore[list-item]
        data = build_heatmap_data(feed)
        assert len(data) == 1

    def test_segment_title_case(self):
        feed = [_item(channels=["biotech"])]
        segs = aggregate_segments(feed)
        assert segs[0]["segment"] == "Biotech"
