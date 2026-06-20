"""Reproduction and property tests for the post-merge fixes in live_overlay_daemon.

Goal: demonstrate real bugs through executable tests, not just code-reading critique.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest


class TestNewsSnapshotCachingBug:
    """BUG-1: _load_news_snapshot() cached {} after 'file not found' and ignores
    a file created later during the TTL window.
    """

    def test_newly_created_snapshot_loaded_after_rate_limit_window(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: a snapshot file created after 'file not found' must be picked
        up after the rate-limit window expires, not only after the full load TTL.
        """
        import services.live_overlay_daemon.compute as compute
        import services.live_overlay_daemon.config as cfg

        snapshot_path = tmp_path / "news.json"
        payload = {"stories": [{"tickers": ["AAPL"], "sentiment_score": 0.5}]}

        # Reset cache
        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})
        # Short TTL so the test runs quickly
        monkeypatch.setattr(cfg, "news_cache_ttl_secs", lambda: 0)

        with patch.object(compute.config, "news_snapshot_path", return_value=snapshot_path):
            # First call: snapshot file does not exist yet
            result1 = compute._load_news_snapshot()
            assert result1 == {}
            assert compute._news_loaded_at == 0.0
            assert compute._news_checked_at > 0.0

            # File is now created
            snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

            # Second call: TTL=0, so immediate reload
            result2 = compute._load_news_snapshot()

        assert result2 == payload, (
            "BUG: _load_news_snapshot returned stale empty cache even though "
            f"snapshot file now exists. expected={payload!r}, got={result2!r}"
        )

    def test_missing_file_is_rate_limited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """During the rate-limit TTL a repeatedly missing file is not
        reloaded (no read/log storm).
        """
        import services.live_overlay_daemon.compute as compute
        import services.live_overlay_daemon.config as cfg

        snapshot_path = tmp_path / "news.json"

        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})
        monkeypatch.setattr(cfg, "news_cache_ttl_secs", lambda: 3600)

        with patch.object(compute.config, "news_snapshot_path", return_value=snapshot_path):
            result1 = compute._load_news_snapshot()
            assert result1 == {}

            result2 = compute._load_news_snapshot()
            assert result2 == {}
            assert compute._news_loaded_at == 0.0

    def test_reload_after_ttl_expires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After the TTL expires the file must be reloaded."""
        import services.live_overlay_daemon.compute as compute
        import services.live_overlay_daemon.config as cfg

        snapshot_path = tmp_path / "news.json"
        payload = {"stories": [{"tickers": ["TSLA"], "sentiment_score": -0.3}]}
        snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})
        monkeypatch.setattr(cfg, "news_cache_ttl_secs", lambda: 0)

        with patch.object(compute.config, "news_snapshot_path", return_value=snapshot_path):
            result = compute._load_news_snapshot()

        assert result == payload


class TestVIXZeroCloseBug:
    """BUG-2: A VIX bar with close=0 was previously dropped by the falsy check.
    The fix uses 'is not None'. This test documents the invariant.
    """

    def test_vix_zero_close_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A VIX bar with close=0 must call cache.set_vix(0)."""
        import services.live_overlay_daemon.cache as cache_mod
        import services.live_overlay_daemon.feed as feed_mod

        calls: list[float] = []
        monkeypatch.setattr(cache_mod, "set_vix", calls.append)
        monkeypatch.setattr(cache_mod, "push_bar", lambda sym, bar: None)

        bar = {
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 0.0,
            "volume": 100,
            "ts_event": 0,
        }

        feed_mod._maybe_cache_vix("VIX", bar)

        assert calls == [0.0], f"VIX zero close should be cached, got calls={calls}"


class TestRecordToBarRobustness:
    """Property/replay tests for _record_to_bar and _symbol_from_record."""

    def test_record_to_bar_with_zero_fields(self) -> None:
        """Record values of numeric zero must not produce None."""
        import services.live_overlay_daemon.feed as feed_mod

        record = type(
            "FakeOhlcv",
            (),
            {
                "open": 0,
                "high": 0,
                "low": 0,
                "close": 0,
                "volume": 0,
                "ts_event": 123,
            },
        )()

        bar = feed_mod._record_to_bar(record)
        assert bar is not None
        assert bar["close"] == 0.0
        assert bar["open"] == 0.0

    def test_symbol_from_record_prefers_instrument_id_attribute(self) -> None:
        """_symbol_from_record should prefer .instrument_id over .hd.instrument_id."""
        import services.live_overlay_daemon.feed as feed_mod

        symmap = {42: "SPY"}
        record = type("FakeRecord", (), {"instrument_id": 42})()
        assert feed_mod._symbol_from_record(record, symmap) == "SPY"

    def test_missing_close_must_not_become_zero_for_vix(self) -> None:
        """A missing close field must not be materialized as 0.0."""
        import services.live_overlay_daemon.feed as feed_mod

        record = type(
            "FakeOhlcvMissingClose",
            (),
            {
                "open": 100_000_000_000,
                "high": 101_000_000_000,
                "low": 99_000_000_000,
                # intentionally no close attribute
                "volume": 100,
                "ts_event": 123,
            },
        )()

        bar = feed_mod._record_to_bar(record)
        assert bar is not None
        assert bar["close"] is None, f"missing close must stay None, got {bar['close']!r}"


class TestBuildPayloadInvariants:
    """Invariant tests for build_payload."""

    def test_build_payload_with_empty_bars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty bar list should not raise and should keep fields as None."""
        import services.live_overlay_daemon.compute as compute

        monkeypatch.setattr(compute, "_load_news_snapshot", lambda: {})
        payload = compute.build_payload(
            "AAPL", [], {"tone": "NEUTRAL", "global_heat": 0.0}, 3600
        )

        assert payload["symbol"] == "AAPL"
        assert payload["flow_rel_vol"] is None
        assert payload["flow_delta_proxy_pct"] is None
        assert payload["squeeze_on"] is None
        assert payload["ats_state"] is None
        assert payload["ats_zscore"] is None

    def test_squeeze_on_is_int_when_present(self) -> None:
        """squeeze_on must be int(0/1) or None (schema compliance)."""
        import services.live_overlay_daemon.compute as compute

        bars = [
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100}
            for _ in range(25)
        ]
        squeeze = compute.compute_squeeze_on(bars)
        if squeeze is not None:
            payload = compute.build_payload(
                "AAPL", bars, {"tone": "NEUTRAL", "global_heat": 0.0}, 3600
            )
            assert payload["squeeze_on"] in (0, 1)
            assert type(payload["squeeze_on"]) is int


class TestJsonSafeAndSqueezeIntegrity:
    """B11/B12 regressions from post-merge bug-hunt findings."""

    def test_json_safe_converts_decimal_nan_to_none(self) -> None:
        from services.live_overlay_daemon.main import _json_safe

        assert _json_safe({"x": Decimal("NaN")}) == {"x": None}
        assert _json_safe({"x": Decimal("1.5")}) == {"x": 1.5}

    def test_patch_overlay_decimal_nan_does_not_break_json_path(self) -> None:
        import services.live_overlay_daemon.cache as cache_mod
        from services.live_overlay_daemon.main import _json_safe

        cache_mod.set_overlay({"AAPL": {"vix_level": 20.0}})
        cache_mod.patch_overlay("AAPL", {"vix_level": Decimal("NaN")})

        payload = cache_mod.get_overlay("AAPL")
        assert payload is not None
        # B11: Decimal('NaN') updates must be rejected at patch boundary,
        # preserving the previous finite value.
        assert payload["vix_level"] == 20.0
        assert _json_safe(payload)["vix_level"] == 20.0

    def test_squeeze_on_rejects_close_outside_high_low(self) -> None:
        import services.live_overlay_daemon.compute as compute

        bars = [
            {"open": 100.0, "close": 110.0, "high": 101.0, "low": 99.0, "volume": 100}
            for _ in range(20)
        ]

        result = compute.compute_squeeze_on(bars)
        assert result is not True, (
            "B12: malformed bars with close outside [low, high] must not produce squeeze=True"
        )
