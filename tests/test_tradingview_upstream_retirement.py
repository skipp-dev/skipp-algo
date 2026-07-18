"""Runtime guardrails for the retired TradingView upstream surfaces."""

from __future__ import annotations

from open_prep import feature_flags


def test_legacy_news_flags_are_permanently_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_TRADINGVIEW_NEWS", "1")
    monkeypatch.setenv("OPEN_PREP_ENABLE_TRADINGVIEW_NEWS", "1")
    assert feature_flags.is_tradingview_news_enabled() is False
    assert feature_flags.is_open_prep_tradingview_news_enabled() is False


def test_live_news_bus_ignores_explicit_tv_request() -> None:
    from scripts.smc_live_news_bus import fetch_live_news_tv

    result = fetch_live_news_tv(
        symbols=["AAPL"],
        cursor=0.0,
        max_per_ticker=5,
        max_total=5,
        symbol_limit=5,
    )
    assert result.ok is False
    assert result.error == "provider_retired"
    assert result.items == []


def test_equity_technicals_never_enter_retired_tv_adapter(monkeypatch) -> None:
    import terminal_technicals as technicals

    monkeypatch.setattr(technicals, "_TV_AVAILABLE", True)
    monkeypatch.setattr(technicals, "_fmp_fallback", lambda *_args: None)
    monkeypatch.setattr(
        technicals,
        "_try_exchanges",
        lambda *_args: (_ for _ in ()).throw(AssertionError("TradingView adapter called")),
    )
    result = technicals.fetch_technicals("RETIRETV", "1D", force=True)
    assert result.error == "FMP technicals unavailable; TradingView provider retired"


def test_bitcoin_technicals_never_enter_retired_tv_adapter(monkeypatch) -> None:
    import terminal_bitcoin as bitcoin

    bitcoin._cache.clear()
    monkeypatch.setattr(bitcoin, "_TV", True)
    monkeypatch.setattr(
        bitcoin,
        "TA_Handler",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("TradingView adapter called")),
    )
    result = bitcoin.fetch_btc_technicals("1h")
    assert result.error == "TradingView provider retired"
