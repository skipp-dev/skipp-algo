"""Regression tests for the news ticker-score index (audit P3 HIGH).

The index must produce identical news_strength / news_bias to the previous
per-symbol story rescan, including multi-ticker stories and sentiment_score /
news_score precedence, and must rebuild when the snapshot reloads.
"""

from __future__ import annotations

import time

import services.live_overlay_daemon.compute as compute


def _reset_news_state() -> None:
    compute._news_cache = {}
    compute._news_loaded_at = 0.0
    compute._news_checked_at = 0.0
    compute._news_index = {}
    compute._news_index_built_at = -1.0


def _install_snapshot(monkeypatch, snap: dict) -> None:
    _reset_news_state()
    monkeypatch.setattr(compute.config, "news_snapshot_url", lambda: "")
    # Force _load_news_snapshot to accept our in-memory snapshot by stubbing
    # the loader to populate the cache with a fresh monotonic load time.
    def _fake_load() -> dict:
        compute._news_cache = snap
        compute._news_loaded_at = time.monotonic()
        return dict(snap)
    monkeypatch.setattr(compute, "_load_news_snapshot", _fake_load)


def test_index_multi_ticker_story_scores_each_ticker(monkeypatch) -> None:
    snap = {
        "stories": [
            {"tickers": ["AAPL", "MSFT"], "sentiment_score": 0.8},
            {"tickers": ["AAPL"], "news_score": 0.4},
            {"tickers": ["TSLA"], "sentiment_score": -0.9},
        ]
    }
    _install_snapshot(monkeypatch, snap)

    aapl = compute._get_news_fields("aapl")
    msft = compute._get_news_fields("MSFT")
    tsla = compute._get_news_fields("TSLA")

    # AAPL: mean(0.8, 0.4) = 0.6 → BULLISH
    assert aapl["news_bias"] == "BULLISH"
    assert aapl["news_strength"] == round(0.6, 4)
    # MSFT: only the 0.8 story
    assert msft["news_bias"] == "BULLISH"
    assert msft["news_strength"] == round(0.8, 4)
    # TSLA: -0.9 → BEARISH, strength = abs
    assert tsla["news_bias"] == "BEARISH"
    assert tsla["news_strength"] == round(0.9, 4)


def test_index_unknown_symbol_returns_none(monkeypatch) -> None:
    _install_snapshot(monkeypatch, {"stories": [{"tickers": ["AAPL"], "news_score": 0.5}]})
    assert compute._get_news_fields("ZZZZ") == {"news_strength": None, "news_bias": None}


def test_index_ignores_non_finite_scores(monkeypatch) -> None:
    snap = {"stories": [{"tickers": ["AAPL"], "sentiment_score": "nan"}]}
    _install_snapshot(monkeypatch, snap)
    # non-finite score is treated as missing → no scores → None
    assert compute._get_news_fields("AAPL") == {"news_strength": None, "news_bias": None}


def test_index_rebuilds_on_snapshot_reload(monkeypatch) -> None:
    _install_snapshot(monkeypatch, {"stories": [{"tickers": ["AAPL"], "news_score": 0.5}]})
    assert compute._get_news_fields("AAPL")["news_bias"] == "BULLISH"

    # Reload with a different snapshot; loaded_at advances → index rebuilds.
    _install_snapshot(monkeypatch, {"stories": [{"tickers": ["AAPL"], "news_score": -0.5}]})
    assert compute._get_news_fields("AAPL")["news_bias"] == "BEARISH"
