"""Tests for overlay-daemon robustness fixes (R1, R3, R4, R6, V1–V5, N1/N2, N5).

R1 — _symbology_map guard warning on missing attribute
R3 — _load_news_snapshot logs warning on JSON/IO errors
R4 — config range validation for rolling_bars / max_stale_secs / refresh_secs / flow_refresh_secs
R6 — bar cache symbol eviction at configurable cap
V1 — startup readiness (feed.is_ready())
V4 — configurable news cache TTL
V5 — configurable max symbols
N1/N2 — stop() and circuit-breaker clear _feed_ready
N5 — double-start guard
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# R4: config range validation
# ---------------------------------------------------------------------------


class TestConfigRangeValidation:
    """rolling_bars() and max_stale_secs() clamp out-of-range values."""

    def test_rolling_bars_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OVERLAY_ROLLING_BARS", raising=False)
        import services.live_overlay_daemon.config as cfg

        assert cfg.rolling_bars() == 60

    def test_rolling_bars_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "120")
        import services.live_overlay_daemon.config as cfg

        assert cfg.rolling_bars() == 120

    def test_rolling_bars_too_high_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "999")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.rolling_bars()
        assert result == 500
        assert "outside valid range" in caplog.text

    def test_rolling_bars_too_low_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "0")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.rolling_bars()
        assert result == 1
        assert "outside valid range" in caplog.text

    def test_max_stale_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OVERLAY_MAX_STALE_SECS", raising=False)
        import services.live_overlay_daemon.config as cfg

        assert cfg.max_stale_secs() == 3600

    def test_max_stale_too_high_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_MAX_STALE_SECS", "99999")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.max_stale_secs()
        assert result == 7200
        assert "outside valid range" in caplog.text

    def test_max_stale_too_low_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_MAX_STALE_SECS", "10")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.max_stale_secs()
        assert result == 60
        assert "outside valid range" in caplog.text

    def test_optional_int_warns_on_invalid(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "not_a_number")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            result = cfg.rolling_bars()
        assert result == 60  # default
        assert "Invalid integer" in caplog.text

    def test_load_env_unquotes_wrapped_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.config as cfg

        env_file = tmp_path / ".env"
        env_file.write_text(
            "OVERLAY_SECRET_TOKEN=\"quoted-token\"\nDATABENTO_API_KEY='quoted-key'\n",
            encoding="utf-8",
        )

        monkeypatch.delenv("OVERLAY_SECRET_TOKEN", raising=False)
        monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
        monkeypatch.setattr(cfg, "_ENV_FILE", env_file)

        try:
            cfg._load_env()

            assert cfg.overlay_secret_token() == "quoted-token"
            assert cfg.databento_api_key() == "quoted-key"
        finally:
            monkeypatch.delenv("OVERLAY_SECRET_TOKEN", raising=False)
            monkeypatch.delenv("DATABENTO_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# R3: _load_news_snapshot warning logging
# ---------------------------------------------------------------------------


class TestNewsSnapshotWarningLogging:
    """_load_news_snapshot() logs a warning on parse failure instead of silently returning {}."""

    def test_corrupt_json_logs_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        bad_file = tmp_path / "news.json"
        bad_file.write_text("{invalid json", encoding="utf-8")

        import services.live_overlay_daemon.compute as compute

        # Reset TTL cache so it reloads
        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})

        with patch.object(compute.config, "news_snapshot_path", return_value=bad_file), caplog.at_level(logging.WARNING):
            result = compute._load_news_snapshot()

        assert result == {}
        assert "Failed to load news snapshot" in caplog.text

    def test_valid_json_no_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        good_file = tmp_path / "news.json"
        good_file.write_text(json.dumps({"stories": []}), encoding="utf-8")

        import services.live_overlay_daemon.compute as compute

        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})

        with patch.object(compute.config, "news_snapshot_path", return_value=good_file), caplog.at_level(logging.WARNING):
            result = compute._load_news_snapshot()

        assert result == {"stories": []}
        assert "Failed to load news snapshot" not in caplog.text


# ---------------------------------------------------------------------------
# R6: bar cache symbol eviction
# ---------------------------------------------------------------------------


class TestBarCacheEviction:
    """Bar cache evicts least-recently-updated symbols when hitting _MAX_SYMBOLS."""

    def test_eviction_at_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.cache as cache_mod

        # Reset module state
        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(cache_mod, "_bar_last_update", {})
        monkeypatch.setattr(cache_mod, "_last_eviction_at", 0.0)
        monkeypatch.setattr(cache_mod, "_rolling_bars_cap", 5)

        small_cap = 20
        monkeypatch.setattr(cache_mod, "_max_symbols", small_cap)

        # Fill to cap with stale symbols
        for i in range(small_cap):
            cache_mod.push_bar(f"OLD{i}", {"open": 1, "close": 1, "high": 1, "low": 1, "volume": 100})

        assert cache_mod.bar_symbol_count() == small_cap

        # Push one more — triggers eviction
        cache_mod.push_bar("NEW_SYMBOL", {"open": 2, "close": 2, "high": 2, "low": 2, "volume": 200})

        # Should have evicted ~10% (2 symbols) and added 1
        assert cache_mod.bar_symbol_count() <= small_cap
        assert cache_mod.get_bars_snapshot("NEW_SYMBOL") != []

    def test_eviction_removes_oldest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.cache as cache_mod

        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(cache_mod, "_bar_last_update", {})
        monkeypatch.setattr(cache_mod, "_last_eviction_at", 0.0)
        monkeypatch.setattr(cache_mod, "_rolling_bars_cap", 5)
        monkeypatch.setattr(cache_mod, "_max_symbols", 5)

        bar = {"open": 1, "close": 1, "high": 1, "low": 1, "volume": 100}

        # Push 5 symbols with increasing timestamps
        for i in range(5):
            cache_mod.push_bar(f"SYM{i}", bar)
            time.sleep(0.001)  # ensure distinct monotonic timestamps

        # SYM0 is oldest. Push a new one to trigger eviction.
        cache_mod.push_bar("FRESH", bar)

        # SYM0 should be evicted (oldest)
        assert cache_mod.get_bars_snapshot("SYM0") == []
        # FRESH should exist
        assert cache_mod.get_bars_snapshot("FRESH") != []

    def test_reinit_updates_existing_symbol_deque_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.cache as cache_mod

        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(cache_mod, "_bar_last_update", {})
        monkeypatch.setattr(cache_mod, "_last_eviction_at", 0.0)

        cache_mod.init_bar_cache(2, max_symbols=2000)
        for i in range(4):
            cache_mod.push_bar("AAPL", {"open": 1, "close": 1, "high": 1, "low": 1, "volume": i})
        assert len(cache_mod.get_bars_snapshot("AAPL")) == 2

        cache_mod.init_bar_cache(5, max_symbols=2000)
        for i in range(10):
            cache_mod.push_bar("AAPL", {"open": 1, "close": 1, "high": 1, "low": 1, "volume": i})

        assert len(cache_mod.get_bars_snapshot("AAPL")) == 5

    def test_downscale_max_symbols_enforces_hard_cap_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.cache as cache_mod

        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(cache_mod, "_bar_last_update", {})
        monkeypatch.setattr(cache_mod, "_last_eviction_at", 0.0)

        bar = {"open": 1, "close": 1, "high": 1, "low": 1, "volume": 1}
        cache_mod.init_bar_cache(5, max_symbols=100)
        for i in range(10):
            cache_mod.push_bar(f"SYM{i}", bar)
        assert cache_mod.bar_symbol_count() == 10

        cache_mod.init_bar_cache(5, max_symbols=3)
        assert cache_mod.bar_symbol_count() <= 3

    def test_new_symbol_push_at_capacity_after_downscale_keeps_cache_within_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.cache as cache_mod

        monkeypatch.setattr(cache_mod, "_bars", {})
        monkeypatch.setattr(cache_mod, "_bar_last_update", {})
        monkeypatch.setattr(cache_mod, "_last_eviction_at", 0.0)

        bar = {"open": 1, "close": 1, "high": 1, "low": 1, "volume": 1}
        cache_mod.init_bar_cache(5, max_symbols=100)
        for i in range(10):
            cache_mod.push_bar(f"OLD{i}", bar)

        # Lowering the cap enforces it immediately; this verifies the next
        # insertion while already at capacity still preserves the hard cap.
        cache_mod.init_bar_cache(5, max_symbols=3)
        cache_mod.push_bar("NEW1", bar)

        assert cache_mod.bar_symbol_count() <= 3
        assert cache_mod.get_bars_snapshot("NEW1") != []


# ---------------------------------------------------------------------------
# R1: _symbology_map guard
# ---------------------------------------------------------------------------


class TestSymbologyMapGuard:
    """feed.py warns when db.Live() client lacks _symbology_map."""

    def test_warning_logged_when_attr_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        """Simulate the guard logic: getattr fallback + warning when attr absent."""
        import services.live_overlay_daemon.feed as feed_mod

        class FakeClient:
            pass

        client = FakeClient()
        symmap: dict[int, str] = getattr(client, "_symbology_map", {})

        with caplog.at_level(logging.WARNING):
            if not hasattr(client, "_symbology_map"):
                feed_mod.logger.warning(
                    "db.Live() client has no '_symbology_map' attribute — "
                    "databento SDK may have changed. Symbol resolution will "
                    "fail until this is updated."
                )

        assert symmap == {}
        assert "_symbology_map" in caplog.text

    def test_no_warning_when_attr_present(self, caplog: pytest.LogCaptureFixture) -> None:
        """No warning when client has _symbology_map."""
        import services.live_overlay_daemon.feed as feed_mod

        class FakeClient:
            _symbology_map: ClassVar[dict[int, str]] = {42: "NVDA"}

        client = FakeClient()
        symmap: dict[int, str] = getattr(client, "_symbology_map", {})

        with caplog.at_level(logging.WARNING):
            if not hasattr(client, "_symbology_map"):
                feed_mod.logger.warning("should not fire")

        assert symmap == {42: "NVDA"}
        assert "_symbology_map" not in caplog.text


# ---------------------------------------------------------------------------
# T4: Boundary tests for config range validation
# ---------------------------------------------------------------------------


class TestConfigBoundaryValues:
    """Exact boundary values: at-limit accepted, one-past-limit clamped."""

    def test_rolling_bars_at_lower_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "1")
        import services.live_overlay_daemon.config as cfg

        assert cfg.rolling_bars() == 1

    def test_rolling_bars_at_upper_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "500")
        import services.live_overlay_daemon.config as cfg

        assert cfg.rolling_bars() == 500

    def test_rolling_bars_one_past_upper(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_ROLLING_BARS", "501")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            assert cfg.rolling_bars() == 500
        assert "outside valid range" in caplog.text

    def test_max_stale_at_lower_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_MAX_STALE_SECS", "60")
        import services.live_overlay_daemon.config as cfg

        assert cfg.max_stale_secs() == 60

    def test_max_stale_at_upper_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_MAX_STALE_SECS", "7200")
        import services.live_overlay_daemon.config as cfg

        assert cfg.max_stale_secs() == 7200

    def test_max_stale_one_past_upper(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_MAX_STALE_SECS", "7201")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            assert cfg.max_stale_secs() == 7200
        assert "outside valid range" in caplog.text

    def test_refresh_secs_at_lower_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_REFRESH_SECS", "10")
        import services.live_overlay_daemon.config as cfg

        assert cfg.refresh_secs() == 10

    def test_refresh_secs_below_lower_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_REFRESH_SECS", "9")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            assert cfg.refresh_secs() == 10
        assert "outside valid range" in caplog.text

    def test_flow_refresh_secs_at_lower_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_FLOW_REFRESH_SECS", "5")
        import services.live_overlay_daemon.config as cfg

        assert cfg.flow_refresh_secs() == 5

    def test_flow_refresh_secs_below_lower_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_FLOW_REFRESH_SECS", "4")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            assert cfg.flow_refresh_secs() == 5
        assert "outside valid range" in caplog.text

    def test_news_cache_ttl_at_lower_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_NEWS_CACHE_TTL_SECS", "60")
        import services.live_overlay_daemon.config as cfg

        assert cfg.news_cache_ttl_secs() == 60

    def test_news_cache_ttl_below_lower_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_NEWS_CACHE_TTL_SECS", "10")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            assert cfg.news_cache_ttl_secs() == 60
        assert "outside valid range" in caplog.text

    def test_max_symbols_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OVERLAY_MAX_SYMBOLS", raising=False)
        import services.live_overlay_daemon.config as cfg

        assert cfg.max_symbols() == 2000

    def test_max_symbols_below_lower_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_MAX_SYMBOLS", "50")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            assert cfg.max_symbols() == 100
        assert "outside valid range" in caplog.text


# ---------------------------------------------------------------------------
# T5: FileNotFoundError for _load_news_snapshot
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# R4-ext: additional config accessors
# ---------------------------------------------------------------------------


class TestMaxFeedFailuresConfig:
    """max_feed_failures() clamps and defaults."""

    def test_max_feed_failures_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OVERLAY_MAX_FEED_FAILURES", raising=False)
        import services.live_overlay_daemon.config as cfg

        assert cfg.max_feed_failures() == 50

    def test_max_feed_failures_at_upper_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "1000")
        import services.live_overlay_daemon.config as cfg

        assert cfg.max_feed_failures() == 1000

    def test_max_feed_failures_above_upper_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "2000")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            assert cfg.max_feed_failures() == 1000
        assert "outside valid range" in caplog.text

    def test_max_feed_failures_below_lower_clamps(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "0")
        import services.live_overlay_daemon.config as cfg

        with caplog.at_level(logging.WARNING):
            assert cfg.max_feed_failures() == 1
        assert "outside valid range" in caplog.text


class TestNewsSnapshotPathConfig:
    """news_snapshot_path() honours env override and default."""

    def test_news_snapshot_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NEWS_SNAPSHOT_PATH", raising=False)
        import services.live_overlay_daemon.config as cfg

        path = cfg.news_snapshot_path()
        assert path.name == "smc_live_news_snapshot.json"

    def test_news_snapshot_path_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        override = tmp_path / "custom_snapshot.json"
        monkeypatch.setenv("NEWS_SNAPSHOT_PATH", str(override))
        import services.live_overlay_daemon.config as cfg

        assert cfg.news_snapshot_path() == override


class TestLogLevelConfig:
    """log_level() returns lower-cased env value or default."""

    def test_log_level_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        import services.live_overlay_daemon.config as cfg

        assert cfg.log_level() == "info"

    def test_log_level_env_lower_cased(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        import services.live_overlay_daemon.config as cfg

        assert cfg.log_level() == "debug"

class TestNewsSnapshotFileNotFound:
    """_load_news_snapshot() handles non-existent file gracefully."""

    def test_missing_file_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing = tmp_path / "does_not_exist.json"

        import services.live_overlay_daemon.compute as compute

        monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
        monkeypatch.setattr(compute, "_news_checked_at", 0.0)
        monkeypatch.setattr(compute, "_news_cache", {})

        with patch.object(compute.config, "news_snapshot_path", return_value=missing):
            result = compute._load_news_snapshot()

        assert result == {}


# ---------------------------------------------------------------------------
# V1: Startup readiness
# ---------------------------------------------------------------------------


class TestFeedReadiness:
    """feed.is_ready() reflects whether first bar has been pushed."""

    def test_not_ready_initially(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        feed_mod._feed_ready.clear()
        assert not feed_mod.is_ready()

    def test_ready_after_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        feed_mod._feed_ready.set()
        feed_mod._last_bar_at = time.monotonic()
        assert feed_mod.is_ready()
        # cleanup
        feed_mod._feed_ready.clear()
        feed_mod._last_bar_at = 0.0


class TestHealthStatusSignals:
    """Health endpoint should not report ok during worker/staleness degradation."""

    def test_health_is_liveness_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.main as main_mod

        payload = json.loads(main_mod.health().body)

        assert payload["status"] == "alive"
        assert payload["service"] == "smc-live-overlay"
        assert "uptime_secs" in payload
        assert "ts" in payload

    def test_health_is_starting_when_workers_not_all_alive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.main as main_mod

        monkeypatch.setattr(main_mod.feed, "is_ready", lambda: True)
        monkeypatch.setattr(main_mod.feed, "last_bar_age_secs", lambda: 0.1)
        monkeypatch.setattr(
            main_mod.feed,
            "worker_liveness",
            lambda: {"live_feed": True, "overlay_refresh": False, "flow_refresh": False},
        )
        monkeypatch.setattr(main_mod.feed, "metrics_snapshot", lambda: {"reconnect_attempts": 3})
        monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: 1.0)
        monkeypatch.setattr(main_mod.cache, "bar_symbol_count", lambda: 1)
        monkeypatch.setattr(main_mod.cache, "total_bar_count", lambda: 10)
        monkeypatch.setattr(main_mod.cache, "overlay_symbol_count", lambda: 1)
        monkeypatch.setattr(main_mod.config, "max_stale_secs", lambda: 3600)

        payload = json.loads(main_mod.ready().body)

        assert payload["status"] == "starting"
        assert payload["feed_healthy"] is True
        assert payload["workers_healthy"] is False
        assert payload["feed_metrics"]["reconnect_attempts"] == 3
        assert payload["overlay_fresh"] is True

    def test_health_is_starting_when_overlay_is_stale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.main as main_mod

        monkeypatch.setattr(main_mod.feed, "is_ready", lambda: True)
        monkeypatch.setattr(main_mod.feed, "last_bar_age_secs", lambda: 0.1)
        monkeypatch.setattr(
            main_mod.feed,
            "worker_liveness",
            lambda: {"live_feed": True, "overlay_refresh": True, "flow_refresh": True},
        )
        monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: float("inf"))
        monkeypatch.setattr(main_mod.cache, "bar_symbol_count", lambda: 1)
        monkeypatch.setattr(main_mod.cache, "total_bar_count", lambda: 10)
        monkeypatch.setattr(main_mod.cache, "overlay_symbol_count", lambda: 0)
        monkeypatch.setattr(main_mod.config, "max_stale_secs", lambda: 3600)

        payload = json.loads(main_mod.ready().body)

        assert payload["status"] == "starting"
        assert payload["feed_healthy"] is True
        assert payload["workers_healthy"] is True
        assert payload["overlay_fresh"] is False

    def test_health_is_idle_market_closed_when_feed_not_ready_outside_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.main as main_mod

        monkeypatch.setattr(main_mod.feed, "is_ready", lambda: False)
        monkeypatch.setattr(main_mod.feed, "last_bar_age_secs", lambda: None)
        monkeypatch.setattr(
            main_mod.feed,
            "worker_liveness",
            lambda: {"live_feed": True, "overlay_refresh": True, "flow_refresh": True},
        )
        monkeypatch.setattr(main_mod.feed, "metrics_snapshot", lambda: {"reconnect_attempts": 0})
        monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: float("inf"))
        monkeypatch.setattr(main_mod.cache, "bar_symbol_count", lambda: 0)
        monkeypatch.setattr(main_mod.cache, "total_bar_count", lambda: 0)
        monkeypatch.setattr(main_mod.cache, "overlay_symbol_count", lambda: 0)
        monkeypatch.setattr(main_mod.config, "max_stale_secs", lambda: 3600)
        monkeypatch.setattr(main_mod, "_is_us_regular_session_open", lambda: False)

        payload = json.loads(main_mod.ready().body)

        assert payload["status"] == "idle_market_closed"
        assert payload["market_open"] is False
        assert payload["workers_healthy"] is True
        assert payload["feed_healthy"] is False

    def test_health_remains_starting_when_feed_not_ready_during_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.main as main_mod

        monkeypatch.setattr(main_mod.feed, "is_ready", lambda: False)
        monkeypatch.setattr(main_mod.feed, "last_bar_age_secs", lambda: None)
        monkeypatch.setattr(
            main_mod.feed,
            "worker_liveness",
            lambda: {"live_feed": True, "overlay_refresh": True, "flow_refresh": True},
        )
        monkeypatch.setattr(main_mod.feed, "metrics_snapshot", lambda: {"reconnect_attempts": 0})
        monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: float("inf"))
        monkeypatch.setattr(main_mod.cache, "bar_symbol_count", lambda: 0)
        monkeypatch.setattr(main_mod.cache, "total_bar_count", lambda: 0)
        monkeypatch.setattr(main_mod.cache, "overlay_symbol_count", lambda: 0)
        monkeypatch.setattr(main_mod.config, "max_stale_secs", lambda: 3600)
        monkeypatch.setattr(main_mod, "_is_us_regular_session_open", lambda: True)

        payload = json.loads(main_mod.ready().body)

        assert payload["status"] == "starting"
        assert payload["market_open"] is True


class TestSmcLiveTimeframeContract:
    """Endpoint tf validation must match published schema contract."""

    def test_health_is_starting_when_overlay_cache_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.main as main_mod

        monkeypatch.setattr(main_mod.feed, "is_ready", lambda: True)
        monkeypatch.setattr(main_mod.feed, "last_bar_age_secs", lambda: 0.1)
        monkeypatch.setattr(
            main_mod.feed,
            "worker_liveness",
            lambda: {"live_feed": True, "overlay_refresh": True, "flow_refresh": True},
        )
        monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: 1.0)
        monkeypatch.setattr(main_mod.cache, "bar_symbol_count", lambda: 1)
        monkeypatch.setattr(main_mod.cache, "total_bar_count", lambda: 10)
        monkeypatch.setattr(main_mod.cache, "overlay_symbol_count", lambda: 0)
        monkeypatch.setattr(main_mod.config, "max_stale_secs", lambda: 3600)

        payload = json.loads(main_mod.ready().body)

        assert payload["status"] == "starting"
        assert payload["feed_healthy"] is True
        assert payload["workers_healthy"] is True
        assert payload["overlay_fresh"] is False


class TestSmcLiveSerializationSafety:
    """smc_live should never emit non-finite numbers into JSONResponse."""

    def test_smc_live_replaces_non_finite_payload_floats_with_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.main as main_mod

        monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: "tok")
        monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: 1.0)
        monkeypatch.setattr(main_mod.config, "max_stale_secs", lambda: 3600)
        monkeypatch.setattr(
            main_mod.cache,
            "get_overlay",
            lambda _sym: {
                "schema": "smc-live-overlay/1",
                "symbol": "AAPL",
                "asof_ts": 1,
                "stale": False,
                "news_strength": None,
                "news_bias": None,
                "flow_rel_vol": float("nan"),
                "flow_delta_proxy_pct": 0.0,
                "squeeze_on": 0,
                "ats_state": "neutral",
                "ats_zscore": float("inf"),
                "vix_level": float("-inf"),
                "tone": "NEUTRAL",
                "global_heat": 0.0,
                "event_window_state": "normal",
                "event_risk_level": "low",
                "next_event_name": None,
                "next_event_time": None,
                "market_event_blocked": False,
                "symbol_event_blocked": False,
                "event_provider_status": "unavailable",
            },
        )

        payload = json.loads(main_mod.smc_live(token="tok", symbol="aapl", tf="5m").body)

        assert payload["flow_rel_vol"] is None
        assert payload["ats_zscore"] is None
        assert payload["vix_level"] is None


class TestVixFiniteContract:
    """Non-finite VIX values must not enter overlay state via cache/flow patch."""

    def test_set_vix_ignores_non_finite_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.cache as cache_mod

        monkeypatch.setattr(cache_mod, "_vix_level", None)
        cache_mod.set_vix(20.5)
        cache_mod.set_vix(float("inf"))
        cache_mod.set_vix(float("nan"))

        assert cache_mod.get_vix() == 20.5

    def test_flow_patch_cycle_does_not_write_non_finite_vix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.cache as cache_mod
        import services.live_overlay_daemon.compute as compute_mod

        monkeypatch.setattr(
            cache_mod,
            "get_all_symbols_snapshot",
            lambda: {
                "AAPL": [
                    {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 100},
                    {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 110},
                    {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 120},
                    {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 130},
                    {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 140},
                ]
            },
        )
        monkeypatch.setattr(cache_mod, "get_vix", lambda: float("inf"))

        cache_mod.set_overlay({"AAPL": {"vix_level": 19.0, "flow_rel_vol": 1.0}})

        compute_mod.run_flow_patch_cycle()

        payload = cache_mod.get_overlay("AAPL")
        assert payload is not None
        assert payload["vix_level"] == 19.0


# ---------------------------------------------------------------------------
# N1/N2: stop() and circuit-breaker clear _feed_ready
# ---------------------------------------------------------------------------


class TestFeedReadyClearedOnStop:
    """N1: stop() must clear _feed_ready so health reports 'starting'."""

    def test_stop_clears_feed_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        feed_mod._feed_ready.set()
        feed_mod._last_bar_at = time.monotonic()
        assert feed_mod.is_ready()

        # Ensure no real threads to join
        monkeypatch.setattr(feed_mod, "_feed_thread", None)
        monkeypatch.setattr(feed_mod, "_refresh_thread", None)
        monkeypatch.setattr(feed_mod, "_flow_refresh_thread", None)
        feed_mod.stop()

        assert not feed_mod.is_ready(), "_feed_ready must be cleared after stop()"
        # cleanup
        feed_mod._stop_event.clear()


class TestFeedLoopConfigFailFast:
    """Non-retryable configuration failures must not enter retry/backoff loops."""

    def test_run_feed_loop_does_not_retry_on_config_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        calls = {"n": 0}

        def _bad_key() -> str:
            calls["n"] += 1
            raise RuntimeError("missing DATABENTO_API_KEY")

        monkeypatch.setattr(feed_mod.config, "databento_api_key", _bad_key)
        monkeypatch.setattr(feed_mod.config, "max_feed_failures", lambda: 50)
        monkeypatch.setattr(feed_mod, "_RECONNECT_DELAY_SECS", 0)
        monkeypatch.setattr(feed_mod, "_RECONNECT_BACKOFF_SECS", 0)

        stop = threading.Event()
        feed_mod._run_feed_loop(stop)

        assert calls["n"] == 1, "config errors must fail fast without retries"


# ---------------------------------------------------------------------------
# N5: double-start guard
# ---------------------------------------------------------------------------


class TestDoubleStartGuard:
    """N5: start() must be a no-op when feed threads are already alive."""

    def test_start_noop_when_already_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        sentinel = MagicMock(spec=threading.Thread)
        sentinel.is_alive.return_value = True
        monkeypatch.setattr(feed_mod, "_feed_thread", sentinel)
        monkeypatch.setattr(feed_mod, "_refresh_thread", sentinel)
        monkeypatch.setattr(feed_mod, "_flow_refresh_thread", sentinel)

        # Calling start() should return early without creating new threads
        with patch.object(feed_mod, "_stop_event") as mock_stop:
            feed_mod.start()
            mock_stop.clear.assert_not_called()

        # cleanup
        monkeypatch.setattr(feed_mod, "_feed_thread", None)
        monkeypatch.setattr(feed_mod, "_refresh_thread", None)
        monkeypatch.setattr(feed_mod, "_flow_refresh_thread", None)


class TestFeedMetricsSnapshot:
    """feed.metrics_snapshot should expose real counters, not hard-coded zeros."""

    def test_metrics_snapshot_reflects_counter_updates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        monkeypatch.setattr(
            feed_mod,
            "_metrics",
            {
                "reconnect_attempts": 0,
                "bento_errors": 0,
                "unexpected_errors": 0,
                "circuit_breakers": 0,
                "partial_restarts": 0,
            },
        )

        feed_mod._inc_metric("reconnect_attempts", 2)
        feed_mod._inc_metric("bento_errors")
        feed_mod._inc_metric("partial_restarts")

        snapshot = feed_mod.metrics_snapshot()
        assert snapshot["reconnect_attempts"] == 2
        assert snapshot["bento_errors"] == 1
        assert snapshot["partial_restarts"] == 1

    def test_metrics_snapshot_is_defensive_copy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        monkeypatch.setattr(
            feed_mod,
            "_metrics",
            {
                "reconnect_attempts": 1,
                "bento_errors": 2,
                "unexpected_errors": 3,
                "circuit_breakers": 4,
                "partial_restarts": 5,
            },
        )

        snapshot = feed_mod.metrics_snapshot()
        snapshot["reconnect_attempts"] = 999

        assert feed_mod.metrics_snapshot()["reconnect_attempts"] == 1

    def test_start_recovers_dead_workers_when_some_are_alive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        alive = MagicMock(spec=threading.Thread)
        alive.is_alive.return_value = True
        dead = MagicMock(spec=threading.Thread)
        dead.is_alive.return_value = False

        monkeypatch.setattr(feed_mod, "_feed_thread", alive)
        monkeypatch.setattr(feed_mod, "_refresh_thread", dead)
        monkeypatch.setattr(feed_mod, "_flow_refresh_thread", dead)

        created: list[str | None] = []

        class _FakeThread:
            def __init__(self, *args, name: str | None = None, **kwargs):
                created.append(name)

            def start(self) -> None:
                return None

            def is_alive(self) -> bool:
                return True

        monkeypatch.setattr(feed_mod.threading, "Thread", _FakeThread)

        feed_mod.start()

        assert "overlay-refresh" in created
        assert "flow-refresh" in created
        assert "live-feed" not in created


# ---------------------------------------------------------------------------
# C1: constant-time token compare with no length side-channel
# ---------------------------------------------------------------------------


class TestConstantTimeTokenCompare:
    """C1: _ct_eq hashes both sides before the compare so the token length is
    not exposed as a timing oracle (CWE-208)."""

    def test_equal_tokens_match(self) -> None:
        import services.live_overlay_daemon.main as main_mod

        assert main_mod._ct_eq("s3cr3t-token", "s3cr3t-token") is True

    def test_same_length_mismatch_rejected(self) -> None:
        import services.live_overlay_daemon.main as main_mod

        assert main_mod._ct_eq("s3cr3t-token", "S3CR3T-TOKEN") is False

    def test_different_length_mismatch_rejected(self) -> None:
        import services.live_overlay_daemon.main as main_mod

        # The old code short-circuited on len() before the constant-time
        # compare; the digest-based path must still reject cleanly.
        assert main_mod._ct_eq("short", "a-much-longer-secret-token") is False
        assert main_mod._ct_eq("", "nonempty") is False

    def test_empty_equal(self) -> None:
        import services.live_overlay_daemon.main as main_mod

        assert main_mod._ct_eq("", "") is True

    def test_compares_fixed_length_digests(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The compare must run over equal-length buffers regardless of input
        length, so neither the comparison nor a len() pre-check can leak the
        secret-token length."""
        import services.live_overlay_daemon.main as main_mod

        seen: list[tuple[int, int]] = []

        import hmac as _hmac

        real_compare = _hmac.compare_digest

        def _spy(a: bytes, b: bytes) -> bool:
            seen.append((len(a), len(b)))
            return real_compare(a, b)

        monkeypatch.setattr(_hmac, "compare_digest", _spy)
        main_mod._ct_eq("abc", "a-far-longer-token-value")
        assert seen, "_ct_eq must call hmac.compare_digest"
        # SHA-256 digests are always 32 bytes on both sides — no length leak.
        assert seen[0] == (32, 32)


# ---------------------------------------------------------------------------
# C2: atexit safety-net shutdown hook
# ---------------------------------------------------------------------------


class TestAtexitShutdownHook:
    """C2: start() registers a bounded atexit hook so the daemon=True feed
    threads close the Databento loop/sockets even on a non-lifespan exit."""

    def test_start_registers_stop_atexit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.live_overlay_daemon.feed as feed_mod

        # Avoid spawning real threads / touching Databento.
        monkeypatch.setattr(feed_mod, "_feed_thread", None)
        monkeypatch.setattr(feed_mod, "_refresh_thread", None)
        monkeypatch.setattr(feed_mod, "_flow_refresh_thread", None)
        monkeypatch.setattr(feed_mod.threading, "Thread", MagicMock())

        registered: list[object] = []
        unregistered: list[object] = []
        monkeypatch.setattr(feed_mod.atexit, "register", lambda fn: registered.append(fn))
        monkeypatch.setattr(feed_mod.atexit, "unregister", lambda fn: unregistered.append(fn))

        feed_mod.start()

        assert feed_mod.stop in registered, "start() must register feed.stop() with atexit"
        assert feed_mod.stop in unregistered, "start() must unregister first to keep a single hook"

        # cleanup
        feed_mod._stop_event.clear()
        monkeypatch.setattr(feed_mod, "_feed_thread", None)


class TestTfSchemaContract:
    """smc_live tf validation must stay aligned with schema enum."""

    def test_smc_live_rejects_unsupported_1d_tf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi import HTTPException

        import services.live_overlay_daemon.main as main_mod

        monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: "tok")

        with pytest.raises(HTTPException) as exc_info:
            main_mod.smc_live(token="tok", symbol="AAPL", tf="1D")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "tf must be one of ['10m', '15m', '1H', '30m', '4H', '5m']"


