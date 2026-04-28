from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

from terminal_export import fire_webhook
from terminal_poller import ClassifiedItem


def _make_ci(**overrides: Any) -> ClassifiedItem:
    defaults: dict[str, Any] = {
        "item_id": "wh1",
        "ticker": "NVDA",
        "tickers_all": ["NVDA"],
        "headline": "NVIDIA beats estimates",
        "snippet": "Details",
        "url": "https://example.com/article",
        "source": "Benzinga",
        "published_ts": time.time(),
        "updated_ts": time.time(),
        "provider": "benzinga_rest",
        "category": "earnings",
        "impact": 0.80,
        "clarity": 0.70,
        "polarity": 0.5,
        "news_score": 0.85,
        "cluster_hash": "abc",
        "novelty_count": 1,
        "sentiment_label": "bullish",
        "sentiment_score": 0.6,
        "event_class": "SCHEDULED",
        "event_label": "earnings",
        "materiality": "MEDIUM",
        "recency_bucket": "FRESH",
        "age_minutes": 5.0,
        "is_actionable": True,
        "source_tier": "TIER_2",
        "source_rank": 2,
        "channels": [],
        "tags": [],
        "relevance": 0.5,
        "entity_count": 1,
        "is_wiim": False,
        "attention_active": True,
        "attention_dispatchable": True,
        "attention_state": "ALERT",
        "posture_state": "LONG",
        "posture_action": "buy",
        "reaction_state": "WATCH",
        "reaction_actionable": True,
        "resolution_state": "FOLLOW_THROUGH",
    }
    defaults.update(overrides)
    return ClassifiedItem(**defaults)


@patch("terminal_export.validate_webhook_url", return_value=(False, "local_host"))
def test_fire_webhook_rejects_invalid_target_before_http_call(_mock_validate) -> None:
    mock_client = MagicMock()

    result = fire_webhook(_make_ci(), url="http://localhost/webhook", _client=mock_client)

    assert result is None
    mock_client.post.assert_not_called()


@patch("terminal_export.validate_webhook_url", return_value=(True, ""))
def test_fire_webhook_posts_without_redirects(_mock_validate) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response

    result = fire_webhook(_make_ci(), url="https://hooks.example.com/webhook", _client=mock_client)

    assert result == {"ok": True}
    assert mock_client.post.call_args.kwargs["follow_redirects"] is False
