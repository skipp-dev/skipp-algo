from __future__ import annotations

from streamlit_terminal_pure import (
    build_test_mode_config_overrides,
    build_test_mode_state_defaults,
    build_alert_rule_payload,
    extract_feed_tickers,
    merge_alert_log_entries,
)


def test_test_mode_config_overrides_matches_expected_defaults() -> None:
    assert build_test_mode_config_overrides() == {
        "tv_news_enabled": False,
        "fmp_enabled": False,
        "poll_interval_s": 60.0,
    }


def test_test_mode_state_defaults_uses_injected_now() -> None:
    defaults = build_test_mode_state_defaults(123.0)

    assert defaults["last_poll_ts"] == 123.0
    assert defaults["last_resync_ts"] == 123.0
    assert defaults["auto_refresh"] is False
    assert defaults["provider_cursors"] == {}


def test_extract_feed_tickers_normalizes_and_filters_market_rows() -> None:
    rows = [{"ticker": "aapl"}, {"ticker": " MARKET "}, {"ticker": " msft "}, {"ticker": ""}]

    assert extract_feed_tickers(rows) == ["AAPL", "MSFT"]


def test_extract_feed_tickers_deduplicates_and_applies_limit() -> None:
    rows = [{"ticker": "AAPL"}, {"ticker": "MSFT"}, {"ticker": "AAPL"}]

    assert extract_feed_tickers(rows, limit=1) == ["AAPL"]


def test_build_alert_rule_payload_normalizes_fields() -> None:
    payload = build_alert_rule_payload(
        ticker=" aapl ",
        condition="score >= threshold",
        threshold="0.85",
        category=" Halt ",
        webhook_url=" https://hooks.example.com ",
        created=123.0,
    )

    assert payload == {
        "ticker": "AAPL",
        "condition": "score >= threshold",
        "threshold": 0.85,
        "category": "halt",
        "webhook_url": "https://hooks.example.com",
        "created": 123.0,
    }


def test_build_alert_rule_payload_falls_back_for_invalid_threshold() -> None:
    payload = build_alert_rule_payload(
        ticker="",
        condition="category matches",
        threshold="bad",
        category="",
        webhook_url="",
        created=5.0,
    )

    assert payload["ticker"] == "*"
    assert payload["threshold"] == 0.0


def test_merge_alert_log_entries_prepends_and_caps() -> None:
    merged = merge_alert_log_entries(
        [{"item_id": "new-1"}, {"item_id": "new-2"}],
        [{"item_id": "old-1"}, {"item_id": "old-2"}],
        max_items=3,
    )

    assert merged == [{"item_id": "new-1"}, {"item_id": "new-2"}, {"item_id": "old-1"}]


def test_merge_alert_log_entries_handles_nonpositive_cap() -> None:
    assert merge_alert_log_entries([{"item_id": "new-1"}], [{"item_id": "old-1"}], max_items=0) == []
