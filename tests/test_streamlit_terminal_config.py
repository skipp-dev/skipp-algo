from __future__ import annotations

from types import SimpleNamespace

from streamlit_terminal_config import has_live_news_provider, validate_terminal_config


def _cfg(**overrides: object) -> SimpleNamespace:
    base = {
        "benzinga_api_key": "",
        "fmp_api_key": "",
        "fmp_enabled": False,
        "jsonl_path": "artifacts/feed.jsonl",
        "sqlite_path": "artifacts/feed.db",
        "poll_interval_s": 10.0,
        "feed_max_age_s": 3600.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_has_live_news_provider_accepts_api_keys() -> None:
    assert has_live_news_provider(_cfg(benzinga_api_key="bz")) is True
    assert has_live_news_provider(_cfg(fmp_enabled=True, fmp_api_key="fmp")) is True


def test_validate_terminal_config_accepts_valid_config() -> None:
    assert validate_terminal_config(_cfg()) == []


def test_validate_terminal_config_reports_invalid_values() -> None:
    cfg = _cfg(
        jsonl_path="",
        sqlite_path="",
        poll_interval_s=0.0,
        feed_max_age_s=-1.0,
        fmp_enabled=True,
        fmp_api_key="",
    )

    assert validate_terminal_config(cfg) == [
        "jsonl_path must not be empty",
        "sqlite_path must not be empty",
        "poll_interval_s must be greater than 0",
        "feed_max_age_s must be greater than or equal to 0",
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
    )

    assert has_live_news_provider(cfg, []) is False
