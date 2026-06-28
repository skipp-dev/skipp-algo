"""Tests for LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC config and metric."""

from __future__ import annotations

import pytest

from services.live_overlay_daemon import config


class TestExpectMarketTraffic:
    def test_defaults_to_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC", raising=False)
        assert config.expect_market_traffic() is False

    def test_true_when_env_set_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC", "1")
        assert config.expect_market_traffic() is True

    def test_whitespace_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC", " 1 ")
        assert config.expect_market_traffic() is True

    def test_any_non_one_value_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC", "true")
        assert config.expect_market_traffic() is False
