"""Unit tests for the cross-source news event matcher.

The matcher groups the SAME real-world news event across providers that share
no common id (Benzinga vs TradingView vs X) by ticker overlap + published-time
proximity + headline similarity. It underpins both the historical content-lead
pre-study and the later live t_tv / t_x columns of the shadow harness.
"""

from __future__ import annotations

from scripts.news_event_matcher import (
    MatchedEvent,
    SourceItem,
    headline_similarity,
    items_match,
    match_events,
    normalize_headline,
)

# ── normalization / similarity ──────────────────────────────────────


def test_normalize_strips_cashtags_punctuation_and_case() -> None:
    assert normalize_headline("$AAPL: Apple BEATS on earnings!!") == "apple beats on earnings"


def test_similarity_high_for_paraphrase_low_for_unrelated() -> None:
    a = "Apple beats Q3 earnings, raises guidance"
    b = "Apple Q3 earnings beat; guidance raised"
    c = "Tesla recalls 40,000 vehicles over brake issue"
    assert headline_similarity(a, b) >= 0.6
    assert headline_similarity(a, c) < 0.4


# ── items_match ─────────────────────────────────────────────────────


def _item(source, iid, ts, hl, tickers, arrival=None):
    return SourceItem(source=source, item_id=iid, published_ts=ts, headline=hl,
                      tickers=tickers, arrival_ts=arrival)


def test_items_match_requires_ticker_overlap() -> None:
    a = _item("benzinga", "b1", 100.0, "Apple beats on earnings", ["AAPL"])
    b = _item("tv", "t1", 130.0, "Apple beats on earnings", ["MSFT"])
    assert not items_match(a, b, time_window_s=120.0, min_headline_sim=0.6)


def test_items_match_requires_time_window() -> None:
    a = _item("benzinga", "b1", 100.0, "Apple beats on earnings", ["AAPL"])
    b = _item("tv", "t1", 100.0 + 999, "Apple beats on earnings", ["AAPL"])
    assert not items_match(a, b, time_window_s=120.0, min_headline_sim=0.6)


def test_items_match_positive() -> None:
    a = _item("benzinga", "b1", 100.0, "Apple beats Q3 earnings, raises guidance", ["AAPL"])
    b = _item("tv", "t1", 140.0, "Apple Q3 earnings beat; guidance raised", ["AAPL", "SPY"])
    assert items_match(a, b, time_window_s=120.0, min_headline_sim=0.6)


def test_ticker_overlap_is_case_insensitive() -> None:
    a = _item("benzinga", "b1", 100.0, "Nvidia lands major AI contract", ["nvda"])
    b = _item("tv", "t1", 120.0, "Nvidia wins major AI contract", ["NVDA"])
    assert items_match(a, b, time_window_s=120.0, min_headline_sim=0.6)


# ── clustering ──────────────────────────────────────────────────────


def test_match_events_groups_same_event_across_sources() -> None:
    items = [
        _item("benzinga", "b1", 100.0, "Apple beats Q3 earnings, raises guidance", ["AAPL"]),
        _item("tv", "t1", 132.0, "Apple Q3 earnings beat; guidance raised", ["AAPL"]),
        _item("x", "x1", 90.0, "AAPL earnings beat and guidance raise", ["AAPL"]),
        # unrelated event → its own cluster
        _item("benzinga", "b2", 500.0, "Tesla recalls 40,000 vehicles", ["TSLA"]),
    ]
    events = match_events(items, time_window_s=120.0, min_headline_sim=0.5)
    assert len(events) == 2
    apple = next(e for e in events if "AAPL" in e.tickers)
    assert set(apple.per_source) == {"benzinga", "tv", "x"}


def test_match_events_keeps_earliest_item_per_source() -> None:
    items = [
        _item("benzinga", "b1", 100.0, "Apple beats on earnings", ["AAPL"]),
        _item("benzinga", "b2", 108.0, "Apple beats on earnings again", ["AAPL"]),
        _item("tv", "t1", 120.0, "Apple beats on earnings", ["AAPL"]),
    ]
    events = match_events(items, time_window_s=120.0, min_headline_sim=0.5)
    assert len(events) == 1
    assert events[0].per_source["benzinga"].item_id == "b1"  # earliest wins


def test_matched_event_timestamp_prefers_arrival() -> None:
    ev = MatchedEvent(
        tickers=["AAPL"],
        per_source={
            "benzinga": _item("benzinga", "b1", 100.0, "h", ["AAPL"], arrival=105.0),
            "tv": _item("tv", "t1", 100.0, "h", ["AAPL"]),  # no arrival
        },
    )
    assert ev.timestamp("benzinga") == 105.0          # arrival preferred
    assert ev.timestamp("tv") == 100.0                # falls back to published
    assert ev.timestamp("x") is None                  # absent source
