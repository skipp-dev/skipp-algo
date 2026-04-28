from __future__ import annotations

from types import SimpleNamespace

from streamlit_terminal_config import collect_tv_news_symbols, has_live_news_provider, validate_terminal_config


def _cfg(**overrides: object) -> SimpleNamespace:
    base = {
        "benzinga_api_key": "",
        "fmp_api_key": "",
        "fmp_enabled": False,
        "tv_news_enabled": True,
        "tv_news_symbols": "AAPL,MSFT",
        "tv_news_max_symbols": 3,
        "jsonl_path": "artifacts/feed.jsonl",
        "sqlite_path": "artifacts/feed.db",
        "poll_interval_s": 10.0,
        "feed_max_age_s": 3600.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_collect_tv_news_symbols_merges_configured_and_feed_symbols() -> None:
    cfg = _cfg(tv_news_symbols="AAPL,MSFT", tv_news_max_symbols=4)
    feed = [{"ticker": "TSLA"}, {"ticker": "AAPL"}, {"ticker": "NVDA"}, {"ticker": "MARKET"}]

    assert collect_tv_news_symbols(cfg, feed) == ["AAPL", "MSFT", "TSLA", "NVDA"]


def test_collect_tv_news_symbols_respects_disable_flag() -> None:
    cfg = _cfg(tv_news_enabled=False)

    assert collect_tv_news_symbols(cfg, [{"ticker": "AAPL"}]) == []


def test_collect_tv_news_symbols_respects_max_symbols() -> None:
    cfg = _cfg(tv_news_symbols="AAPL", tv_news_max_symbols=2)
    feed = [{"ticker": "MSFT"}, {"ticker": "NVDA"}]

    assert collect_tv_news_symbols(cfg, feed) == ["AAPL", "MSFT"]


def test_has_live_news_provider_accepts_api_keys() -> None:
    assert has_live_news_provider(_cfg(benzinga_api_key="bz")) is True
    assert has_live_news_provider(_cfg(fmp_enabled=True, fmp_api_key="fmp")) is True


def test_has_live_news_provider_uses_tradingview_symbols_as_fallback() -> None:
    cfg = _cfg(tv_news_symbols="", tv_news_max_symbols=2)

    assert has_live_news_provider(cfg, [{"ticker": "AAPL"}]) is True
    assert has_live_news_provider(_cfg(tv_news_enabled=False, tv_news_symbols=""), [{"ticker": "AAPL"}]) is False


def test_validate_terminal_config_accepts_valid_config() -> None:
    assert validate_terminal_config(_cfg()) == []


def test_validate_terminal_config_reports_invalid_values() -> None:
    cfg = _cfg(
        jsonl_path="",
        sqlite_path="",
        poll_interval_s=0.0,
        feed_max_age_s=-1.0,
        tv_news_max_symbols=0,
        fmp_enabled=True,
        fmp_api_key="",
    )

    assert validate_terminal_config(cfg) == [
        "jsonl_path must not be empty",
        "sqlite_path must not be empty",
        "poll_interval_s must be greater than 0",
        "feed_max_age_s must be greater than or equal to 0",
        "tv_news_max_symbols must be greater than or equal to 1",
        "fmp_api_key must be set when fmp_enabled is true",
    ]


def test_validate_terminal_config_rejects_negative_poll_interval() -> None:
    cfg = _cfg(poll_interval_s=-5.0)

    assert "poll_interval_s must be greater than 0" in validate_terminal_config(cfg)


def test_has_live_news_provider_treats_blank_api_keys_as_missing() -> None:
    cfg = _cfg(
        benzinga_api_key="   ",
        fmp_enabled=True,
        fmp_api_key="   ",
        tv_news_enabled=False,
        tv_news_symbols="",
    )

    assert has_live_news_provider(cfg, []) is False
