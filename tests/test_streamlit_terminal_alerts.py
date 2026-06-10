from __future__ import annotations

from streamlit_terminal_alerts import evaluate_alert_rules, validate_webhook_url


def _item(**overrides):
    base = {
        "ticker": "AAPL",
        "headline": "Apple beats expectations",
        "news_score": 0.91,
        "sentiment_label": "bullish",
        "materiality": "HIGH",
        "category": "earnings",
        "item_id": "item-1",
        "story_key": "story-1",
        "story_update_kind": "new",
        "attention_active": True,
        "attention_state": "ALERT",
        "attention_score": 0.91,
        "attention_dispatchable": True,
        "attention_reason": "follow_through_alert",
        "posture_state": "LONG",
        "posture_action": "buy",
        "reaction_state": "CONFIRMED",
        "resolution_state": "FOLLOW_THROUGH",
    }
    base.update(overrides)
    return base


def test_validate_webhook_url_rejects_localhost() -> None:
    ok, reason = validate_webhook_url("http://localhost/webhook")

    assert ok is False
    assert reason == "local_host"


def test_validate_webhook_url_rejects_private_resolution() -> None:
    def _resolver(*_args):
        return [(None, None, None, None, ("10.0.0.5", 443))]

    ok, reason = validate_webhook_url("https://hooks.example.com/webhook", resolver=_resolver)

    assert ok is False
    assert reason == "resolved_to_private_or_local_ip"


def test_validate_webhook_url_accepts_public_host() -> None:
    def _resolver(*_args):
        return [(None, None, None, None, ("8.8.8.8", 443))]

    ok, reason = validate_webhook_url("https://hooks.example.com/webhook", resolver=_resolver)

    assert ok is True
    assert reason == ""


def test_validate_webhook_url_rejects_ipv6_loopback() -> None:
    ok, reason = validate_webhook_url("http://[::1]/webhook")

    assert ok is False
    assert reason == "private_or_local_ip"


def test_validate_webhook_url_rejects_link_local_resolution() -> None:
    def _resolver(*_args):
        return [(None, None, None, None, ("169.254.10.20", 443))]

    ok, reason = validate_webhook_url("https://hooks.example.com/webhook", resolver=_resolver)

    assert ok is False
    assert reason == "resolved_to_private_or_local_ip"


def test_validate_webhook_url_rejects_multicast_resolution() -> None:
    def _resolver(*_args):
        return [(None, None, None, None, ("224.0.0.25", 443))]

    ok, reason = validate_webhook_url("https://hooks.example.com/webhook", resolver=_resolver)

    assert ok is False
    assert reason == "resolved_to_private_or_local_ip"


def test_validate_webhook_url_rejects_insecure_http_scheme() -> None:
    def _resolver(*_args):
        return [(None, None, None, None, ("8.8.8.8", 80))]

    ok, reason = validate_webhook_url("http://hooks.example.com/webhook", resolver=_resolver)

    assert ok is False
    assert reason == "insecure_scheme"


def test_validate_webhook_url_rejects_embedded_credentials() -> None:
    def _resolver(*_args):
        return [(None, None, None, None, ("8.8.8.8", 443))]

    ok, reason = validate_webhook_url("https://user:pass@hooks.example.com/webhook", resolver=_resolver)

    assert ok is False
    assert reason == "credentials_not_allowed"


def test_validate_webhook_url_dns_failure_is_rejected() -> None:
    def _resolver(*_args):
        raise OSError("resolver unavailable")

    ok, reason = validate_webhook_url("https://hooks.example.com/webhook", resolver=_resolver)

    assert ok is False
    assert reason == "dns_resolution_failed"


def test_evaluate_alert_rules_dedups_by_story_and_caps_webhooks() -> None:
    rules = [
        {
            "ticker": "AAPL",
            "condition": "score >= threshold",
            "threshold": 0.8,
            "category": "",
            "webhook_url": "https://hooks.example.com/primary",
        },
        {
            "ticker": "*",
            "condition": "sentiment == bullish",
            "threshold": 0.0,
            "category": "",
            "webhook_url": "",
        },
    ]

    evaluation = evaluate_alert_rules(
        [
            _item(),
            _item(item_id="item-2", headline="Duplicate story", story_key="story-1"),
            _item(item_id="item-3", ticker="MSFT", attention_active=False),
        ],
        rules,
        webhook_budget=1,
        now=1700000000.0,
        webhook_validator=lambda _url: (True, ""),
    )

    assert len(evaluation["alert_log_entries"]) == 2
    assert len(evaluation["pending_webhooks"]) == 1
    assert evaluation["pending_webhooks"][0][0] == "https://hooks.example.com/primary"
    assert {entry["rule"] for entry in evaluation["alert_log_entries"]} == {
        "score >= threshold",
        "sentiment == bullish",
    }


def test_evaluate_alert_rules_empty_items_is_safe() -> None:
    evaluation = evaluate_alert_rules([], [{"ticker": "AAPL", "condition": "score >= threshold", "threshold": 0.8}], webhook_budget=2, now=1700000000.0)

    assert evaluation == {"alert_log_entries": [], "pending_webhooks": []}


def test_evaluate_alert_rules_budget_exhausted_skips_webhooks() -> None:
    evaluation = evaluate_alert_rules(
        [_item()],
        [{"ticker": "AAPL", "condition": "score >= threshold", "threshold": 0.8, "webhook_url": "https://hooks.example.com/primary"}],
        webhook_budget=0,
        now=1700000000.0,
        webhook_validator=lambda _url: (True, ""),
    )

    assert len(evaluation["alert_log_entries"]) == 1
    assert evaluation["pending_webhooks"] == []


def test_evaluate_alert_rules_no_matching_rules_returns_empty() -> None:
    evaluation = evaluate_alert_rules(
        [_item(ticker="MSFT", sentiment_label="neutral", news_score=0.2)],
        [{"ticker": "AAPL", "condition": "score >= threshold", "threshold": 0.8, "webhook_url": "https://hooks.example.com/primary"}],
        webhook_budget=1,
        now=1700000000.0,
        webhook_validator=lambda _url: (True, ""),
    )

    assert evaluation == {"alert_log_entries": [], "pending_webhooks": []}


def test_evaluate_alert_rules_filters_invalid_webhook_urls() -> None:
    evaluation = evaluate_alert_rules(
        [_item()],
        [{"ticker": "AAPL", "condition": "score >= threshold", "threshold": 0.8, "webhook_url": "http://hooks.example.com/primary"}],
        webhook_budget=1,
        now=1700000000.0,
        webhook_validator=lambda _url: (False, "insecure_scheme"),
    )

    assert len(evaluation["alert_log_entries"]) == 1
    assert evaluation["pending_webhooks"] == []
