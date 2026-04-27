"""Unit tests for ``open_prep.sentiment_fng`` (CNN equity F&G)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from open_prep.sentiment_fng import (
    _bucket_label,
    fetch_cnn_equity_fear_greed,
)


def _mock_urlopen(payload: bytes | str | Exception) -> MagicMock:
    if isinstance(payload, Exception):
        raise AssertionError("call _patch with side_effect for exceptions")
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    response = MagicMock()
    response.read.return_value = body
    cm = MagicMock()
    cm.__enter__.return_value = response
    cm.__exit__.return_value = False
    return cm


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "Extreme Fear"),
        (24, "Extreme Fear"),
        (25, "Fear"),
        (44, "Fear"),
        (45, "Neutral"),
        (54, "Neutral"),
        (55, "Greed"),
        (74, "Greed"),
        (75, "Extreme Greed"),
        (100, "Extreme Greed"),
    ],
)
def test_bucket_label_matches_terminal_bitcoin_thresholds(value, expected):
    assert _bucket_label(float(value)) == expected


def test_fetch_cnn_equity_fear_greed_happy_path():
    payload = json.dumps(
        {"fear_and_greed": {"score": 72.4, "rating": "greed"}}
    )
    with patch("open_prep.sentiment_fng.urlopen", return_value=_mock_urlopen(payload)):
        out = fetch_cnn_equity_fear_greed()
    assert out is not None
    assert out["value"] == 72.4
    assert out["label"] == "Greed"
    assert out["raw_label"] == "greed"
    assert out["source"] == "cnn"
    assert "fetched_at" in out


def test_fetch_cnn_equity_fear_greed_network_failure_returns_none():
    import urllib.error

    def raise_url_error(*_a, **_kw):
        raise urllib.error.URLError("DNS lookup failed")

    with patch("open_prep.sentiment_fng.urlopen", side_effect=raise_url_error):
        assert fetch_cnn_equity_fear_greed() is None


def test_fetch_cnn_equity_fear_greed_timeout_returns_none():
    def raise_timeout(*_a, **_kw):
        raise TimeoutError("read timeout")

    with patch("open_prep.sentiment_fng.urlopen", side_effect=raise_timeout):
        assert fetch_cnn_equity_fear_greed() is None


def test_fetch_cnn_equity_fear_greed_invalid_json_returns_none():
    with patch(
        "open_prep.sentiment_fng.urlopen",
        return_value=_mock_urlopen("<html>oops not json</html>"),
    ):
        assert fetch_cnn_equity_fear_greed() is None


def test_fetch_cnn_equity_fear_greed_missing_object_returns_none():
    with patch(
        "open_prep.sentiment_fng.urlopen",
        return_value=_mock_urlopen(json.dumps({"unrelated": True})),
    ):
        assert fetch_cnn_equity_fear_greed() is None


def test_fetch_cnn_equity_fear_greed_missing_score_returns_none():
    with patch(
        "open_prep.sentiment_fng.urlopen",
        return_value=_mock_urlopen(
            json.dumps({"fear_and_greed": {"rating": "greed"}})
        ),
    ):
        assert fetch_cnn_equity_fear_greed() is None


def test_fetch_cnn_equity_fear_greed_score_out_of_range_returns_none():
    # CNN endpoint should never emit values outside 0..100; if it does
    # it almost certainly indicates a schema change and we must not
    # silently propagate garbage into the regime snapshot.
    with patch(
        "open_prep.sentiment_fng.urlopen",
        return_value=_mock_urlopen(
            json.dumps({"fear_and_greed": {"score": 150, "rating": "?"}})
        ),
    ):
        assert fetch_cnn_equity_fear_greed() is None


def test_fetch_cnn_equity_fear_greed_bool_score_returns_none():
    # Defensive: bool is an int subclass; True must not coerce to 1.0.
    with patch(
        "open_prep.sentiment_fng.urlopen",
        return_value=_mock_urlopen(
            json.dumps({"fear_and_greed": {"score": True, "rating": "?"}})
        ),
    ):
        assert fetch_cnn_equity_fear_greed() is None
