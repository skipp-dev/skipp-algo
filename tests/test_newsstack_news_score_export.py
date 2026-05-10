from __future__ import annotations

import newsstack_fmp


def test_newsstack_package_exports_latest_news_score() -> None:
    from newsstack_fmp import pipeline

    with pipeline._bbt_lock:
        old = dict(pipeline._best_by_ticker)
        pipeline._best_by_ticker.clear()
        pipeline._best_by_ticker.update(
            {
                "AAPL": {"ticker": "AAPL", "news_score": "0.82"},
                "MSFT": {"ticker": "MSFT", "news_score": None},
                "BAD": {"ticker": "BAD", "news_score": "not-a-number"},
            }
        )
    try:
        assert newsstack_fmp.get_news_score("aapl") == 0.82
        assert newsstack_fmp.get_news_score("MSFT") == 0.0
        assert newsstack_fmp.get_news_score("BAD") == 0.0
        assert newsstack_fmp.get_news_score("UNKNOWN") == 0.0
    finally:
        with pipeline._bbt_lock:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker.update(old)


def test_smc_bridge_uses_newsstack_news_score_export(monkeypatch) -> None:
    import smc_tv_bridge.smc_api as api

    monkeypatch.setattr(newsstack_fmp, "get_news_score", lambda symbol: 0.42 if symbol == "AAPL" else 0.0)

    assert api._get_news_score("AAPL") == 0.42
